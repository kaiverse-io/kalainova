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
LONG_WINDOWS = 4  # past one window's length, several short ones spread across the whole piece
MAX_SHOTS_READ = 24
MASTER_SIZES = {(1920, 1080), (3840, 2160), (4096, 2160)}
MOTION_WIDTH = 320
MOTION_STEP_SEC = 0.25  # long enough for a slow swell to show
MOTION_LEVEL = 6.0  # grey levels a pixel has to change; film grain and shimmer stay under this
MOTION_BLOCK = 64  # matched alone, because a zoom moves each part of the frame a different distance
MOTION_BLOCK_MIN_CONTRAST = 4.0  # grey levels; a flat block cannot say where it went
MOTION_BLOCK_MIN_MATCH = 0.15  # below this the block did not travel as one, as water does not
MOTION_MIN_BLOCKS = 6
MOTION_FIT_ROUNDS = 4
MOTION_FIT_TOLERANCE = (
    1.0  # pixels a block can miss the camera's move and still count as following it
)
MOTION_MOST_TRAVEL = 0.25  # of the frame's height in one step
MOTION_EDGE_PX = 2  # the softening reaches this far in from the edge


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


def _peak_offset(line: Arr, at: int) -> float:
    """Where a peak really sits between samples, from a parabola through its neighbours."""
    left, mid, right = line[(at - 1) % len(line)], line[at], line[(at + 1) % len(line)]
    curve = left - 2 * mid + right
    return 0.0 if abs(curve) < 1e-9 else float(np.clip(0.5 * (left - right) / curve, -0.5, 0.5))


def _phase_match(a: Arr, b: Arr) -> tuple[float, float, float]:
    """How far b's picture travelled to reach a, and how clear that match is.

    Windowed, because a block's own edges stay where they are. On a smooth picture that still
    pattern outweighs the picture's move, and the match says nothing moved.
    """
    h, w = a.shape
    window = np.outer(np.hanning(h), np.hanning(w))
    cross = np.fft.rfft2((a - a.mean()) * window) * np.conj(np.fft.rfft2((b - b.mean()) * window))
    peak = np.fft.irfft2(cross / (np.abs(cross) + 1e-6), s=a.shape)
    y, x = (int(i) for i in np.unravel_index(int(np.argmax(peak)), peak.shape))
    dx = (x if x <= w // 2 else x - w) + _peak_offset(peak[y, :], x)
    dy = (y if y <= h // 2 else y - h) + _peak_offset(peak[:, x], y)
    return dx, dy, float(peak[y, x])


def _block_moves(a: Arr, b: Arr) -> Arr:
    """[x, y, dx, dy] from the frame's centre, for each block that clearly travelled as one."""
    h, w = a.shape
    size, rows = MOTION_BLOCK, []
    for top in range(0, h - size + 1, size // 2):
        for left in range(0, w - size + 1, size // 2):
            block = a[top : top + size, left : left + size]
            if block.std() < MOTION_BLOCK_MIN_CONTRAST:
                continue
            dx, dy, match = _phase_match(block, b[top : top + size, left : left + size])
            if match >= MOTION_BLOCK_MIN_MATCH:
                rows.append((left + size / 2 - w / 2, top + size / 2 - h / 2, dx, dy))
    return np.array(rows, dtype=np.float64).reshape(-1, 4)


def _pan_and_zoom(moves: Arr) -> tuple[float, float, float]:
    """The pan and zoom that best explain these block moves, by least squares."""
    x, y, dx, dy = (moves[:, i] - moves[:, i].mean() for i in range(4))
    zoom = float(((x * dx).sum() + (y * dy).sum()) / max((x * x).sum() + (y * y).sum(), 1e-9))
    pan_x = moves[:, 2].mean() - zoom * moves[:, 0].mean()
    pan_y = moves[:, 3].mean() - zoom * moves[:, 1].mean()
    return float(pan_x), float(pan_y), zoom


def _camera_move(a: Arr, b: Arr) -> tuple[float, float, float]:
    """The camera's pan and zoom from b to a. Blocks that move on their own lose their vote."""
    moves = _block_moves(a, b)
    if len(moves) < MOTION_MIN_BLOCKS:
        dx, dy, _ = _phase_match(a, b)
        return dx, dy, 0.0
    # the median first: an object filling part of the frame cannot drag it off the camera, as it
    # can an average
    camera = float(np.median(moves[:, 2])), float(np.median(moves[:, 3])), 0.0
    for _ in range(MOTION_FIT_ROUNDS):
        pan_x, pan_y, zoom = camera
        misses = np.hypot(
            moves[:, 2] - (pan_x + zoom * moves[:, 0]), moves[:, 3] - (pan_y + zoom * moves[:, 1])
        )
        agree = misses < max(MOTION_FIT_TOLERANCE, 2 * float(np.median(misses)))
        if agree.sum() < MOTION_MIN_BLOCKS:
            break
        camera = _pan_and_zoom(moves[agree])
    return camera


def _undo_camera(b: Arr, pan_x: float, pan_y: float, zoom: float) -> Arr:
    h, w = b.shape
    scale = 1.0 / (1.0 + zoom)
    box = (scale, 0, w / 2 - (w / 2 + pan_x) * scale, 0, scale, h / 2 - (h / 2 + pan_y) * scale)
    moved = Image.fromarray(b).transform(
        (w, h), Image.Transform.AFFINE, box, Image.Resampling.BILINEAR
    )
    return np.asarray(moved, dtype=np.float32)


def _softened(frame: Arr) -> Arr:
    """Lining frames up resamples one of them. Softening both stops that reading as a change."""
    picture = Image.fromarray(np.clip(frame, 0, 255).astype(np.uint8))
    return np.asarray(picture.filter(ImageFilter.BoxBlur(1)), dtype=np.float32)


def _changed_share(a: Arr, b: Arr) -> float:
    """Share of the picture that differs between two frames, once the camera is taken out."""
    h, w = a.shape
    pan_x, pan_y, zoom = _camera_move(a, b)
    reach = max(abs(pan_x), abs(pan_y)) + abs(zoom) * w / 2
    if reach > MOTION_MOST_TRAVEL * h:  # a cut or a flash; no camera moves that far in one step
        pan_x, pan_y, zoom, reach = 0.0, 0.0, 0.0, 0.0
    edge = int(np.ceil(reach)) + MOTION_EDGE_PX
    difference = np.abs(_softened(a) - _softened(_undo_camera(b, pan_x, pan_y, zoom)))
    return float((difference[edge : h - edge, edge : w - edge] > MOTION_LEVEL).mean())


def shot_motion(frames: Arr, fps: float) -> float | None:
    """Share of the picture that moves, with the camera's own pan and zoom taken out.

    A frozen picture under a pan, a push-in, or grain reads near zero. Frame differences cannot tell
    those from a moving sea, and neither can knowing the source was a video file. Share of the frame
    is not liveliness: a talking head or a distant rocket can read low. None means too few frames.
    """
    step = max(round(MOTION_STEP_SEC * fps), 1)
    if len(frames) <= step:
        return None
    gray = frames.astype(np.float32)
    return float(
        np.mean(
            [_changed_share(a, b) for a, b in zip(gray[:-step:step], gray[step::step], strict=True)]
        )
    )


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
        _at_most("picture.stutter", worst_stutter, "stutter_max"),
        _at_most(
            "edit.cuts_per_min", jumps_seen / max(seconds_read / 60, 1e-6), "cuts_per_min_max"
        ),
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


def _scan_held_frames(path: Path) -> tuple[float, float, float]:
    """First level, last level, and held share, one frame at a time: a film has to fit in memory."""
    first = last = 0.0
    previous: Arr | None = None
    held = lit = 0
    for frame in media.iter_gray(path, width=480):
        level = float(frame.mean())
        if previous is None:
            first = level
        else:
            moved = float(np.abs(frame.astype(np.int16) - previous.astype(np.int16)).mean())
            if level > BLACK_LEVEL:
                lit += 1
                held += moved < DUPLICATE_LEVEL
        last, previous = level, frame
    return first, last, held / lit if lit else 0.0


def _master_picture(path: Path) -> list[dict[str, Any]]:
    first, last, held = _scan_held_frames(path)
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


def _tally(readings: list[dict[str, Any]]) -> dict[str, int]:
    return {"met": sum(bool(r["ok"]) for r in readings), "total": len(readings)}


def _summary(readings: list[dict[str, Any]]) -> dict[str, Any]:
    """Conformance and craft apart. Conformance is mostly the renderer checking its own work, so a
    single total flatters anything it makes: a flat gradient reads higher than real footage.
    """
    met = sum(bool(r["ok"]) for r in readings)
    return {
        "passed": met == len(readings),
        "met": met,
        "total": len(readings),
        "conformance": _tally([r for r in readings if r["blocks"]]),
        "craft": _tally([r for r in readings if not r["blocks"]]),
        "readings": readings,
    }


def summary_line(report: dict[str, Any]) -> str:
    """How a person should read a report: two numbers that mean different things."""
    conform, craft = report["conformance"], report["craft"]
    return (
        f"conformance {conform['met']}/{conform['total']}, craft {craft['met']}/{craft['total']}. "
        "A clean sheet shows no measured defect, not that the piece is good"
    )


def _cambi_readings(path: Path) -> list[Reading]:
    found = media.cambi(path)
    if found is None:
        return []  # this ffmpeg has no libvmaf, which is fine: picture.banding still reads
    return [_at_most("picture.cambi_peak", found[1], "cambi_peak_max")]


def measure(path: Path) -> dict[str, Any]:
    """Every reading the delivered file alone can give."""
    info = media.summarize(path)
    duration = media.duration(path)
    readings: list[Reading] = []
    if "width" in info:
        readings += _delivery_readings(path)
        readings += _frame_readings(path, duration)
        readings += _motion_readings(path, duration)
        readings += _cambi_readings(path)
    if "sample_rate_hz" in info:
        readings += _sound_readings(path)
    return _summary([asdict(r) for r in readings])


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


def _source_is_lossy(am: dict[str, Any]) -> list[str]:
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


def _source_readings(work: Path, em: dict[str, Any], am: dict[str, Any]) -> list[Reading]:
    """Faults in what went in: found here, they cost nothing to fix."""
    profile = em.get("profile") or {}
    used = {c["source"] for c in em.get("cuts", [])}
    sources = [a for a in am["assets"] if a["id"] in used]
    readings = [_at_least("edit.moving_share", moving_share(em, am), "moving_share_min")]
    readings += _shot_motion_readings(work, em, am)
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
