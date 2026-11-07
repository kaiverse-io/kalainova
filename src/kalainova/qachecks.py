"""The checks QA runs that each ask one question of a piece, kept apart from the running of them."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import bar, config, consistency, kitchecks, prompts, shots, timeline
from .jobfs import ContractError, CostCapExceeded, Job
from .providers import router

Fields = dict[str, Any]

# Files that came from a person or the engine itself, so there is no model licence to read.
NO_LICENCE = {"operator", "kit", "chained", "clip", "track", "local"}


def promise_checks(data: Fields, am: Fields) -> list[Fields]:
    """A shot that asked to move and did not. Only a person can accept that, on the job itself."""
    breaks = am.get("promise_breaks") or []
    if not breaks:
        return []
    from .publish import placeholder_assets

    forgiven = (data.get("brief") or {}).get("allow_stills") or placeholder_assets(am)
    named = ", ".join(b["beat_id"] for b in breaks)
    return [
        {
            "id": "delivery.motion_promise",
            "status": "warn" if forgiven else "fail",
            "detail": f"asked to move and did not: {named}",
        }
    ]


def licence_checks(am: Fields) -> list[Fields]:
    """What each model's terms ask of whoever releases this. A person reads and meets them."""
    unknown: set[str] = set()
    limited: set[str] = set()
    owed: set[str] = set()
    for asset in am["assets"]:
        provider = asset.get("provider")
        if not provider or provider in NO_LICENCE:
            continue
        model = str(asset.get("model", "")).split(":")[0]
        terms = config.licence_for(provider, model)
        if not terms:
            unknown.add(f"{provider}/{model}")
            continue
        if terms.get("commercial") is False:
            limited.add(f"{provider}/{model}")
        owed.update(str(o) for o in terms.get("obligations") or [])
    out = []
    if unknown:
        detail = f"nobody has read the terms of {sorted(unknown)}"
        out.append({"id": "rights.model_licence", "status": "warn", "detail": detail})
    if limited:
        detail = f"terms not confirmed for commercial use: {sorted(limited)}"
        out.append({"id": "rights.commercial_use", "status": "warn", "detail": detail})
    if owed:
        out.append(
            {"id": "rights.obligations", "status": "warn", "detail": "; ".join(sorted(owed))}
        )
    return out


def sound_checks(prof: Fields, am: Fields) -> list[Fields]:
    """What a premium mix would have that this one lacks. Only a person can say if it matters."""
    if prof.get("delivery") != "mezzanine":
        return []
    out = []
    if not any(a.get("role") == "sfx" for a in am["assets"]):
        detail = "voice and music only: no sound of the place under the picture"
        out.append({"id": "sound.layers", "status": "warn", "detail": detail})
    lossy = bar.sources.lossy_sources(am)
    if lossy:
        detail = f"{lossy} reached the mix through lossy audio, which no master can win back"
        out.append({"id": "sound.source_quality", "status": "warn", "detail": detail})
    return out


def plan_checks(data: Fields, packet: Fields) -> list[Fields]:
    brief = data.get("brief") or {}
    found = shots.review(
        packet,
        budget=int(brief.get("max_video_beats", 3)),
        allow_stills=True,
        wants_video="video" in data.get("media", []),
    )
    return [{**p, "status": "warn"} for p in found]


def cut_checks(final: Path, em: Fields) -> list[Fields]:
    if len(em.get("cuts", [])) < 2:
        return []
    bad = [c for c in timeline.cut_report(final, em["cuts"]) if c["flagged"]]
    if not bad:
        return [{"id": "edit.cuts", "status": "pass", "detail": "no click or flash at any cut"}]
    spots = ", ".join(f"{c['at_sec']:.2f}s" for c in bad[:8])
    detail = f"{len(bad)} cuts have a click or a flash: {spots}"
    return [{"id": "edit.cuts", "status": "warn", "detail": detail}]


def judge_script(packet: Fields) -> str:
    return str(
        [
            {
                "id": b["id"],
                "line": b["text"],
                "cue": b.get("visual_cue", ""),
                "moves": b.get("visual_kind") == "video",
            }
            for b in packet["beats"]
        ]
    )


def shape(prof: Fields) -> str:
    width, height = prof.get("width", 1), prof.get("height", 1)
    return "vertical" if height > width else "square" if height == width else "landscape"


def judged_shots(judge: Fields) -> list[Fields]:
    bad = [
        f"{s.get('id')}: {s.get('note') or 'see the sheet'}"
        for s in judge.get("shots") or []
        if s.get("moved") is False
        or s.get("geometry_ok") is False
        or s.get("matches_previous") is False
    ]
    if not judge.get("shots"):
        return []
    detail = "; ".join(bad)[:600] or "every shot read as it should"
    return [{"id": "judge.shots", "status": "warn" if bad else "pass", "detail": detail}]


def kit_checks(job: Job, packet: Fields, am: Fields, sheet: str | None) -> list[Fields]:
    """A stream job proves the lock held: first from the record, then by looking at the frames."""
    from .plan import extract_json

    try:
        locked = consistency.for_job(job)
    except ContractError as exc:
        return [{"id": "consistency.lock", "status": "fail", "detail": str(exc)[:500]}]
    if not locked:
        return []
    resolved, lock = locked
    checks = [{"id": "consistency.lock", "status": "pass", "detail": "kits match the job's lock"}]
    checks += kitchecks.recorded_checks(resolved, lock, packet, am)
    if am.get("kit_lock_sha256") != consistency.lock_sha256(job):
        checks.append(
            {"id": "consistency.manifest", "status": "fail", "detail": "assets predate this lock"}
        )
    unseen = {"id": "consistency.vision", "status": "warn"}
    if not sheet:
        return [*checks, {**unseen, "detail": "no contact sheet; a human compares the frames"}]
    text = prompts.load("qa_consistency").format(
        context=kitchecks.judge_brief(resolved, lock["cast"]),
        script=[b["text"] for b in packet["beats"]],
    )
    images = [*kitchecks.judge_images(resolved, lock["cast"]), job.work / sheet]
    try:
        _, res = router.generate(
            job, "llm", "llm", text, images=images, max_tokens=800, note="qa-consistency"
        )
        return [*checks, *kitchecks.judge_checks(extract_json(res.text))]
    except CostCapExceeded:
        raise
    except LookupError:
        return [*checks, {**unseen, "detail": "no vision model ready; a human compares the frames"}]
    except Exception as exc:  # the human gate still stands, and the warning says so
        return [*checks, {**unseen, "detail": f"vision check failed: {exc}"[:300]}]
