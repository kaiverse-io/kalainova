"""Whether each paid call in a package is ready to buy (ADR 0022).

A package is checked before anyone is asked to sign it off, so a person reads a verdict and its
reasons rather than raw requests. Each finding names its shot or call, what is wrong, and how to fix
it, at one of two levels:

- `block`: the call cannot be bought as it stands. An input is missing or wrong, the model cannot
  make what is asked, the plan cannot be made as written, or the stills it starts from were not
  accepted. A package with a block is not signed off.
- `risk`: the call can be bought, and is likely to need a retake. The prompt is vague, nothing says
  what a good take must show, a face is held past what a model holds, nothing says what moves. The
  person signing off fixes it and builds the package again, or accepts it by name with a reason,
  which the sign-off records.

The checks need no model and cost nothing. What a person accepted, and the retakes that followed,
are both on record, so each check can later be measured against verdicts (ADR 0017).
"""

from __future__ import annotations

from typing import Any

from . import config, preproduction, shotmake, shots
from .jobfs import Job
from .providers import base

MIN_PROMPT_WORDS = 12  # fewer, and a model fills the rest in itself
PICTURES = ("image", "video")
Finding = dict[str, Any]

FIXES = {
    "character_shot_length": "cut it into shorter angles in script_packet.json",
    "motion_stated": "say what moves in its shot's camera, action or environment",
    "performance_words": "keep its cue to framing, action and setting: the engine directs the "
    "performance (perform.sing in prompts/directions.yaml) and the voice moves the mouth",
    "still_words": "write its visual_cue as motion",
    "prompt_length": "cut its words to what the model reads",
    "repetition": "make the two shots differ, or merge them",
    "shot_sizes": "vary the shot sizes",
    "slideshow_risk": "move more shots",
    "video_budget": "raise brief.max_video_beats, or move fewer shots",
}


def _finding(
    check: str, level: str, detail: str, fix: str, *, shot: str = "", call: int = 0
) -> Finding:
    where = shot or (f"call-{call}" if call else "piece")
    return {"id": f"{check}:{where}", "level": level, "check": check, "shot": shot, "call": call,
            "detail": detail, "fix": fix}  # fmt: skip


def _beats(job: Job) -> dict[str, dict[str, Any]]:
    if not job.has("script_packet"):
        return {}
    return {b["id"]: b for b in job.read("script_packet").get("beats") or []}


def _plan(job: Job) -> list[Finding]:
    """The plan's own review (shots.review), as the assets stage runs it before any spend."""
    if not job.has("script_packet"):
        return []
    data, brief = job.job, job.job.get("brief") or {}
    found = shots.review(
        job.read("script_packet"),
        budget=shots.video_budget(data),
        allow_stills=bool(brief.get("allow_stills")),
        wants_video="video" in (data.get("media") or []),
        style=shotmake.style(data),
        limit=shots.word_limit(config.preference("video", data)),
        character_max_sec=shots.character_ceiling(data),
    )
    out = []
    for problem in found:
        check = problem["id"].removeprefix("plan.")
        level = "block" if problem["status"] == "fail" else "risk"
        fix = FIXES.get(check, "fix it in script_packet.json")
        out.append(_finding(check, level, problem["detail"], fix, shot=problem.get("beat", "")))
    return out


def _longest(call: dict[str, Any]) -> float | None:
    try:
        provider = base.get(str(call["provider"]))
    except KeyError:
        return None
    return provider.inputs(call["capability"], call.get("routed") or None).longest_sec


def _sent(call: dict[str, Any], where: dict[str, Any]) -> list[Finding]:
    out = []
    for sent in call.get("requests") or []:
        said = sent.get("schema")
        if isinstance(said, list) and said:
            detail = f"the vendor would refuse: {said[0]}"
            out.append(_finding("vendor_schema", "block", detail, "fix the mapping", **where))
    return out


def _picture(
    asked: dict[str, Any], beat: dict[str, Any] | None, where: dict[str, Any]
) -> list[Finding]:
    """A still or a moving shot: is it said concretely, and does it carry the faces it shows?"""
    out = []
    words = len(str(asked.get("prompt") or "").split())
    if words < MIN_PROMPT_WORDS:
        detail = f"its prompt is {words} words, so the model invents the rest"
        fix = "say who, doing what, where, and how it is framed"
        out.append(_finding("vague_prompt", "risk", detail, fix, **where))
    cast = (beat or {}).get("cast") or []
    if cast and not asked.get("references"):
        detail = f"it shows {', '.join(cast)} and sends no reference picture: the face is invented"
        fix = "freeze the kit's identity pictures and lock the job to it"
        out.append(_finding("no_references", "block", detail, fix, **where))
    return out


def _moving(
    job: Job, call: dict[str, Any], beat: dict[str, Any] | None, where: dict[str, Any]
) -> list[Finding]:
    """A moving shot: where it starts, what success looks like, and whether the model makes it."""
    asked: dict[str, Any] = call.get("asked") or {}
    out: list[Finding] = []
    start: dict[str, Any] = asked["start"] if isinstance(asked.get("start"), dict) else {}
    if not asked.get("start"):
        detail = "it sends no start frame, so the model invents the first picture"
        out.append(_finding("no_start_frame", "risk", detail, "make its still first", **where))
    if beat is not None and not (beat.get("shot") or {}).get("must_show"):
        detail = "nothing says what a good take must show, so no take can be judged against it"
        fix = "set shot.must_show in script_packet.json"
        out.append(_finding("no_success_stated", "risk", detail, fix, **where))
    longest, length = _longest(call), float(asked.get("duration") or 0)
    if longest and length > longest:
        detail = f"it asks for {length:g}s and the model makes at most {longest:g}s"
        out.append(_finding("too_long", "block", detail, "shorten the shot", **where))
    stills = (job.job.get("animatic_reviewed") or {}).get("stills") or {}
    accepted = stills.get(where["shot"])
    if accepted and start.get("sha256") and start["sha256"] != accepted:
        detail = "its start frame is not the still accepted in the animatic"
        fix = "accept the animatic again"
        out.append(_finding("start_frame_changed", "block", detail, fix, **where))
    return out


def _call(job: Job, call: dict[str, Any], beat: dict[str, Any] | None) -> list[Finding]:
    """What is wrong with one paid call's inputs, from what the engine asked for."""
    where = {"shot": str(call.get("shot") or ""), "call": int(call.get("n") or 0)}
    out = _sent(call, where)
    if call["capability"] in PICTURES:
        out += _picture(call.get("asked") or {}, beat, where)
    if call["capability"] == "video":
        out += _moving(job, call, beat, where)
    return out


def review(job: Job, stage: str, calls: list[dict[str, Any]]) -> list[Finding]:
    """Every finding for the paid calls of one stage, worst first."""
    out = _plan(job)
    if stage == "motion" and preproduction.waiting_gate(job) == "animatic":
        detail = "the animatic has no accept, so its stills are not settled"
        fix = "watch the animatic, then accept it"
        out.append(_finding("animatic_not_accepted", "block", detail, fix))
    beats = _beats(job)
    for call in calls:
        out += _call(job, call, beats.get(str(call.get("shot") or "")))
    unique: dict[str, Finding] = {}
    for f in out:
        unique.setdefault(f["id"], f)  # the plan and a call can say the same thing once
    return sorted(unique.values(), key=lambda f: f["level"] != "block")
