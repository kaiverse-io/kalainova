"""The checks QA runs that each ask one question of a piece, kept apart from the running of them."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import bar, config, consistency, kitchecks, prompts, shots, timeline
from .editor import musiccuts
from .jobfs import ContractError, CostCapExceeded, Job
from .providers import base as providers_base
from .providers import router

Fields = dict[str, Any]

# Files that came from a person or the engine itself, so there is no model licence to read.
NO_LICENCE = {"operator", "kit", "chained", "clip", "track", "local"}


def promise_checks(data: Fields, am: Fields) -> list[Fields]:
    """A shot that asked to move and did not. Only a person can accept that, on the job itself."""
    breaks = am.get("promise_breaks") or []
    if not breaks:
        return []
    forgiven = (data.get("brief") or {}).get("allow_stills")
    named = ", ".join(b["beat_id"] for b in breaks)
    return [
        {
            "id": "delivery.motion_promise",
            "status": "warn" if forgiven else "fail",
            "detail": f"asked to move and did not: {named}",
        }
    ]


def placeholder_checks(am: Fields) -> list[Fields]:
    """Assets a placeholder provider made. They keep a piece from being reviewed."""
    made = sorted(
        {a.get("id", "?") for a in am.get("assets", []) if _is_placeholder(a.get("provider"))}
    )
    if not made:
        return []
    return [
        {
            "id": "delivery.placeholder",
            "status": "warn",
            "detail": f"{len(made)} placeholder assets, not a result: {', '.join(made)}",
        }
    ]


def _is_placeholder(name: object) -> bool:
    try:
        return bool(isinstance(name, str) and providers_base.get(name).placeholder)
    except KeyError:
        return False


def headline(report: Fields) -> str:
    """The line a person or agent reads first. `passed` covers the contract checks only; a piece
    that did not move as promised, or that placeholders made, says so here."""
    state = "PASSED" if report["passed"] else "FAILED"
    checks = {c["id"]: c for c in report["checks"]}
    unmet = []
    promise = checks.get("delivery.motion_promise")
    if promise:
        unmet.append(promise["detail"].replace("asked to move and did not: ", "did not move: "))
    fake = checks.get("delivery.placeholder")
    if fake:
        unmet.append(fake["detail"].split(":")[0])
    if not unmet:
        return f"QA {state}"
    if not report["passed"]:
        return f"QA {state}, and not reviewable: {'; '.join(unmet)}"
    return f"QA: checks ran, not reviewable: {'; '.join(unmet)}"


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
    found = shots.review(
        packet,
        budget=shots.video_budget(data),
        allow_stills=True,
        wants_video="video" in data.get("media", []),
        character_max_sec=shots.character_ceiling(data),
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


def judge_script(packet: Fields, exclude_beats: set[str] | None = None) -> str:
    excluded = exclude_beats or set()
    return str(
        [
            {
                "id": b["id"],
                "line": b["text"],
                "cue": b.get("visual_cue", ""),
                "moves": b.get("visual_kind") == "video",
            }
            for b in packet["beats"]
            if b["id"] not in excluded
        ]
    )


def shape(prof: Fields) -> str:
    width, height = prof.get("width", 1), prof.get("height", 1)
    return "vertical" if height > width else "square" if height == width else "landscape"


MOTION_FAULTS = {"warping": "warping", "flicker": "flicker", "objects_change": "object_changes"}


def shot_problems(shot: Fields) -> list[str]:
    """What a judge's reading of one shot says is wrong, in the words findings.json uses."""
    has_loc = bool(
        shot.get("region")
        or shot.get("time") is not None
        or shot.get("timestamp") is not None
        or shot.get("at_sec") is not None
    )
    found = [name for key, name in MOTION_FAULTS.items() if shot.get(key) is True]
    if shot.get("moved") is False or shot.get("action_happened") is False:
        found.append("action_missing")
    if shot.get("geometry_ok") is False:
        found.append("geometry")
    if shot.get("matches_previous") is False:
        found.append("mismatch")
    if found and not has_loc:
        return []
    return found


def findings_from_judge(job_id: str, judge: Fields) -> Fields | None:
    """The judge's per-shot faults as a file a retake can read, or None when it found none."""
    shots_found = [
        {
            "id": str(s.get("id")),
            "problems": problems,
            "note": str(s.get("note") or "see the motion strip"),
            **(
                {"suggested_prompt_change": str(s["retake_prompt"])}
                if s.get("retake_prompt")
                else {}
            ),
        }
        for s in judge.get("shots") or []
        if (problems := shot_problems(s))
    ]
    if not shots_found:
        return None
    return {"schema_version": "0.1", "job_id": job_id, "source": "judge", "shots": shots_found}


def judged_shots(judge: Fields) -> list[Fields]:
    shots = judge.get("shots") or []
    if not shots:
        return []
    checks: list[Fields] = []
    bad = []
    unsure_shots = []
    for s in shots:
        probs = shot_problems(s)
        if probs:
            bad.append(f"{s.get('id')}: {s.get('note') or 'see the sheet'}")
        elif s.get("status") == "unsure":
            unsure_shots.append(s.get("id"))
    detail = "; ".join(bad)[:600] or "every shot read as it should"
    checks.append({"id": "judge.shots", "status": "warn" if bad else "pass", "detail": detail})
    if unsure_shots:
        checks.append(
            {
                "id": "judge.unsure",
                "status": "unsure",
                "detail": f"unsure on shots: {', '.join(str(i) for i in unsure_shots)}",
            }
        )
    return checks


def _caption_anchors(path: Path) -> list[float]:
    """Where burned caption text is anchored, as fractions of the frame height."""
    import re

    text = path.read_text()
    res = re.search(r"PlayResY:\s*(\d+)", text)
    if not res:
        return []
    height = float(res.group(1))
    return [
        float(m.group(1)) / height for m in re.finditer(r"Dialogue:[^\n]*?\\pos\(\d+,(\d+)\)", text)
    ]


def _drawn_caption_check(path: Path, zone: Fields) -> list[Fields]:
    """Drawn caption boxes against the band and the right margin they were laid out for."""
    if not path.exists():
        return []
    boxes = json.loads(path.read_text()).get("boxes") or []
    low, high = zone["caption_y"]
    floor = float(zone.get("caption_floor", high))
    edge = 1 - float(zone["right_margin"])
    off = [
        b
        for b in boxes
        if b["top"] < low - 0.005 or b["bottom"] > floor + 0.005 or b["right"] > edge + 0.005
    ]
    detail = (
        f"{len(off)} of {len(boxes)} drawn caption cards leave the band {low}-{high}"
        f" or the right margin, where interface overlays cover them"
        if off
        else "drawn captions sit in the band and margin the interface overlays leave clear"
    )
    return [{"id": "safe_zone.drawn", "status": "warn" if off else "pass", "detail": detail}]


def safe_zone_checks(job: Job, profile: str) -> list[Fields]:
    """Burned text, and a face where a detector has recorded one, against the interface overlays a
    short vertical player puts over the frame. Warns only."""
    zone = config.safe_zone(profile)
    if not zone:
        return []
    out = []
    caps = job.work / "captions.ass"
    low, high = zone["caption_y"]
    floor = float(zone.get("caption_floor", high))
    anchors = _caption_anchors(caps) if caps.exists() else []
    off = sorted({round(y, 2) for y in anchors if not low - 0.005 <= y <= high + 0.005})
    if anchors:
        detail = (
            f"burned text is anchored at {off} of the frame height; keep it between"
            f" {low} and {high} and never below {floor}, where interface overlays cover it"
            if off
            else "burned text sits in the band the interface overlays leave clear"
        )
        out.append(
            {"id": "safe_zone.captions", "status": "warn" if off else "pass", "detail": detail}
        )
    out.extend(_drawn_caption_check(job.work / "captions.drawn.json", zone))
    faces = job.work / "face_centres.json"
    if faces.exists():
        centres = json.loads(faces.read_text())
        lo, hi = zone["face_y"]
        bad = [c for c in centres if not lo <= float(c["y"]) <= hi]
        detail = (
            f"a face centre is outside {lo}-{hi} of the frame height"
            f" in {len(bad)} of {len(centres)} readings"
            if bad
            else "faces sit where interface overlays leave them clear"
        )
        out.append({"id": "safe_zone.faces", "status": "warn" if bad else "pass", "detail": detail})
    return out


def cuts_on_beat_checks(job: Job, em: Fields) -> list[Fields]:
    """A video cut to a track: how many of its cuts landed on a beat of that track. Warns only."""
    path = job.work / "music_cuts.json"
    if not path.exists():
        return []
    beats = json.loads(path.read_text())["beats"]
    cuts = [float(c.get("start_sec", 0)) for c in em.get("cuts", [])][1:]
    if not cuts:
        return []
    rows = musiccuts.cut_offsets(cuts, beats)
    share = musiccuts.share_on_beat(cuts, beats)
    worst = max(r["off_sec"] for r in rows)
    return [
        {
            "id": "edit.cuts_on_beat",
            "status": "pass" if share >= 0.9 else "warn",
            "detail": f"{share:.2f} of {len(cuts)} cuts are on a beat;"
            f" the furthest is {worst:.2f}s off",
        }
    ]


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
