"""COVER PICKER. The frame a piece is shown by, and a square crop of it.

It looks at frames across the piece, skips the fades at both ends, drops frames that are near
black or flat, and takes the sharpest of what is left. A brief may name a time or a file instead,
and that choice always wins. The square crop is cut around where the picture has the most detail,
because there is no face finder here yet; a person's head sits in the detailed part of a frame far
more often than in a flat one. Cover type is a drawn card, never something a model writes.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from .. import media
from ..bar.picture import BLACK_LEVEL
from ..jobfs import ContractError
from . import release

STEP_SEC = 0.5  # one candidate frame every half second
EDGE_MARGIN_SEC = 0.5  # kept clear of the head and tail beyond any fade
SAMPLE_WIDTH = 320
FLAT_STD = 8.0  # a frame this even carries no picture
FALLBACK_SEC = 0.9  # the old fixed pick, used only when nothing can be measured


def sharpness(gray: np.ndarray) -> float:
    """Variance of the Laplacian. A blurred frame scores low, a crisp one high."""
    g = gray.astype(np.float32)
    lap = g[1:-1, 1:-1] * -4 + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def usable(gray: np.ndarray) -> bool:
    """Not near black and not flat."""
    return float(gray.mean()) >= BLACK_LEVEL and float(gray.std()) >= FLAT_STD


def best_frame(
    frames: np.ndarray, times: list[float], lo: float, hi: float
) -> tuple[float, float] | None:
    """The (time, score) of the sharpest usable frame in [lo, hi], or None if none qualifies."""
    best: tuple[float, float] | None = None
    for t, frame in zip(times, frames, strict=False):
        if not lo <= t <= hi or not usable(frame):
            continue
        score = sharpness(frame)
        if best is None or score > best[1]:
            best = (t, score)
    return best


def square_origin(gray: np.ndarray) -> int:
    """Where a square window starts along the long side so it holds the most detail."""
    h, w = gray.shape
    if h == w:
        return 0
    g = gray.astype(np.float32)
    energy = np.abs(np.diff(g, axis=1, prepend=g[:, :1])) + np.abs(
        np.diff(g, axis=0, prepend=g[:1, :])
    )
    side = min(h, w)
    profile = energy.sum(axis=1 if h > w else 0)
    sums = np.convolve(profile, np.ones(side), mode="valid")
    return int(np.argmax(sums))


def write_square(src: Path, dst: Path) -> None:
    """Cut the largest square from src around its most detailed part."""
    with Image.open(src) as im:
        rgb = im.convert("RGB")
        long_side, side = max(rgb.size), min(rgb.size)
        factor = SAMPLE_WIDTH / rgb.width
        small = rgb.convert("L").resize((SAMPLE_WIDTH, max(round(rgb.height * factor), 1)))
        start = min(round(square_origin(np.asarray(small)) / factor), long_side - side)
        box = (
            (0, start, side, start + side)
            if rgb.height > rgb.width
            else (start, 0, start + side, side)
        )
        rgb.crop(box).save(dst, quality=95)


def _from_file(source: Path, dst: Path) -> list[str]:
    if not source.is_file():
        raise ContractError(f"the cover file {source.name} is not in the job's work folder")
    with Image.open(source) as im:
        im.convert("RGB").save(dst, quality=95)
    return release.cover_warnings(source)


def choose(video: Path, duration: float, edge_sec: float) -> tuple[float, str]:
    """The time to take, and how it was chosen."""
    total = duration or media.duration(video)
    margin = max(edge_sec, 0.0) + EDGE_MARGIN_SEC
    lo, hi = (margin, total - margin) if total > 2 * margin else (0.0, total)
    frames = media.decode_gray(video, width=SAMPLE_WIDTH, fps=1 / STEP_SEC)
    times = [i * STEP_SEC for i in range(len(frames))]
    best = best_frame(frames, times, lo, hi)
    if best is None:
        return min(FALLBACK_SEC, max(total - 0.1, 0.0)), "fallback"
    return best[0], "sharpest"


def write(
    video: Path,
    thumb: Path,
    square: Path | None,
    *,
    duration: float = 0.0,
    edge_sec: float = 0.0,
    at: float | None = None,
    file: Path | None = None,
) -> dict[str, object]:
    """Write the cover and, if asked, its square. Returns what was chosen, for the record."""
    warnings: list[str] = []
    t: float | None = None
    if file is not None:
        warnings = _from_file(file, thumb)
        how = "file"
    else:
        if at is not None:
            t, how = float(at), "brief"
        else:
            t, how = choose(video, duration, edge_sec)
        media.run(["-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1", "-q:v", "2", str(thumb)])
    if square is not None:
        write_square(thumb, square)
    return {"how": how, "at_sec": t, "warnings": warnings}
