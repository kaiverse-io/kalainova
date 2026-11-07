"""Faults in what went into a piece. Found here, they cost nothing to fix."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import media
from .motion import MOTION_WIDTH, shot_motion
from .picture import corner_mark_score
from .readings import Reading, at_least, at_most, limits
from .sound import voice_to_music_db


def moving_share(em: dict[str, Any], am: dict[str, Any]) -> float:
    """Share of the runtime cut from video files, not stills. `shot_motion` reads what moves."""
    kinds = {a["id"]: a["kind"] for a in am["assets"]}
    starts = [float(c.get("start_sec", 0)) for c in em.get("cuts", [])]
    total = float(em.get("duration_sec") or 0)
    ends = [*starts[1:], total]
    moving = sum(
        end - start
        for cut, start, end in zip(em.get("cuts", []), starts, ends, strict=True)
        if kinds.get(cut["source"]) == "video"
    )
    return moving / total if total else 0.0


def _generated_shots(work: Path, em: dict[str, Any], am: dict[str, Any]) -> dict[str, float]:
    """What moves in each generated clip, over the part of it the edit uses."""
    clips = {a["id"]: a for a in am["assets"] if a["kind"] == "video" and a.get("synthetic")}
    read = {}
    for cut in em.get("cuts", []):
        clip = clips.get(cut["source"])
        if not clip:
            continue
        path = work / clip["path"]
        start = float(cut.get("in_sec") or 0.0)
        frames = media.decode_gray(
            path,
            width=MOTION_WIDTH,
            start=start,
            duration=float(cut.get("out_sec") or media.duration(path)) - start,
        )
        motion = shot_motion(frames, media.summarize(path).get("fps", 24.0))
        if motion is not None:
            read[cut["source"]] = motion
    return read


def lossy_sources(am: dict[str, Any]) -> list[str]:
    """Assets that reached the mix through lossy audio, which no master can win back."""
    return [
        a["id"]
        for a in am["assets"]
        if str((a.get("provenance") or {}).get("audio_format", "")).startswith(("mp3", "opus"))
    ]


def _shot_motion_readings(work: Path, em: dict[str, Any], am: dict[str, Any]) -> list[Reading]:
    """A generated clip that barely moves is a defect. In real footage, a quiet shot is a choice."""
    shots = _generated_shots(work, em, am)
    if not shots:
        return []
    least = min(shots, key=lambda s: shots[s])
    limit = float(limits()["shot_motion_min"])
    ok = shots[least] >= limit
    return [Reading("source.shot_motion", f"{shots[least]:.3f} {least}", f">= {limit:g}", ok)]


def source_readings(work: Path, em: dict[str, Any], am: dict[str, Any]) -> list[Reading]:
    """Faults in what went in: found here, they cost nothing to fix."""
    profile = em.get("profile") or {}
    used = {c["source"] for c in em.get("cuts", [])}
    sources = [a for a in am["assets"] if a["id"] in used]
    readings = [at_least("edit.moving_share", moving_share(em, am), "moving_share_min")]
    readings += _shot_motion_readings(work, em, am)
    sizes = [media.summarize(work / a["path"]) for a in sources]
    want = min(profile.get("width", 1), profile.get("height", 1))
    scales = [min(s.get("width", want), s.get("height", want)) / want for s in sizes]
    if scales:
        readings.append(at_least("source.scale", min(scales), "source_scale_min"))
    stills = [a for a in sources if a["kind"] == "still"]
    if len(stills) >= 3:
        grays = [media.gray_frame(work / a["path"], 0.0) for a in stills]
        common = (min(g.shape[0] for g in grays), min(g.shape[1] for g in grays))
        cropped = [g[-common[0] :, -common[1] :] for g in grays]
        readings.append(
            at_most("source.corner_mark", corner_mark_score(cropped), "source_mark_max")
        )
    return readings


def stem_readings(work: Path) -> list[Reading]:
    voice, music = work / "voice.stem.wav", work / "music.stem.wav"
    if not (voice.exists() and music.exists()):
        return []
    left, _, sr = media.decode_stereo(voice)
    bed, _, _ = media.decode_stereo(music)
    gap = voice_to_music_db(left, bed, sr)
    return [
        at_least("audio.voice_to_music_db", gap, "voice_to_music_db_min"),
        at_most("audio.music_audible", gap, "voice_to_music_db_max"),
    ]
