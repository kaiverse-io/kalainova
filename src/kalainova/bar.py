"""The studio bar: what "finished" means, as numbers a tool computes.

Each signal is a pure function over pixels or samples, so it can be proved on synthetic media with a
known answer. `measure` reads a delivered file and compares the signals to the limits in
config/studio.yaml. The bar informs the human gate. It never replaces it.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageFilter

from . import config, media

Arr = npt.NDArray[Any]

STILL_LEVEL = 0.02  # mean grey-level change per frame below which nothing is moving
STUTTER_WINDOW = 9
FLAT_RUN_PX = 12  # a band this wide with a one-level step at each end reads as a contour
DUPLICATE_MIN_CORR = 0.9
CORNER_FRACTION = 0.2
MARK_EDGE_LEVEL = 24.0
MARK_REACH_PX = 2
HARD_CUT_DROP_DB = 28.0
SPEECH_FLOOR_DB = -36.0
SILENCE_EPS = 1.0 / 32768
MAX_MEASURE_FRAMES = 240


def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


# ------------------------------------------------------------------ picture signals
def banding_score(gray: Arr) -> float:
    """Share of the frame inside flat runs bounded by one-level steps. Contours on a gradient."""
    rows = gray.astype(np.int16)
    width = rows.shape[1]
    steps = np.diff(rows, axis=1)
    row_idx, col_idx = np.nonzero(steps)
    if row_idx.size < 2:
        return 0.0
    same_row = row_idx[1:] == row_idx[:-1]
    runs = col_idx[1:] - col_idx[:-1]
    gentle = np.abs(steps[row_idx, col_idx]) == 1
    banded = same_row & (runs >= FLAT_RUN_PX) & gentle[1:] & gentle[:-1]
    return float(runs[banded].sum() / (rows.shape[0] * width))


def stutter_score(diffs: Arr) -> float:
    """Share of frames that barely change while their neighbours do: the signature of judder."""
    if diffs.size < 3 or float(diffs.mean()) <= STILL_LEVEL:
        return 0.0
    window = np.ones(STUTTER_WINDOW) / STUTTER_WINDOW
    local = np.convolve(diffs, window, mode="same")
    moving = local > STILL_LEVEL
    return float((diffs[moving] < 0.3 * local[moving]).mean()) if moving.any() else 0.0


def repetition_share(thumbs: Sequence[Arr]) -> float:
    """Share of shots that look like another shot in the piece."""
    if len(thumbs) < 2:
        return 0.0
    flat = np.array([t.astype(np.float64).ravel() for t in thumbs])
    norm = flat - flat.mean(axis=1, keepdims=True)
    scale = np.linalg.norm(norm, axis=1, keepdims=True)
    scale[scale == 0] = 1.0
    corr = (norm / scale) @ (norm / scale).T
    np.fill_diagonal(corr, -1.0)
    return float((corr.max(axis=1) >= DUPLICATE_MIN_CORR).mean())


def corner_mark_score(frames: Sequence[Arr]) -> float:
    """Edges that stay in a corner across different shots: a watermark or a burned-in logo."""
    if len(frames) < 3:
        return 0.0
    kept: Arr | None = None
    for frame in frames:
        grown = Image.fromarray(_edges(frame)).filter(ImageFilter.MaxFilter(2 * MARK_REACH_PX + 1))
        edges = np.asarray(grown, dtype=np.float32)
        kept = edges if kept is None else np.minimum(kept, edges)
    assert kept is not None
    return max(_corner_shares(kept))


def _edges(frame: Arr) -> Arr:
    g = frame.astype(np.float32)
    gx = np.abs(np.diff(g, axis=1, prepend=g[:, :1]))
    gy = np.abs(np.diff(g, axis=0, prepend=g[:1, :]))
    return np.clip(np.maximum(gx, gy), 0, 255).astype(np.uint8)


def _corner_shares(kept: Arr) -> list[float]:
    h, w = kept.shape
    ch, cw = int(h * CORNER_FRACTION), int(w * CORNER_FRACTION)
    corners = (kept[:ch, :cw], kept[:ch, -cw:], kept[-ch:, :cw], kept[-ch:, -cw:])
    return [float((c > MARK_EDGE_LEVEL).mean()) for c in corners]


def detail_ratio(gray: Arr) -> float:
    """Spectral energy above half of Nyquist. An upscaled or over-compressed frame has very little."""
    g = gray.astype(np.float64)
    g = g - g.mean()
    window = np.outer(np.hanning(g.shape[0]), np.hanning(g.shape[1]))
    power = np.abs(np.fft.rfft2(g * window)) ** 2
    fy = np.fft.fftfreq(g.shape[0])[:, None]
    fx = np.fft.rfftfreq(g.shape[1])[None, :]
    high = np.hypot(fx, fy) > 0.25
    total = float(power.sum())
    return float(power[high].sum() / total) if total > 0 else 0.0


# ------------------------------------------------------------------ sound signals
def _envelope_db(x: Arr, sr: int, hop_ms: float = 5.0) -> Arr:
    hop = max(int(sr * hop_ms / 1000), 1)
    n = x.size // hop
    if n == 0:
        return np.zeros(0)
    rms = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-9))


def hard_cuts_per_min(x: Arr, sr: int) -> float:
    """Sound that stops dead from speech level. Natural speech decays; a chopped edit does not."""
    env = _envelope_db(x, sr)
    if env.size < 8:
        return 0.0
    now, before, after = env[4:-2], env[:-6], env[6:]
    # Still at full level 20 ms earlier, and gone 10 ms later. A decay has already started by then.
    hit = (now > SPEECH_FLOOR_DB) & (now >= before - 6.0) & (after < now - HARD_CUT_DROP_DB)
    events = np.count_nonzero(np.diff(hit.astype(np.int8)) == 1)
    return events / max(x.size / sr / 60, 1e-6)


def clipped_share(x: Arr) -> float:
    """Share of samples in runs of three or more at full scale."""
    hot = np.abs(x) >= 0.9995
    if x.size < 3:
        return 0.0
    run = hot[:-2] & hot[1:-1] & hot[2:]
    return float(run.mean())


def dc_offset(x: Arr) -> float:
    return float(abs(x.mean())) if x.size else 0.0


def stereo_correlation(left: Arr, right: Arr) -> float:
    """1 is identical, 0 unrelated, -1 cancels to nothing on a phone speaker."""
    if left.std() == 0 or right.std() == 0:
        return 1.0
    return float(np.corrcoef(left, right)[0, 1])


def longest_digital_silence(x: Arr, sr: int) -> float:
    """Longest run of true digital zero inside the piece. Real rooms are never silent."""
    quiet = np.concatenate([[False], np.abs(x) < SILENCE_EPS, [False]])
    edges = np.flatnonzero(quiet[1:] != quiet[:-1])
    if edges.size < 2:
        return 0.0
    return float((edges[1::2] - edges[::2]).max() / sr)


def ending_drop_db(x: Arr, sr: int) -> float:
    """Level of the last 100 ms against the loudest of the last three seconds. Near 0 is a hard stop."""
    tail = x[-3 * sr :]
    last = tail[-sr // 10 :]
    if tail.size == 0 or last.size == 0:
        return 0.0
    win = max(sr // 10, 1)
    n = tail.size // win
    peak = float(np.sqrt((tail[: n * win].reshape(n, win) ** 2).mean(axis=1)).max()) if n else 0.0
    return _db(float(np.sqrt((last**2).mean()))) - _db(peak)


def beat_alignment(cuts: Sequence[float], beats: Sequence[float], tolerance: float) -> float:
    """Share of cuts that land on a beat."""
    if not cuts or not beats:
        return 0.0
    grid = np.array(beats)
    return float(np.mean([np.abs(grid - c).min() <= tolerance for c in cuts]))


# ------------------------------------------------------------------ reading a file
@dataclass(frozen=True)
class Reading:
    id: str
    value: float | str | None
    limit: str
    ok: bool
    blocks: bool = False


def limits() -> dict[str, Any]:
    return dict(config.studio().get("bar") or {})


def _at_most(rid: str, value: float, key: str, *, blocks: bool = False) -> Reading:
    limit = float(limits()[key])
    return Reading(rid, round(value, 4), f"<= {limit:g}", value <= limit, blocks)


def _at_least(rid: str, value: float, key: str, *, blocks: bool = False) -> Reading:
    limit = float(limits()[key])
    return Reading(rid, round(value, 4), f">= {limit:g}", value >= limit, blocks)


def _sample_times(duration: float, count: int) -> list[float]:
    margin = min(0.25, duration / 10)
    return [margin + (duration - 2 * margin) * (i + 0.5) / count for i in range(count)]


def _shot_starts(path: Path, duration: float) -> list[float]:
    return [0.0, *[t for t in media.scene_changes(path) if 0.2 < t < duration - 0.2]]


def _shot_middles(path: Path, duration: float) -> list[float]:
    starts = _shot_starts(path, duration)
    ends = [*starts[1:], duration]
    return [(a + b) / 2 for a, b in zip(starts, ends, strict=True)]


def _motion_readings(path: Path, duration: float) -> list[Reading]:
    fps = max(media.summarize(path).get("fps", 30.0), 1.0)
    span = min(duration, MAX_MEASURE_FRAMES / fps)
    start = max((duration - span) / 2, 0.0)
    frames = media.decode_gray(path, width=540, start=start, duration=span)
    if len(frames) < 3:
        return []
    diffs = np.abs(np.diff(frames.astype(np.int16), axis=0)).mean(axis=(1, 2))
    # A cut is not unevenness, so the frames across one are left out and counted on their own.
    jumps = diffs >= np.median(diffs) * 8 + 1.0
    per_min = float(np.count_nonzero(jumps)) / max(span / 60, 1e-6)
    return [
        _at_most("picture.stutter", stutter_score(diffs[~jumps]), "stutter_max"),
        _at_most("edit.cuts_per_min", per_min, "cuts_per_min_max"),
    ]


def _frame_readings(path: Path, duration: float) -> list[Reading]:
    grays = [media.gray_frame(path, t) for t in _sample_times(duration, 6)]
    middles = _shot_middles(path, duration)
    shots = [media.gray_frame(path, t) for t in middles[:24]]
    thumbs = [np.asarray(Image.fromarray(s).resize((48, 27))) for s in shots]
    return [
        _at_most(
            "picture.banding", float(np.mean([banding_score(g) for g in grays])), "banding_max"
        ),
        _at_least(
            "picture.detail", float(np.median([detail_ratio(g) for g in grays])), "detail_min"
        ),
        _at_most("picture.repetition", repetition_share(thumbs), "repetition_max"),
        _at_most("picture.corner_mark", corner_mark_score(shots), "corner_mark_max"),
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
        _at_most("audio.clipping", clipped_share(mono), "clipped_share_max", blocks=True),
        _at_most("audio.dc_offset", dc_offset(mono), "dc_offset_max"),
        _at_least("audio.mono_safe", stereo_correlation(left, right), "stereo_correlation_min"),
        _at_most("audio.hard_cuts_per_min", hard_cuts_per_min(mono, sr), "hard_cuts_per_min_max"),
        _at_most(
            "audio.digital_silence_sec",
            longest_digital_silence(mono[sr // 4 : -sr // 4], sr),
            "digital_silence_sec_max",
        ),
        _at_most("audio.ending_drop_db", ending_drop_db(mono, sr), "ending_drop_db_max"),
    ]


def measure(path: Path) -> dict[str, Any]:
    """Every reading the delivered file alone can give."""
    info = media.summarize(path)
    duration = media.duration(path)
    readings: list[Reading] = []
    if "width" in info:
        readings += _delivery_readings(path)
        readings += _frame_readings(path, duration)
        readings += _motion_readings(path, duration)
    if "sample_rate_hz" in info:
        readings += _sound_readings(path)
    met = sum(r.ok for r in readings)
    return {
        "passed": met == len(readings),
        "met": met,
        "total": len(readings),
        "readings": [asdict(r) for r in readings],
    }
