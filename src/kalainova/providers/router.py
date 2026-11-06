"""The one way the engine calls a model.

generate() walks the job's provider list and, for each attempt, applies the same rules:

  price     a job with a cost cap refuses a provider it cannot estimate
  deadline  a call that outlives its deadline is abandoned, and its estimate is charged
  failure   a provider failure moves to the next listed provider and says so on stderr;
            a bug in an adapter (TypeError, AttributeError) is raised, not hidden
  output    a file must match the request, and reaches its destination only after that
  reuse     a paid file is recorded the moment it exists, so a restart does not pay twice

Only providers named in the list are tried. Nothing is added to it here.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from .. import config, media
from ..jobfs import ContractError, CostCapExceeded, Job
from . import base

# capability -> the position of the destination path in the call's arguments
OUTPUT_ARG = {"voice": 1, "image": 1, "video": 1, "music": 1, "song": 1, "sfx": 1}
# OSError covers connection, timeout, and HTTP errors. ValueError, KeyError, and IndexError cover a malformed reply.
PROVIDER_FAILURES = (OSError, RuntimeError, ValueError, KeyError, IndexError)
DEFAULT_DEADLINE_SEC = 600.0
GENERATIONS = "generations.jsonl"
ASPECT_TOLERANCE = 0.03
MIN_SCALE = 0.5  # the editor can upscale a large image, not rescue a thumbnail


class ProviderError(ContractError):
    """Every listed provider was tried and none produced a result."""


class NoProvider(ProviderError, LookupError):
    """No listed provider implements the capability and is ready to use."""


class ProviderTimeout(TimeoutError):
    pass


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
        elif not p.available():
            skipped.append(f"{name}: missing {', '.join(p.missing_env())}")
        else:
            usable.append(p)
    return usable, skipped


def available(job: Job, capability: str) -> bool:
    return bool(_usable(capability, config.preference(capability, job.job))[0])


def _deadline(capability: str) -> float:
    return float((config.studio().get("deadlines_sec") or {}).get(capability, DEFAULT_DEADLINE_SEC))


def _call(fn, args: tuple, kw: dict, deadline: float):
    """Run on a worker thread so the engine can stop waiting. Python cannot kill the thread, so an
    abandoned call may finish later. It writes to its own temporary path, never to the destination."""
    box: dict[str, Any] = {}

    def run():
        try:
            box["result"] = fn(*args, **kw)
        except BaseException as exc:  # handed to the caller, which decides what it means
            box["error"] = exc

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(deadline)
    if worker.is_alive():
        raise ProviderTimeout(f"no result after {deadline:g}s")
    if "error" in box:
        raise box["error"]
    return box["result"]


def _check_output(capability: str, path: Path, kw: dict) -> None:
    """Refuse a file that is unreadable or is not what was asked for. Raises ValueError or OSError."""
    if capability == "image":
        from PIL import Image

        with Image.open(path) as im:
            width, height = im.size
            im.verify()
        want_w, want_h = kw.get("width"), kw.get("height")
        if want_w and want_h:
            if abs(width / height - want_w / want_h) > ASPECT_TOLERANCE * (want_w / want_h):
                raise ValueError(f"image is {width}x{height}, wrong shape for {want_w}x{want_h}")
            if width < want_w * MIN_SCALE:
                raise ValueError(f"image is {width}x{height}, too small for {want_w}x{want_h}")
    elif media.duration(path) <= 0:
        raise ValueError("file has no duration")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _request_key(capability: str, fn_name: str, args: tuple, kw: dict) -> str:
    def plain(value):
        if isinstance(value, Path):
            return _sha256(value) if value.is_file() else str(value)
        if isinstance(value, dict):
            return {k: plain(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [plain(v) for v in value]
        return value

    at = OUTPUT_ARG[capability]
    request = {
        "capability": capability,
        "fn": fn_name,
        "dst": Path(args[at]).name,
        "args": [plain(a) for i, a in enumerate(args) if i != at],
        "kw": {k: plain(v) for k, v in kw.items()},
    }
    return hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()


def _saved(
    job: Job, key: str, dst: Path, names: list[str]
) -> tuple[base.Provider, base.Result] | None:
    """A recorded file, if it is still the same bytes from a provider this job still lists."""
    path = job.folder / GENERATIONS
    if not path.exists() or not dst.is_file():
        return None
    entries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    entry = next((e for e in reversed(entries) if e["key"] == key), None)
    if not entry or entry["provider"] not in names or entry["sha256"] != _sha256(dst):
        return None
    provider = base.get(entry["provider"])
    return provider, base.Result(
        path=dst, model=entry["model"], words=entry["words"], meta=entry["meta"]
    )


def _record(job: Job, key: str, provider: base.Provider, res: base.Result, dst: Path) -> None:
    entry = {
        "key": key,
        "provider": provider.name,
        "model": res.model,
        "file": dst.name,
        "sha256": _sha256(dst),
        "cost": round(res.cost, 6),
        "words": res.words,
        "meta": res.meta,
    }
    with job.locked():
        with open(job.folder / GENERATIONS, "a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def generate(
    job: Job,
    capability: str,
    fn_name: str,
    *args,
    est: dict | None = None,
    note: str = "",
    fresh: bool = False,
    only: list[str] | None = None,
    **kw,
) -> tuple[base.Provider, base.Result]:
    names = only or config.preference(capability, job.job)
    usable, skipped = _usable(capability, names)
    if not usable:
        raise NoProvider(
            f"{job.id}: no provider for {capability}: tried {', '.join(names) or 'nothing'} "
            f"({'; '.join(skipped) or 'none listed'})"
        )
    has_output = capability in OUTPUT_ARG
    dst = Path(args[OUTPUT_ARG[capability]]) if has_output else None
    key = _request_key(capability, fn_name, args, kw) if has_output else ""
    if has_output and not fresh:
        saved = _saved(job, key, dst, names)
        if saved:
            print(
                f"{job.id}: {capability}: reused {dst.name} from {saved[0].name}, no new charge",
                file=sys.stderr,
            )
            return saved
    cap = job.job.get("cost_cap")
    errors = list(skipped)
    for p in usable:
        estimate = p.estimate(capability, **(est or {}))
        if estimate is None and cap is not None:
            errors.append(f"{p.name}: no price for {capability}, and this job has a cost cap")
            continue
        job.reserve(p.name, capability, estimate or 0.0)
        call_args = list(args)
        attempt = None
        if has_output:
            attempt = dst.with_name(f".{uuid.uuid4().hex[:8]}.{dst.name}")
            call_args[OUTPUT_ARG[capability]] = attempt
        try:
            res = _call(getattr(p, fn_name), tuple(call_args), kw, _deadline(capability))
        except CostCapExceeded:
            raise
        except ContractError:
            raise
        except ProviderTimeout as exc:
            job.charge(
                p.name,
                capability,
                estimate or 0.0,
                f"{note or fn_name}: timed out, may have been billed",
            )
            errors.append(f"{p.name}: {exc}")
            continue
        except PROVIDER_FAILURES as exc:
            errors.append(f"{p.name}: {type(exc).__name__}: {str(exc)[:300]}")
            continue
        if has_output:
            if not attempt.is_file():
                errors.append(f"{p.name}: returned no file")
                continue
            try:
                _check_output(capability, attempt, kw)
            except PROVIDER_FAILURES as exc:
                attempt.unlink(missing_ok=True)
                job.charge(p.name, capability, res.cost, f"{note or fn_name}: output rejected")
                errors.append(f"{p.name}: rejected output: {str(exc)[:200]}")
                continue
            os.replace(attempt, dst)
            res.path = dst
            if not p.placeholder:
                _record(job, key, p, res, dst)
        if errors:
            print(
                f"{job.id}: {capability}: used {p.name} after: {'; '.join(errors)}", file=sys.stderr
            )
        job.charge(p.name, capability, res.cost, note or fn_name)
        return p, res
    raise ProviderError(f"{job.id}: every provider failed for {capability}: {'; '.join(errors)}")
