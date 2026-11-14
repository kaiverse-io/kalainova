"""The studio bar: what "finished" means, as numbers a tool computes.

Each signal is a pure function over pixels or samples, so it can be proved on synthetic media with a
known answer. `measure` reads a delivered file and compares the signals to the limits in
config/studio.yaml. The bar informs the human gate. It never replaces it.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .. import media, mediascan
from . import motion, readings, sources
from .identity import face_reading
from .master import measure_master
from .motion import MOTION_STEP_SEC, MOTION_WIDTH, shot_motion
from .picture import (
    banding_score,
    clipping_ratio,
    corner_mark_score,
    detail_ratio,
    duplicate_share,
    dynamic_range,
    repetition_share,
    stutter_score,
)
from .readings import Reading, as_checks, at_least, at_most, limits, summarise, summary_line
from .sound import (
    beat_alignment,
    clipped_share,
    dc_offset,
    ending_drop_db,
    hard_cuts_per_min,
    longest_digital_silence,
    stereo_correlation,
    voice_to_music_db,
)
from .sources import moving_share

__all__ = [
    "LONG_WINDOWS",
    "MOTION_STEP_SEC",
    "MOTION_WIDTH",
    "Reading",
    "as_checks",
    "at_least",
    "at_most",
    "banding_score",
    "beat_alignment",
    "clipped_share",
    "corner_mark_score",
    "dc_offset",
    "detail_ratio",
    "duplicate_share",
    "ending_drop_db",
    "hard_cuts_per_min",
    "identity_readings",
    "limits",
    "longest_digital_silence",
    "measure",
    "measure_job",
    "measure_master",
    "motion",
    "moving_share",
    "readings",
    "repetition_share",
    "shot_motion",
    "sources",
    "stereo_correlation",
    "stutter_score",
    "summarise",
    "summary_line",
    "voice_to_music_db",
]

MAX_MEASURE_FRAMES = 240
LONG_WINDOWS = 4  # past one window's length, several short ones spread across the whole piece
MAX_SHOTS_READ = 24


def identity_readings(path: Path, references: list[Path]) -> list[Reading]:
    """Measure the closest reference image against the configured identity limit."""
    reading = face_reading(path, references, float(limits()["face_distance_max"]))
    return [] if reading is None else [reading]


def _sample_times(duration: float, count: int) -> list[float]:
    margin = min(0.25, duration / 10)
    return [margin + (duration - 2 * margin) * (i + 0.5) / count for i in range(count)]


def _shot_starts(path: Path, duration: float) -> list[float]:
    return [0.0, *[t for t in media.scene_changes(path) if 0.2 < t < duration - 0.2]]


def _shot_middles(path: Path, duration: float) -> list[float]:
    starts = _shot_starts(path, duration)
    ends = [*starts[1:], duration]
    return [(a + b) / 2 for a, b in zip(starts, ends, strict=True)]


def _windows(duration: float, fps: float) -> list[tuple[float, float]]:
    """Where to read motion: all of a short piece, and samples across the whole of a long one."""
    whole = MAX_MEASURE_FRAMES / fps
    if duration <= whole:
        return [(0.0, duration)]
    span = whole / LONG_WINDOWS
    gap = (duration - span) / max(LONG_WINDOWS - 1, 1)
    return [(gap * i, span) for i in range(LONG_WINDOWS)]


def _motion_readings(path: Path, duration: float) -> list[Reading]:
    fps = max(media.summarize(path).get("fps", 30.0), 1.0)
    worst_stutter: float | None = None
    jumps_seen, seconds_read = 0, 0.0
    for start, span in _windows(duration, fps):
        frames = media.decode_gray(path, width=540, start=start, duration=span)
        if len(frames) < 3:
            continue
        diffs = np.abs(np.diff(frames.astype(np.int16), axis=0)).mean(axis=(1, 2))
        # A cut is not unevenness, so the frames across one are left out and counted on their own.
        jumps = diffs >= np.median(diffs) * 8 + 1.0
        jumps_seen += int(np.count_nonzero(jumps))
        seconds_read += span
        stutter = stutter_score(diffs[~jumps])
        worst_stutter = stutter if worst_stutter is None else max(worst_stutter, stutter)
    if worst_stutter is None:
        return []
    return [
        at_most("picture.stutter", worst_stutter, "stutter_max"),
        at_most("edit.cuts_per_min", jumps_seen / max(seconds_read / 60, 1e-6), "cuts_per_min_max"),
    ]


def _spread(items: list[float], most: int) -> list[float]:
    """At most this many items, taken evenly across the list rather than from its start."""
    if len(items) <= most:
        return items
    return [items[i * len(items) // most] for i in range(most)]


def _frame_readings(path: Path, duration: float) -> list[Reading]:
    grays = [media.gray_frame(path, t) for t in _sample_times(duration, 6)]
    middles = _spread(_shot_middles(path, duration), MAX_SHOTS_READ)
    shots = [media.gray_frame(path, t) for t in middles]
    thumbs = [np.asarray(Image.fromarray(s).resize((48, 27))) for s in shots]
    return [
        at_most(
            "picture.banding", float(np.mean([banding_score(g) for g in grays])), "banding_max"
        ),
        at_least(
            "picture.detail", float(np.median([detail_ratio(g) for g in grays])), "detail_min"
        ),
        at_most("picture.repetition", repetition_share(thumbs), "repetition_max"),
        at_most("picture.corner_mark", corner_mark_score(shots), "corner_mark_max"),
    ]


def _delivery_readings(path: Path) -> list[Reading]:
    video = media.stream_info(path, "video")
    tags = {video.get(k) for k in ("color_primaries", "color_transfer", "color_space")}
    return [
        Reading(
            "delivery.color_tags",
            "/".join(str(t) for t in sorted(tags, key=str)),
            "bt709",
            tags == {"bt709"},
            blocks=True,
        ),
        Reading(
            "delivery.pixel_format",
            str(video.get("pix_fmt")),
            "yuv420p",
            video.get("pix_fmt") == "yuv420p",
            blocks=True,
        ),
    ]


def _sound_readings(path: Path) -> list[Reading]:
    left, right, sr = media.decode_stereo(path)
    mono = (left + right) / 2
    return [
        at_most("audio.clipping", clipped_share(mono), "clipped_share_max", blocks=True),
        at_most("audio.dc_offset", dc_offset(mono), "dc_offset_max"),
        at_least("audio.mono_safe", stereo_correlation(left, right), "stereo_correlation_min"),
        at_most("audio.hard_cuts_per_min", hard_cuts_per_min(mono, sr), "hard_cuts_per_min_max"),
        at_most(
            "audio.digital_silence_sec",
            longest_digital_silence(mono[sr // 4 : -sr // 4], sr),
            "digital_silence_sec_max",
        ),
        at_most("audio.ending_drop_db", ending_drop_db(mono, sr), "ending_drop_db_max"),
    ]


def _cambi_readings(path: Path) -> list[Reading]:
    found = mediascan.cambi(path)
    if found is None:
        return []  # this ffmpeg has no libvmaf, which is fine: picture.banding still reads
    return [at_most("picture.cambi_peak", found[1], "cambi_peak_max")]


def _still_readings(path: Path) -> list[Reading]:
    img = Image.open(path).convert("L")
    gray = np.asarray(img)
    w, h = img.size
    return [
        at_most("picture.banding", banding_score(gray), "banding_max"),
        at_least("picture.detail", detail_ratio(gray), "detail_min"),
        at_least("picture.dynamic_range", dynamic_range(gray), "picture_dynamic_range_min"),
        at_most("picture.clipping", clipping_ratio(gray), "picture_clipping_max"),
        Reading("picture.dimensions", f"{w}x{h}", ">= 512x512", w >= 512 and h >= 512),
    ]


def measure(path: Path) -> dict[str, Any]:
    """Every reading the delivered file alone can give."""
    if path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        return summarise([asdict(r) for r in _still_readings(path)])
    try:
        duration = media.duration(path)
    except media.MediaError as err:
        try:
            return summarise([asdict(r) for r in _still_readings(path)])
        except Exception:
            raise err from None
    info = media.summarize(path)
    readings: list[Reading] = []
    if "width" in info:
        readings += _delivery_readings(path)
        readings += _frame_readings(path, duration)
        readings += _motion_readings(path, duration)
        readings += _cambi_readings(path)
    if "sample_rate_hz" in info:
        readings += _sound_readings(path)
    return summarise([asdict(r) for r in readings])


def measure_job(work: Path, em: dict[str, Any], am: dict[str, Any]) -> dict[str, Any]:
    """Everything the bar can read about a rendered job, including what went into it."""
    report = measure(work / "final.mp4")
    readings = list(report["readings"])
    readings += [asdict(r) for r in sources.source_readings(work, em, am)]
    readings += [asdict(r) for r in sources.stem_readings(work)]
    master = work / "final.master.mov"
    if master.exists():
        prof = em["profile"]
        readings += measure_master(
            master,
            target_fps=float(prof["fps"]),
            target_lufs=float(prof["target_lufs"]),
            true_peak_dbtp_max=float(prof["true_peak_dbtp_max"]),
        )
    return summarise(readings)
