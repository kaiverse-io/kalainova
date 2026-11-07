"""The camera on a still: sub-pixel, steady, and the same speed in every shot.

ffmpeg's zoompan snaps to whole pixels, which reads as a tremble on a slow move. A camera that eases
to a stop on each shot is what makes a sequence read as a slideshow. This one samples every frame at
exact positions, moves at one constant rate, and carries that rate through the cut.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image

Arr = npt.NDArray[Any]

ZOOM_PER_SEC = 0.012  # a push the eye reads as intent, not as a wobble
PAN_PER_SEC = 0.009  # share of the picture width per second
WIDEST_PAN_ZOOM = 1.3  # past this a pan shows softness from the enlargement
HEADROOM = 1.06  # the frame stays this far inside the still, so a pan has room to travel
BATCH_FRAMES = 32


@dataclass(frozen=True)
class Camera:
    zoom: float
    cx: float
    cy: float


def camera(motion: str, t: float, duration: float, *, crop_x: float = 0.5) -> Camera:
    """Where the camera is at t seconds. Zoom moves exponentially, so its speed looks constant."""
    grow = (1 + ZOOM_PER_SEC) ** t
    full = (1 + ZOOM_PER_SEC) ** duration
    if motion == "push_in":
        return _inside(HEADROOM * grow, crop_x, 0.5)
    if motion == "push_out":
        return _inside(HEADROOM * full / grow, crop_x, 0.5)
    if motion == "pan_left":
        zoom, x = _pan(t, duration, crop_x, -1.0)
        return _inside(zoom, x, 0.5)
    if motion == "pan_right":
        zoom, x = _pan(t, duration, crop_x, 1.0)
        return _inside(zoom, x, 0.5)
    if motion == "drift_up":
        zoom, y = _pan(t, duration, 0.5, -1.0)
        return _inside(zoom, crop_x, y)
    return _inside(1.0, crop_x, 0.5)


def _pan(t: float, duration: float, centre: float, sign: float) -> tuple[float, float]:
    """A zoom with room for the whole journey, and the position on it at t.

    Fixed headroom stopped a long shot dead against the edge of the picture, then started it. Only a
    shot long enough to need more than the widest zoom travels more slowly.
    """
    rate = min(PAN_PER_SEC, (1 - 1 / WIDEST_PAN_ZOOM) / max(duration, 1e-3))
    travel = rate * duration
    zoom = max(HEADROOM, 1 / (1 - travel))
    margin = 0.5 / zoom + travel / 2
    middle = min(max(centre, margin), 1 - margin)
    return zoom, middle + sign * (t - duration / 2) * rate


def _inside(zoom: float, cx: float, cy: float) -> Camera:
    half = 0.5 / zoom
    return Camera(zoom, min(max(cx, half), 1 - half), min(max(cy, half), 1 - half))


def _taps(position: Arr, size: int) -> tuple[list[Arr], list[Arr]]:
    """Catmull-Rom sample positions and weights along one axis."""
    base = np.floor(position).astype(np.int64)
    f = (position - base).astype(np.float32)
    weights = [
        -0.5 * f + f**2 - 0.5 * f**3,
        1 - 2.5 * f**2 + 1.5 * f**3,
        0.5 * f + 2 * f**2 - 1.5 * f**3,
        -0.5 * f**2 + 0.5 * f**3,
    ]
    return [np.clip(base + k - 1, 0, size - 1) for k in range(4)], weights


def frame(src: Arr, cam: Camera, width: int, height: int) -> Arr:
    """One output frame, float32 RGB. src must already cover the frame at zoom 1."""
    sh, sw = src.shape[:2]
    scale = cam.zoom * max(width / sw, height / sh)
    xs = sw * cam.cx + (np.arange(width) + 0.5 - width / 2) / scale - 0.5
    ys = sh * cam.cy + (np.arange(height) + 0.5 - height / 2) / scale - 0.5
    ix, wx = _taps(xs, sw)
    iy, wy = _taps(ys, sh)
    left, right = int(ix[0].min()), int(ix[3].max()) + 1
    window = src[:, left:right]
    rows: Arr = np.zeros((height, right - left, 3), np.float32)
    for i, w in zip(iy, wy, strict=True):
        rows += w[:, None, None] * window[i]
    out: Arr = np.zeros((height, width, 3), np.float32)
    for i, w in zip(ix, wx, strict=True):
        out += w[None, :, None] * rows[:, i - left]
    return out


def load_still(path: Path, width: int, height: int, *, room: float) -> Arr:
    """A still as float32 RGB, resampled once so the moving frames never read past its detail."""
    with Image.open(path) as opened:
        rgb = opened.convert("RGB")
    fit = max(width / rgb.width, height / rgb.height) * room
    size = (round(rgb.width * fit), round(rgb.height * fit))
    planes = [
        np.asarray(band.convert("F").resize(size, Image.Resampling.LANCZOS), np.float32)
        for band in rgb.split()
    ]
    return np.stack(planes, axis=-1) / 255.0


def frames_16bit(
    still: Path,
    motion_name: str,
    *,
    width: int,
    height: int,
    fps: float,
    duration: float,
    crop_x: float = 0.5,
) -> Iterator[bytes]:
    """The shot as rgb48 frames, in order, drawn on every core."""
    room = HEADROOM * (1 + ZOOM_PER_SEC) ** duration
    src = load_still(still, width, height, room=room)
    count = max(round(duration * fps), 1)

    def draw(i: int) -> bytes:
        cam = camera(motion_name, i / fps, duration, crop_x=crop_x)
        img = frame(src, cam, width, height)
        return (np.clip(img, 0, 1) * 65535 + 0.5).astype(np.uint16).tobytes()

    with ThreadPoolExecutor(max_workers=os.cpu_count() or 2) as pool:
        for start in range(0, count, BATCH_FRAMES):
            yield from pool.map(draw, range(start, min(start + BATCH_FRAMES, count)))
