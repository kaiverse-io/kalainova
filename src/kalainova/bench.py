"""A camera test: one shot made on several models, side by side, before a shoot.

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
from .jobfs import ContractError, Job
from .providers import base, router

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


def _provider_of(job: Job, model: str) -> str:
    """The first provider in the job's video list that names this model."""
    listed = config.studio().get("video_models") or {}
    names = config.preference("video", job.job)
    for name in names:
        if model in (listed.get(name) or {}):
            return name
    known = sorted({m for name in names for m in (listed.get(name) or {})})
    raise ContractError(
        f"{job.id}: {model} is not under video_models for any provider this job uses; "
        f"known: {', '.join(known) or 'none'}"
    )


@dataclass
class _Setup:
    beat: dict[str, Any]
    span: float
    still: Path
    prompt: str
    aspect: str
    kw: dict[str, Any]


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
    return _Setup(beat, float(span), still, prompt, str(prof.get("aspect", "9:16")), kw)


def _request_for(setup: _Setup, provider: str, model: str, say: Say) -> dict[str, Any]:
    """The reference images go only to a model that takes them, so no model is refused for them."""
    kw = {k: v for k, v in setup.kw.items() if k != "model"}
    if kw.get("references") and not base.get(provider).reference_support("video", model):
        say(f"{model} cannot take this shot's references, so it starts from the frame alone")
        kw = {}
    return {**kw, "model": model}


def estimate(job: Job, shot: str, models: list[str], count: int, say: Say = print) -> list[Row]:
    """What each model's takes should cost, said before anything is spent. Refuses over the cap."""
    setup = _setup(job, shot)
    rows = []
    table = config.studio().get("prices") or {}
    for model in models:
        provider = _provider_of(job, model)
        request = _request_for(setup, provider, model, say)
        quote = router.quote(
            job,
            "video",
            only=[provider],
            duration=setup.span,
            image=True,
            references=bool(request.get("references")),
            model=model,
        )
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
                seed: int, dst: Path, request: dict[str, Any] = request, row: Row = row
            ) -> tuple[Any, Any]:
                return router.generate(
                    job,
                    "video",
                    "video",
                    setup.prompt,
                    dst,
                    duration=setup.span,
                    aspect=setup.aspect,
                    image=setup.still,
                    seed=seed,
                    audio=False,
                    only=[row.provider],
                    note=f"bench {row.model}",
                    est={
                        "duration": setup.span,
                        "image": True,
                        "references": bool(request.get("references")),
                        "model": row.model,
                    },
                    **request,
                )

            try:
                take = takes.attempt(
                    job,
                    shot,
                    n,
                    suffix=".mp4",
                    make=make,
                    assess=takes.assess_clip,
                    prompt=setup.prompt,
                    seed=takes.seed_for(setup.prompt, i),
                    extra={"bench": True},
                )
            except RuntimeError as exc:
                failed[row.model] = str(exc)[:300]
                say(f"{row.model}: no take: {exc}")
                break
            made.append(take)
            say(f"{row.model} take {take['n']}: {_reading(take)}")
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
    rows = [(f"{t['model']}  take {t['n']}  {_reading(t)}", job.work / t["file"]) for t in made]
    folder = job.work / "bench"
    folder.mkdir(exist_ok=True)
    return timeline.bench_sheet(rows, folder / f"{shot}.jpg")
