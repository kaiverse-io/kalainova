"""The one way the engine calls a model.

generate() takes one typed request (providers/contract.py), walks the job's provider list, and for
each attempt applies the same rules:

  price     a job with a cost cap refuses a provider it cannot estimate; a price that cannot be
            checked refuses (providers/prices.py)
  gates     a paid call passes the studio's gates first (gates.py): none goes while spend is
            stopped, past the studio's signed limits, or without a signed package covering it once
  deadline  a call that outlives its deadline is abandoned, and its estimate is charged
  failure   a provider failure moves to the next listed provider and says so on stderr; a request
            the vendor refuses as malformed stops the walk, since the engine's mapping is at fault;
            a bug in an adapter (TypeError, AttributeError) is raised, not hidden
  output    a file must match the request and hold a picture, and only then reaches its destination
  reuse     a paid file is recorded the moment it exists, so a restart does not pay twice
  rehearsal while one is open, nothing is sent: a paid provider that cannot rehearse refuses
  pins      a pinned model goes to the provider the pin names only; any other uses its own default

Each attempt gets a fresh `Context` with its labels and a `Receipt` the adapter fills, so what the
vendor said about the call is kept whether the call succeeds or fails.

Only providers named in the list are tried. Nothing is added to it here.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from .. import config, gates, media, trace
from ..jobfs import ContractError, Job
from . import base, prices, records, rehearsal
from .contract import (
    RECORDED,
    Billable,
    BilledError,
    Context,
    ImageRequest,
    InvalidRequestError,
    MotionRequest,
    Pin,
    RefusalError,
    Request,
    Result,
)

# OSError covers connection, timeout, and HTTP errors. ValueError, KeyError, and IndexError cover a
# malformed reply.
PROVIDER_FAILURES = (OSError, RuntimeError, ValueError, KeyError, IndexError, RefusalError)
DEFAULT_DEADLINE_SEC = 600.0
GENERATIONS = records.GENERATIONS
PICTURE_OUTPUTS = ("image", "video", "motion", "lipsync", "graphics")
SOUND_OUTPUTS = ("song", "music")
ASPECT_TOLERANCE = 0.03
MIN_SCALE = 0.5  # the editor can upscale a large image, not rescue a thumbnail


class ProviderError(ContractError):
    """Every listed provider was tried and none produced a result."""


class NoProviderError(ProviderError, LookupError):
    """No listed provider implements the capability and is ready to use."""


class ProviderTimeoutError(TimeoutError):
    pass


def _rehearses_first(job: Job, capability: str, names: list[str]) -> None:
    """In a rehearsal, the first listed provider must be one that rehearses, key or not.

    A paid provider skipped only for its missing key is the one the real run calls once the key is
    set, so the rehearsal stops at it rather than showing the next provider's route and price.
    """
    for name in names:
        try:
            p = base.get(name)
        except KeyError:
            continue
        if capability not in p.capabilities:
            continue
        if not (p.free or p.rehearses):
            raise ContractError(
                f"{job.id}: {name} is listed first for {capability} and cannot rehearse, so the "
                "rehearsal stops before it; pin the job to a provider that can"
            )
        return


def _corrected(
    job: Job, p: base.Provider, billable: Billable, model: str | None = None
) -> float | None:
    """The provider's estimate, raised where the vendor's list price or this studio's own bills
    say the price table is low (providers/prices.py). A quote and a reservation both come here."""
    estimate = p.estimate(billable, model)
    if p.free:
        return estimate
    try:
        factor, why = prices.correction(job, p, billable, model)
    except Exception as exc:  # noqa: BLE001 - any failure to check a price refuses the paid call
        raise ContractError(
            f"{job.id}: {billable.capability} on {p.name}: the price could not be checked ({exc}), "
            "so nothing is spent; fix the studio's price records and run again"
        ) from exc
    if estimate and factor > 1:
        print(
            f"{job.id}: {billable.capability} on {p.name}: estimate x{factor}, from {why}",
            file=sys.stderr,
        )
        return round(estimate * factor, 6)
    return estimate


def _usable(capability: str, names: list[str]) -> tuple[list[base.Provider], list[str]]:
    usable, skipped = [], []
    for name in names:
        try:
            p = base.get(name)
        except KeyError:
            skipped.append(f"{name}: unknown provider")
            continue
        if capability not in p.capabilities:
            skipped.append(f"{name}: no {capability}")
        elif not p.available(capability):
            skipped.append(f"{name}: missing {', '.join(p.missing_env(capability))}")
        else:
            usable.append(p)
    return usable, skipped


def available(job: Job, capability: str) -> bool:
    return bool(_usable(capability, config.preference(capability, job.job))[0])


def refuse_too_long(job: Job, capability: str, seconds: float) -> None:
    """Before any spend: a model's stated longest output is a limit; a longer ask is not made."""
    first = first_usable(job, capability)
    if not first:
        return
    most = first.inputs(capability).longest_sec
    if most and seconds > most:
        raise ProviderError(
            f"{job.id}: {first.default_model(capability)} makes at most {most:g}s and the piece "
            f"asks for {seconds:g}s; shorten it or list a model that makes longer tracks"
        )


def first_usable(job: Job, capability: str) -> base.Provider | None:
    """The provider a call would try first, or None when none is ready."""
    usable, _ = _usable(capability, config.preference(capability, job.job))
    return usable[0] if usable else None


def _pinned(pin: Pin | None, provider: str) -> str | None:
    return pin.model if pin and pin.provider == provider else None


def quote(
    job: Job, billable: Billable, *, only: list[str] | None = None, pin: Pin | None = None
) -> tuple[str, float | None] | None:
    """What the first ready provider would charge for one call, without making it.

    None when no provider is ready. The estimate is None when that provider has no price for it.
    """
    usable, _ = _usable(
        billable.capability, only or config.preference(billable.capability, job.job)
    )
    if not usable:
        return None
    return usable[0].name, usable[0].estimate(billable, _pinned(pin, usable[0].name))


def first_listed(job: Job, capability: str, only: list[str] | None = None) -> base.Provider | None:
    """The provider the job names first for this capability, whether or not its key is loaded."""
    for name in only or config.preference(capability, job.job):
        try:
            p = base.get(name)
        except KeyError:
            continue
        if capability in p.capabilities:
            return p
    return None


def price(
    job: Job, billable: Billable, *, only: list[str] | None = None, pin: Pin | None = None
) -> tuple[str, float | None, list[str]] | None:
    """What the first listed provider would charge, and what it still needs before a paid run.
    A price comes from the table, so a quote needs no key. None when no provider is listed."""
    p = first_listed(job, billable.capability, only)
    if p is None:
        return None
    model = _pinned(pin, p.name)
    return p.name, _corrected(job, p, billable, model), p.missing_env(billable.capability)


def _deadline(capability: str) -> float:
    return float((config.studio().get("deadlines_sec") or {}).get(capability, DEFAULT_DEADLINE_SEC))


def _call(fn: Callable[..., Result], args: tuple[Any, ...], deadline: float | None) -> Result:
    """Run on a worker thread so the engine can stop waiting. Python cannot kill the thread, so an
    abandoned call may finish later. It writes to its own temporary path, never to the
    destination."""
    box: dict[str, Any] = {}

    def run() -> None:
        try:
            box["result"] = fn(*args)
        except BaseException as exc:  # handed to the caller, which decides what it means
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(deadline)
    if worker.is_alive():
        raise ProviderTimeoutError(f"no result after {deadline:g}s")
    if "error" in box:
        raise box["error"]
    result: Result = box["result"]
    return result


def _check_output(request: Request, path: Path) -> None:
    """Refuse a file that is unreadable or not what was asked for. Raises ValueError or OSError."""
    capability = request.capability
    if isinstance(request, ImageRequest):
        from PIL import Image

        with Image.open(path) as im:
            width, height = im.size
            im.verify()
        want_w, want_h = request.width, request.height
        if want_w and want_h:
            if abs(width / height - want_w / want_h) > ASPECT_TOLERANCE * (want_w / want_h):
                raise ValueError(f"image is {width}x{height}, wrong shape for {want_w}x{want_h}")
            if width < want_w * MIN_SCALE:
                raise ValueError(f"image is {width}x{height}, too small for {want_w}x{want_h}")
    elif media.duration(path) <= 0:
        raise ValueError("file has no duration")
    if capability in PICTURE_OUTPUTS and not media.has_picture(path):
        raise ValueError("no picture: one flat tone throughout, the model's decode failed")
    if capability in SOUND_OUTPUTS and not media.has_sound(path):
        raise ValueError("no sound: the file is silent, the model's decode failed")


def _settle(p: base.Provider, res: Result, ctx: Context) -> None:
    """The result's typed facts under the engine's names, then its price checked against the
    vendor's own figure. An adapter's meta never overrides a name the engine records."""
    res.meta = {k: v for k, v in (res.meta or {}).items() if k not in RECORDED}
    res.meta.update(res.recorded())
    records.settle_at_vendor(p, res, ctx.receipt)


def generate(
    job: Job,
    request: Request,
    *,
    note: str = "",
    fresh: bool = False,
    only: list[str] | None = None,
) -> tuple[base.Provider, Result]:
    capability = request.capability
    names = only or config.preference(capability, job.job)
    usable, skipped = _usable(capability, names)
    if not usable:
        raise NoProviderError(
            f"{job.id}: no provider for {capability}: tried {', '.join(names) or 'nothing'} "
            f"({'; '.join(skipped) or 'none listed'})"
        )
    dst, key = request.output(), request.key()
    if dst is not None and not fresh:
        saved = records.saved(job, key, dst, names)
        if saved:
            print(
                f"{job.id}: {capability}: reused {dst.name} from {saved[0].name}, no new charge",
                file=sys.stderr,
            )
            return saved
    if rehearsal.active() is not None:
        _rehearses_first(job, capability, names)
    errors = list(skipped)
    for p in usable:
        res = _attempt(job, p, request, key, note or request.method, errors)
        if res is None:
            continue
        if errors:
            print(
                f"{job.id}: {capability}: used {p.name} after: {'; '.join(errors)}", file=sys.stderr
            )
        return p, res
    raise ProviderError(f"{job.id}: every provider failed for {capability}: {'; '.join(errors)}")


def _priced(
    job: Job, p: base.Provider, request: Request, errors: list[str]
) -> tuple[bool, float | None]:
    """Whether this provider may be tried under the job's cap, and its corrected estimate."""
    capability, cap = request.capability, job.job.get("cost_cap")
    estimate = _corrected(job, p, request.billable(), request.model_for(p.name))
    if estimate is None and cap is not None:
        errors.append(f"{p.name}: no price for {capability}, and this job has a cost cap")
        return False, None
    if not estimate and not p.free and cap is not None:
        # A priced call that estimates to nothing would go out unseen by the cap.
        errors.append(
            f"{p.name}: the estimate for {capability} is zero, and this job has a cost cap; "
            "the caller must say how much it is asking for"
        )
        return False, None
    return True, estimate


def _attempt(
    job: Job, p: base.Provider, request: Request, key: str, note: str, errors: list[str]
) -> Result | None:
    """One provider's try. A result, or None to move on to the next; raises what must stop."""
    capability = request.capability
    ok, estimate = _priced(job, p, request, errors)
    if not ok:
        return None
    dry = rehearsal.active()
    if dry is not None and not (p.free or p.rehearses):
        raise ContractError(
            f"{job.id}: {p.name} cannot rehearse {capability}, so the rehearsal stops before it"
        )
    one = _Try(job, p, request, key, note, errors, estimate)
    hold = partial(job.reserve, p.name, capability, estimate or 0.0)
    if not p.free and dry is None:
        gates.refuse_paid(job, p.name, capability)
        asked = gates.Call(job=job, provider=p.name, capability=capability, key=key,
                           model=one.routed, estimate=estimate or 0.0, attempt=one.aid)  # fmt: skip
        one.allowed, one.reservation = gates.admit(asked, hold)
        one.ctx = replace(one.ctx, signed=one.allowed.signed if one.allowed else None)
    else:
        one.reservation = hold()
    if dry is not None and not p.free:
        dry.begin(one.aid, request, p.name, estimate, note, key=key, model=one.model,
                  routed=one.routed, shot=one.ctx.labels.get("shot", ""))  # fmt: skip
    try:
        res = _call(getattr(p, request.method), (one.sent, one.ctx), one.limit)
    except BaseException as exc:  # noqa: BLE001 - each kind is sorted in _Try.failed
        one.failed(exc)
        return None
    return one.kept(res, dry)


class _Try:
    """One attempt at one provider: its id, its context, and how its outcome is written down."""

    def __init__(
        self,
        job: Job,
        p: base.Provider,
        request: Request,
        key: str,
        note: str,
        errors: list[str],
        estimate: float | None,
    ) -> None:
        self.job, self.p, self.request, self.key, self.note = job, p, request, key, note
        self.errors, self.estimate = errors, estimate
        self.reservation: str | None = None
        self.allowed: gates.Allowed | None = None  # the signed entry a paid call is spent against
        self.aid, self.model = uuid.uuid4().hex[:12], request.model_for(p.name)
        # the model it goes to, as a package names it: the pin, else the provider's default
        self.routed = self.model or p.default_model(
            request.capability, references=request.billable().references
        )
        self.dst = request.output()
        self.attempt = self.dst.with_name(f".{self.aid}.{self.dst.name}") if self.dst else None
        self.sent = request.writing_to(self.attempt) if self.attempt else request
        deadline = _deadline(request.capability)
        self.limit = None if p.self_timed else deadline
        self.ctx = Context(
            job=job.id,
            attempt=self.aid,
            labels={"job": job.id, "attempt": self.aid, **trace.labels()},
            model=self.model,
            deadline_sec=deadline if p.self_timed else None,
        )
        self.trace = partial(
            records.trace_attempt, job, request.capability, p, datetime.now(UTC).isoformat(),
            time.monotonic(), self.model, self.aid, self.ctx.receipt,
        )  # fmt: skip

    def charge(
        self, amount: float, why: str, made: str | None, meta: dict[str, Any] | None = None
    ) -> None:
        audit = records.audit(self.aid, made, meta, self.ctx.receipt)
        if self.allowed is not None:
            audit.update(package=self.allowed.package, package_entry=self.allowed.entry,
                         signed_by=self.allowed.signer)  # fmt: skip
        note = f"{self.note}: {why}" if why else self.note
        self.job.charge(self.p.name, self.request.capability, amount, note, self.reservation, audit)

    def _moved_on(self, said: str) -> None:
        self.errors.append(f"{self.p.name}: {said}")

    def failed(self, exc: BaseException) -> None:
        """Write a failed call down, then move on, or raise what must stop the walk."""
        kind, said = type(exc).__name__, str(exc)
        if isinstance(exc, TimeoutError):  # ours, or an adapter's own wait: either may be billed
            self.trace(outcome="timeout", estimate=self.estimate, settled=self.estimate or 0.0,
                       error_class=kind, detail=said)  # fmt: skip
            self.charge(self.estimate or 0.0, "timed out, may have been billed", self.model)
            return self._moved_on(said)
        if isinstance(exc, BilledError):
            self.trace(outcome="error", estimate=self.estimate, settled=exc.billed,
                       error_class=kind, detail=said)  # fmt: skip
            self.charge(exc.billed, "billed, then failed", self.model)
            return self._moved_on(said[:300])
        self.job.release(self.reservation)
        if self.allowed is not None:  # nothing was billed, so the signed entry is not used up
            gates.give_back(self.job, self.aid, kind)
        if isinstance(exc, ContractError) or not isinstance(exc, PROVIDER_FAILURES):
            raise exc  # a rule the engine set, a bug in an adapter, or the cap: nothing left held
        refused = isinstance(exc, RefusalError)
        self.trace(outcome="refused" if refused else "error", estimate=self.estimate,
                   error_class=kind, detail=said)  # fmt: skip
        if isinstance(
            exc, InvalidRequestError
        ):  # the engine's mapping is wrong; a fallback hides it
            raise ProviderError(
                f"{self.job.id}: {self.p.name} refused the {self.request.capability} request as "
                f"malformed, so no other provider is tried and nothing more is spent: {said[:400]}"
            ) from exc
        return self._moved_on(f"{kind}: {said[:300]}")

    def kept(self, res: Result, dry: rehearsal.Rehearsal | None) -> Result | None:
        """A returned call, settled, its file checked and moved into place, and written down."""
        _settle(self.p, res, self.ctx)
        made = res.model or self.model
        prices.learn(self.job, self.p.name, made or "", res.meta)
        if self.attempt is not None and self.dst is not None:
            problem = self._file_problem()
            if problem:
                self.trace(outcome="error", estimate=self.estimate, settled=res.cost,
                           meta=res.meta, error_class=problem[0], detail=problem[1])  # fmt: skip
                self.charge(res.cost, problem[2], made, res.meta)
                self._moved_on(problem[3])
                return None
            if dry is not None and not self.p.free:
                dry.settle(self.aid, res.cost, res.model, res.meta)
            os.replace(self.attempt, self.dst)
            res.path = self.dst
            if not self.p.placeholder:
                records.record(
                    self.job, self.key, self.p, res, self.dst, self.aid, self.ctx.receipt
                )
        self.charge(res.cost, "", made, res.meta)
        self.trace(outcome="ok", estimate=self.estimate, settled=res.cost, made=res.model or None,
                   model_version=res.version, meta=res.meta)  # fmt: skip
        return res

    def _file_problem(self) -> tuple[str, str, str, str] | None:
        """Why the returned file cannot be kept: error class, detail, ledger note, walk note."""
        assert self.attempt is not None
        if not self.attempt.is_file():
            return "NoFile", "the provider returned no file", "no file", "returned no file"
        try:
            _check_output(self.sent, self.attempt)
        except PROVIDER_FAILURES as exc:
            self.attempt.unlink(missing_ok=True)
            said = f"output rejected: {exc}"
            return type(exc).__name__, said, "output rejected", f"rejected output: {str(exc)[:200]}"
        return None


def motion(job: Job, character_image: Path, driving_video: Path, dst: Path, **kw: Any) -> Path:
    """Transfer the driving clip's motion to a character image through the selected provider."""
    request = MotionRequest(character=character_image, driving=driving_video, dst=dst, **kw)
    _, result = generate(job, request, note="motion transfer")
    return result.path or dst
