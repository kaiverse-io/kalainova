"""What moves in a shot, with the camera's own move taken out.

A pan over a still picture is a camera move and nothing else, so it must read as frozen. Blocks are
matched alone because a zoom moves each part of the frame a different distance.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageFilter

Arr = npt.NDArray[Any]

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
