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

BLACK_LEVEL = 20.0
DUPLICATE_LEVEL = 0.005
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
MASTER_SIZES = {(1920, 1080), (3840, 2160), (4096, 2160)}


def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


# ------------------------------------------------------------------ picture signals
def duplicate_share(frames: Arr) -> float:
    """Share of picture frames identical to the one before. Black heads and tails do not count."""
    if len(frames) < 2:
        return 0.0
    moved = np.abs(np.diff(frames.astype(np.int16), axis=0)).mean(axis=(1, 2))
    lit = frames[1:].mean(axis=(1, 2)) > BLACK_LEVEL
    return float((moved[lit] < DUPLICATE_LEVEL).mean()) if lit.any() else 0.0


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
    """Spectral energy above half of Nyquist. An upscaled or over-compressed frame has little."""
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


def voice_to_music_db(voice: Arr, music: Arr, sr: int) -> float:
    """How far the music sits under the voice, measured only where someone is speaking."""
    hop = max(sr // 10, 1)
    n = min(voice.size, music.size) // hop
    if n == 0:
        return 0.0
    v = np.sqrt((voice[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    m = np.sqrt((music[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    speaking = v > 10 ** (SPEECH_FLOOR_DB / 20)
    if not speaking.any():
        return 0.0
    return float(np.median(20 * np.log10(v[speaking] / np.maximum(m[speaking], 1e-9))))


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
    """Level of the last 100 ms against the loudest of the last 3 s. Near 0 is a hard stop."""
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
    return config.bar_limits()


def _at_most(rid: str, value: float, key: str, *, blocks: bool = False) -> Reading:
    limit = float(limits()[key])
    return Reading(rid, round(float(value), 4), f"<= {limit:g}", bool(value <= limit), blocks)


def _at_least(rid: str, value: float, key: str, *, blocks: bool = False) -> Reading:
    limit = float(limits()[key])
    return Reading(rid, round(float(value), 4), f">= {limit:g}", bool(value >= limit), blocks)


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


def _check(rid: str, value: Any, limit: str, ok: bool) -> dict[str, Any]:
    return asdict(Reading(rid, value, limit, bool(ok), blocks=True))


def _head_bytes(path: Path, count: int = 1 << 20) -> bytes:
    with path.open("rb") as fh:
        return fh.read(count)


def _master_video(path: Path, target_fps: float) -> list[dict[str, Any]]:
    v = media.stream_info(path, "video")
    head = _head_bytes(path)
    tags = {v.get(k) for k in ("color_primaries", "color_transfer", "color_space")}
    num, _, den = str(v.get("r_frame_rate", "0/1")).partition("/")
    fps = float(num) / float(den or 1)
    size = (v.get("width"), v.get("height"))
    return [
        _check(
            "master.codec",
            f"{v.get('codec_name')} {v.get('profile')}",
            "prores HQ",
            v.get("codec_name") == "prores" and "HQ" in str(v.get("profile")),
        ),
        _check("master.pixels", v.get("pix_fmt"), "yuv422p10le", v.get("pix_fmt") == "yuv422p10le"),
        _check("master.size", f"{size[0]}x{size[1]}", "HD or 4K", size in MASTER_SIZES),
        _check(
            "master.color", "/".join(map(str, sorted(tags, key=str))), "bt709", tags == {"bt709"}
        ),
        _check("master.frame_rate", round(fps, 3), f"{target_fps:g}", abs(fps - target_fps) < 0.01),
        _check("master.atoms", "fiel colr", "present", all(a in head for a in (b"fiel", b"colr"))),
    ]


def _master_picture(path: Path) -> list[dict[str, Any]]:
    frames = media.decode_gray(path, width=480)
    first, last = float(frames[0].mean()), float(frames[-1].mean())
    held = duplicate_share(frames)
    limit = float(limits()["duplicate_share_max"])
    return [
        _check(
            "master.black_head_tail",
            f"{first:.1f}/{last:.1f}",
            f"< {BLACK_LEVEL:g}",
            first < BLACK_LEVEL and last < BLACK_LEVEL,
        ),
        _check("master.duplicate_frames", round(held, 4), f"<= {limit:g}", held <= limit),
    ]


def _master_sound(path: Path) -> list[dict[str, Any]]:
    a = media.stream_info(path, "audio")
    if not a:
        return [_check("master.audio", None, "LPCM stereo", False)]
    loud = media.loudness(path)
    lkfs, peak = loud["integrated_lufs"], loud["true_peak_dbtp"]
    max_lkfs = float(limits()["master_integrated_lkfs_max"])
    max_peak = float(limits()["master_true_peak_dbtp_max"])
    return [
        _check(
            "master.audio",
            f"{a.get('codec_name')} {a.get('sample_rate')} {a.get('channels')}ch",
            "pcm_s24le 48000 2ch",
            a.get("codec_name") == "pcm_s24le"
            and a.get("sample_rate") == "48000"
            and a.get("channels") == 2,
        ),
        _check("master.lkfs", lkfs, f"<= {max_lkfs:g}", lkfs is not None and lkfs <= max_lkfs),
        _check("master.true_peak", peak, f"<= {max_peak:g}", peak is not None and peak <= max_peak),
    ]


def measure_master(path: Path, *, target_fps: float) -> list[dict[str, Any]]:
    """The delivery file against a premium platform's published ingest requirements."""
    return [*_master_video(path, target_fps), *_master_picture(path), *_master_sound(path)]


def _summary(readings: list[dict[str, Any]]) -> dict[str, Any]:
    met = sum(bool(r["ok"]) for r in readings)
    return {
        "passed": met == len(readings),
        "met": met,
        "total": len(readings),
        "readings": readings,
    }


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
    return _summary([asdict(r) for r in readings])


def moving_share(em: dict[str, Any], am: dict[str, Any]) -> float:
    """Share of the runtime on real moving footage. Below this a piece reads as a slideshow."""
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


def _source_readings(work: Path, em: dict[str, Any], am: dict[str, Any]) -> list[Reading]:
    """Faults in what went in: found here, they cost nothing to fix."""
    profile = em.get("profile") or {}
    used = {c["source"] for c in em.get("cuts", [])}
    sources = [a for a in am["assets"] if a["id"] in used]
    readings = [_at_least("edit.moving_share", moving_share(em, am), "moving_share_min")]
    sizes = [media.summarize(work / a["path"]) for a in sources]
    want = min(profile.get("width", 1), profile.get("height", 1))
    scales = [min(s.get("width", want), s.get("height", want)) / want for s in sizes]
    if scales:
        readings.append(_at_least("source.scale", min(scales), "source_scale_min"))
    stills = [a for a in sources if a["kind"] == "still"]
    if len(stills) >= 3:
        grays = [media.gray_frame(work / a["path"], 0.0) for a in stills]
        common = (min(g.shape[0] for g in grays), min(g.shape[1] for g in grays))
        cropped = [g[-common[0] :, -common[1] :] for g in grays]
        readings.append(
            _at_most("source.corner_mark", corner_mark_score(cropped), "source_mark_max")
        )
    return readings


def _stem_readings(work: Path) -> list[Reading]:
    voice, music = work / "voice.stem.wav", work / "music.stem.wav"
    if not (voice.exists() and music.exists()):
        return []
    left, _, sr = media.decode_stereo(voice)
    bed, _, _ = media.decode_stereo(music)
    gap = voice_to_music_db(left, bed, sr)
    return [
        _at_least("audio.voice_to_music_db", gap, "voice_to_music_db_min"),
        _at_most("audio.music_audible", gap, "voice_to_music_db_max"),
    ]


def measure_job(work: Path, em: dict[str, Any], am: dict[str, Any]) -> dict[str, Any]:
    """Everything the bar can read about a rendered job, including what went into it."""
    report = measure(work / "final.mp4")
    readings = list(report["readings"])
    readings += [asdict(r) for r in _source_readings(work, em, am)]
    readings += [asdict(r) for r in _stem_readings(work)]
    master = work / "final.master.mov"
    if master.exists():
        readings += measure_master(master, target_fps=float(em["profile"]["fps"]))
    return _summary(readings)


def as_checks(report: dict[str, Any]) -> list[dict[str, str]]:
    """Readings as QA checks. Only an objective defect blocks. Taste stays with the human."""
    return [
        {
            "id": f"bar.{r['id']}",
            "status": "pass" if r["ok"] else ("fail" if r["blocks"] else "warn"),
            "detail": f"{r['value']} (limit {r['limit']})",
        }
        for r in report["readings"]
    ]
