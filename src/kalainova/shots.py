"""One shot, written the way a model reads it.

A still needs a picture described. A clip that starts from that still already has the picture, so
its prompt spends its words on what moves. Prompts that repeat the picture leave no room for motion,
and one reason generated clips freeze is that nothing in the prompt asks them not to.

People, places, and props are written once in a packet's continuity block and reused word for word,
so a coat does not become a jacket between two shots.

review() reads a plan before any money or GPU time is spent on it.
"""

from __future__ import annotations

import re
from typing import Any

from . import config

Packet = dict[str, Any]
Beat = dict[str, Any]
Problem = dict[str, str]

# Words that ask a video model for no motion, whatever else the prompt says.
STILL_WORDS = re.compile(
    r"\b(?:film still|still image|still photo\w*|photograph|frozen in)\b", re.I
)
_MOTION_WORDS = re.compile(
    r"\b(?:\w+ing|moves?|drifts?|rolls?|sweeps?|turns?|walks?|climbs?|rises?|falls?|flows?|pans?|"
    r"tilts?|pushes?|pulls?|tracks?|dolly|sways?|runs?|crashes?|breaks?)\b",
    re.I,
)
ALIKE = 0.7  # cues sharing this much of their words read as the same shot twice
SAME_SIZE_RUN = 3
UNLIMITED = 10**6
DEFAULT_STILL_PROFILE_BUDGET = 3
GROUPS = (("cast", "people"), ("location", "places"), ("props", "props"))


def video_budget(data: dict[str, Any]) -> int:
    """How many shots of a job may move. A moving-picture profile moves every shot unless the brief
    asks for fewer with max_video_beats; an audio-only profile keeps the old limit of 3."""
    asked = (data.get("brief") or {}).get("max_video_beats")
    if asked is not None:
        return int(asked)
    moving = bool(config.profile(data.get("profile") or "short-9x16").get("fps"))
    return UNLIMITED if moving else DEFAULT_STILL_PROFILE_BUDGET


def _names(beat: Beat, field: str) -> list[str]:
    value = beat.get(field)
    if not value:
        return []
    return [str(value)] if isinstance(value, str) else [str(v) for v in value]


def _joined(parts: list[str | None]) -> str:
    kept = [str(p).strip().rstrip(".") for p in parts if p and str(p).strip()]
    return ". ".join(kept) + "." if kept else ""


def continuity_text(packet: Packet, beat: Beat) -> list[str]:
    """The fixed descriptions this beat names, word for word."""
    block = packet.get("continuity") or {}
    out = []
    for field, group in GROUPS:
        table = block.get(group) or {}
        out += [str(table[name]) for name in _names(beat, field) if name in table]
    return out


def still_prompt(packet: Packet, beat: Beat, style: str) -> str:
    """The picture at the start of the shot."""
    shot = beat.get("shot") or {}
    picture = shot.get("first_frame") or beat.get("visual_cue") or beat["text"]
    return _joined([str(picture), *continuity_text(packet, beat), style])


def _fit(text: str, limit: int | None) -> str:
    """Keep to what a model reads, dropping whole sentences from the end where possible."""
    words = text.split()
    if not limit or len(words) <= limit:
        return text
    cut = " ".join(words[:limit])
    stop = cut.rfind(".")
    return cut[: stop + 1] if stop > len(cut) // 2 else cut.rstrip(",;:") + "."


def word_limit(names: list[str]) -> int | None:
    """The tightest limit among the providers this call could reach."""
    table = config.studio().get("prompt_words_max") or {}
    limits = [int(table[name]) for name in names if name in table]
    return min(limits) if limits else None


def _what_moves(beat: Beat, shot: dict[str, Any], end_in_text: bool) -> str:
    motion = [shot.get("camera"), shot.get("action"), shot.get("environment")]
    if not any(motion):
        return _joined([str(beat.get("visual_cue") or beat["text"])])
    text = _joined(motion)
    if end_in_text and shot.get("last_frame"):
        return f"{text} It ends on this: {str(shot['last_frame']).rstrip('.')}."
    return text


def motion_prompt(
    packet: Packet,
    beat: Beat,
    style: str,
    *,
    has_start_image: bool,
    limit: int | None = None,
    with_sound: bool = False,
    end_in_text: bool = False,
) -> str:
    """What moves, first. With no start image, the model also needs the picture, after that.

    A last frame is a picture, so it is sent as one to a model that takes it. Words about it would
    only be a guess, so they are written only when asked for."""
    shot = beat.get("shot") or {}
    text = _what_moves(beat, shot, end_in_text)
    if not has_start_image:
        text = f"{text} {still_prompt(packet, beat, style)}"
    text = re.sub(r"\s{2,}", " ", STILL_WORDS.sub("", text))
    if with_sound and (shot.get("sound") or beat.get("ambience")):
        text = f"{text} The sound is {str(shot.get('sound') or beat['ambience']).rstrip('.')}."
    return _fit(text.strip(), limit)


def _problem(check: str, severity: str, detail: str) -> Problem:
    return {"id": f"plan.{check}", "status": severity, "detail": detail}


def _token_set(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z']+", text.lower()) if len(w) > 3}


def _alike(a: Beat, b: Beat) -> bool:
    left = _token_set(str(a.get("visual_cue") or ""))
    right = _token_set(str(b.get("visual_cue") or ""))
    if not left or not right:
        return False
    return len(left & right) / len(left | right) >= ALIKE


def _names_known(packet: Packet) -> list[Problem]:
    block = packet.get("continuity")
    if not block:
        return []
    out = []
    for beat in packet["beats"]:
        for field, group in GROUPS:
            table = block.get(group) or {}
            for name in _names(beat, field):
                if name not in table:
                    detail = f"{beat['id']} names {name}, which {group} does not describe"
                    out.append(_problem("continuity", "fail", detail))
    return out


def _budget(packet: Packet, budget: int, allow_stills: bool) -> list[Problem]:
    asked = sum(1 for b in packet["beats"] if b.get("visual_kind") == "video")
    if asked <= budget:
        return []
    detail = f"{asked} shots ask to move and the budget is {budget}; raise brief.max_video_beats"
    return [_problem("video_budget", "warn" if allow_stills else "fail", detail)]


def _moving_shot_problems(beat: Beat) -> list[Problem]:
    bid = beat["id"]
    shot = beat.get("shot") or {}
    cue = str(beat.get("visual_cue") or "")
    out = []
    if STILL_WORDS.search(cue):
        out.append(_problem("still_words", "warn", f"{bid} moves, but its cue asks for a still"))
    stated = shot.get("camera") or shot.get("action") or shot.get("environment")
    if not stated and not _MOTION_WORDS.search(cue):
        out.append(_problem("motion_stated", "warn", f"{bid} moves, but nothing says what moves"))
    return out


def _sequence_problems(beats: list[Beat]) -> list[Problem]:
    out = []
    run, last = 0, ""
    for beat in beats:
        size = str((beat.get("shot") or {}).get("size") or "")
        run = run + 1 if size and size == last else 1
        last = size
        if size and run == SAME_SIZE_RUN:
            out.append(_problem("shot_sizes", "warn", f"{SAME_SIZE_RUN} {size} shots in a row"))
    for first, second in zip(beats, beats[1:], strict=False):
        if _alike(first, second):
            detail = f"{first['id']} and {second['id']} describe nearly the same picture"
            out.append(_problem("repetition", "warn", detail))
    return out


def _structure_problems(beats: list[Beat]) -> list[Problem]:
    out = []
    if beats and beats[0].get("continues"):
        out.append(_problem("continues", "fail", f"{beats[0]['id']} has nothing to continue from"))
    for beat in beats:
        if beat.get("on_camera") and not (beat.get("speaker") or beat.get("cast")):
            detail = f"{beat['id']} is said on camera, and names nobody saying it"
            out.append(_problem("on_camera", "fail", detail))
    return out


def _slideshow_risk(beats: list[Beat], wants_video: bool) -> list[Problem]:
    if not wants_video or not beats:
        return []
    still = sum(1 for b in beats if b.get("visual_kind") != "video" and not b.get("graphics"))
    if still * 2 <= len(beats):
        return []
    detail = f"{still} of {len(beats)} shots do not move, which reads as a slideshow"
    return [_problem("slideshow_risk", "warn", detail)]


def _prompt_lengths(packet: Packet, style: str, limit: int | None) -> list[Problem]:
    if not limit:
        return []
    out = []
    for beat in packet["beats"]:
        if beat.get("visual_kind") != "video":
            continue
        words = len(motion_prompt(packet, beat, style, has_start_image=True).split())
        if words > limit:
            detail = f"{beat['id']} has {words} words of motion; a model reads about {limit}"
            out.append(_problem("prompt_length", "warn", detail))
    return out


def review(
    packet: Packet,
    *,
    budget: int,
    allow_stills: bool = False,
    wants_video: bool = True,
    style: str = "",
    limit: int | None = None,
) -> list[Problem]:
    """What is wrong with this plan, before anything is spent. Pure, so it can run anywhere."""
    beats = packet["beats"]
    out = [*_names_known(packet), *_budget(packet, budget, allow_stills)]
    out += _structure_problems(beats)
    out += _sequence_problems(beats)
    out += _slideshow_risk(beats, wants_video)
    out += _prompt_lengths(packet, style, limit)
    for beat in beats:
        if beat.get("visual_kind") == "video":
            out += _moving_shot_problems(beat)
    return out
