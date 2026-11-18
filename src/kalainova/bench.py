"""A camera test: one shot made on several models, side by side, before a shoot. A shot that sings
is made on models that sing it from its still and its line (`sing_models`), the line the same for
each, so the rows differ only in how each model sings.

Every bench take goes through the router and the take store like any other take, so it carries its
model, seed, cost, and how it read. It is marked as a bench take, which never replaces the take a
piece uses and does not count against a shot's take limits. Every model gets the same prompt, the
same start frame, and the same seeds, so a difference between rows comes from the model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config, consistency, shotmake, shots, takes, timeline
from .editor import singing
from .jobfs import ContractError, Job
from .providers import base, router
from .providers.contract import Billable, Pin, Request, SingRequest, VideoRequest

Say = Callable[[str], None]


@dataclass
class Row:
    model: str
    provider: str
    per_take: float
    own_price: bool  # the price table has a row for this model, not just for the capability


def parse_models(text: str) -> list[str]:
    found = list(dict.fromkeys(m.strip() for m in text.split(",") if m.strip()))
    if len(found) < 2:
        raise ContractError("a bench compares at least two models: --models a,b")
    return found


def _provider_of(job: Job, model: str, capability: str = "video") -> str:
    """The first provider in the job's list for this capability that names this model."""
    names = config.preference(capability, job.job)
    known: list[str] = []
    for name in names:
        try:
            offered = base.get(name).models(capability)
        except KeyError:
            continue
        if model in offered:
            return name
        known += offered
    raise ContractError(
        f"{job.id}: {model} is not under {capability}_models for any provider this job uses; "
        f"known: {', '.join(sorted(set(known))) or 'none'}"
    )


@dataclass
class _Setup:
    beat: dict[str, Any]
    span: float
    still: Path
    prompt: str
    aspect: str
    kw: shotmake.Held
    resolved: Any = None
    lock: dict[str, Any] | None = None
    line: Path | None = None  # the shot's line of the vocal stem, when it sings

    @property
    def capability(self) -> str:
        return "sing" if self.line else "video"


def _setup(job: Job, shot: str) -> _Setup:
    data = job.job
    packet = job.read("script_packet")
    beat = next((b for b in packet["beats"] if b["id"] == shot), None)
    if not beat:
        raise ContractError(f"{job.id}: no shot {shot}")
    if beat.get("visual_kind") != "video":
        raise ContractError(f"{job.id}: {shot} is a still, so there is nothing to bench")
    still = job.work / "beats" / f"{shot}.still.png"
    if not still.exists() or not job.has("asset_manifest"):
        raise ContractError(
            f"{job.id}: {shot} has no start frame yet. Make the stills first (run assets with "
            "brief.max_video_beats set to 0), so every model starts from the same picture"
        )
    manifest = job.read("asset_manifest")
    span = next(s["end_sec"] - s["start_sec"] for s in manifest["timeline"] if s["beat_id"] == shot)
    locked = consistency.for_job(job)
    resolved, lock = locked if locked else (None, {})
    kw = shotmake.shot_kw(resolved, lock, "video", beat, start=still)
    prompt = shots.motion_prompt(
        packet,
        beat,
        shotmake.style(data),
        has_start_image=True,
        limit=shots.word_limit(config.preference("video", data)),
    )
    prof = config.profile(data.get("profile") or "short-9x16")
    aspect = str(prof.get("aspect", "9:16"))
    line = job.work / "beats" / f"{shot}.voice.wav" if beat.get("sings") else None
    if line and shotmake.sung_line(job, beat, line) < singing.SUNG_MIN:
        raise ContractError(f"{job.id}: {shot} is not sung over its span, so it has no line")
    return _Setup(beat, float(span), still, prompt, aspect, kw, resolved, lock, line)


def _request_for(setup: _Setup, provider: str, model: str, say: Say) -> shotmake.Held:
    """What one model is given, worked out for that model rather than the stream's pinned one.

    A model that takes references gets the kit's, with the still as its first frame or its first
    reference by what it accepts; a model that takes none starts from the frame alone, said aloud.
    """
    pin = Pin(provider=provider, model=model)
    if not setup.kw.references:
        return shotmake.Held(pin=pin)
    if setup.line and base.get(provider).inputs("sing", model).references:
        return shotmake.Held(setup.kw.references, pin)  # the still first, then the kit
    if setup.line or not base.get(provider).inputs("video", model).references:
        say(f"{model} cannot take this shot's references, so it starts from the frame alone")
        return shotmake.Held(pin=pin)
    lock = dict(setup.lock or {})
    lock["generators"] = {
        **(lock.get("generators") or {}),
        "video": {"provider": provider, "model": model},
    }
    held = shotmake.shot_kw(setup.resolved, lock, "video", setup.beat, start=setup.still)
    return shotmake.Held(held.references, pin)


def conditioning(provider: str, model: str, held: shotmake.Held, sings: bool = False) -> str:
    """What a bench take was given, in words, so takes with different inputs are not read alike."""
    if sings:
        pictures = f", {len(held.references)} kit picture(s)" if held.references else ""
        return f"the still{pictures} and its line of the vocal"
    if not held.references:
        return "the start frame only"
    kit = len(held.references)
    if base.get(provider).inputs("video", model).start_with_references:
        return f"the start frame and {kit} kit reference(s)"
    return f"{kit} reference(s), the still among them; no start frame"


def estimate(job: Job, shot: str, models: list[str], count: int, say: Say = print) -> list[Row]:
    """What each model's takes should cost, said before anything is spent. Refuses over the cap."""
    setup = _setup(job, shot)
    rows = []
    table = config.studio().get("prices") or {}
    for model in models:
        provider = _provider_of(job, model, setup.capability)
        request = _request_for(setup, provider, model, say)
        asked = Billable(
            capability=setup.capability,
            duration=setup.span,
            image=True,
            references=bool(request.references),
        )
        quote = router.quote(job, asked, only=[provider], pin=request.pin)
        if quote is None:
            raise ContractError(f"{job.id}: {provider} is not ready, so {model} cannot be tested")
        if quote[1] is None:
            raise ContractError(f"{job.id}: no price for {model}, so its cost cannot be estimated")
        rows.append(Row(model, provider, quote[1], bool((table.get(provider) or {}).get(model))))
    total = sum(r.per_take for r in rows) * count
    for r in rows:
        note = "" if r.own_price else "  (no price of its own: the generic video rate)"
        say(f"{r.model}: about ${r.per_take * count:.2f} for {count} take(s){note}")
    say(f"bench total: about ${total:.2f}")
    cap = job.job.get("cost_cap")
    if total and cap is None:
        raise ContractError(f"{job.id}: a bench spends money, so the job needs a cost_cap")
    if cap is not None and total > float(cap) - job.committed():
        left = max(float(cap) - job.committed(), 0.0)
        raise ContractError(
            f"{job.id}: the bench is estimated at ${total:.2f} and the job has ${left:.2f} left "
            "under its cap; name fewer models, take fewer takes, or raise cost_cap"
        )
    return rows


def run(job: Job, shot: str, models: list[str], count: int = 1, say: Say = print) -> dict[str, Any]:
    """Make the shot on each model, and write one sheet with a row per model."""
    if count < 1:
        raise ContractError("a bench makes at least one take of each model")
    rows = estimate(job, shot, models, count, say)
    setup = _setup(job, shot)
    made: list[dict[str, Any]] = []
    failed: dict[str, str] = {}
    for row in rows:
        request = _request_for(setup, row.provider, row.model, lambda _: None)
        for i in range(count):
            n = takes.next_take_number(job, shot)

            def make(
                seed: int, dst: Path, request: shotmake.Held = request, row: Row = row
            ) -> tuple[Any, Any]:
                clip: Request = VideoRequest(
                    prompt=setup.prompt,
                    dst=dst,
                    duration=setup.span,
                    aspect=setup.aspect,
                    start=setup.still,
                    seed=seed,
                    sound=False,
                    references=request.references,
                    pin=request.pin,
                )
                if setup.line:  # the same line for every model, sung in the call that makes it
                    clip = SingRequest(
                        prompt=setup.prompt,
                        still=setup.still,
                        audio=setup.line,
                        dst=dst,
                        aspect=setup.aspect,
                        references=request.references,
                        seed=seed,
                        pin=request.pin,
                    )
                return router.generate(job, clip, only=[row.provider], note=f"bench {row.model}")

            try:
                take = takes.attempt(
                    job,
                    shot,
                    n,
                    suffix=".mp4",
                    make=make,
                    assess=shotmake.judged_sung(takes.assess_clip, setup.line)
                    if setup.line
                    else takes.assess_clip,
                    prompt=setup.prompt,
                    seed=takes.seed_for(setup.prompt, i),
                    extra={
                        "bench": True,
                        "conditioning": conditioning(
                            row.provider, row.model, request, bool(setup.line)
                        ),
                    },
                )
            except RuntimeError as exc:
                failed[row.model] = str(exc)[:300]
                say(f"{row.model}: no take: {exc}")
                break
            made.append(take)
            say(f"{row.model} take {take['n']}, given {take['conditioning']}: {_reading(take)}")
    sheet = _sheet(job, shot, made)
    return {"takes": made, "failed": failed, "sheet": sheet}


def _reading(take: dict[str, Any]) -> str:
    readings = {k: v for k, v in (take.get("readings") or {}).items() if k != "score"}
    state = "moves" if take["ok"] else "MISSES the motion promise"
    cost = f", ${take['cost']:.2f}" if take.get("cost") else ""
    return f"{state} {readings}{cost}, seed {take['seed']}"


def _sheet(job: Job, shot: str, made: list[dict[str, Any]]) -> Path | None:
    if not made:
        return None
    rows = [
        (
            f"{t['model']}  take {t['n']}  given {t.get('conditioning', '?')}  {_reading(t)}",
            job.work / t["file"],
        )
        for t in made
    ]
    folder = job.work / "bench"
    folder.mkdir(exist_ok=True)
    return timeline.bench_sheet(rows, folder / f"{shot}.jpg")
