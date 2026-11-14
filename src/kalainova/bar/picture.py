"""What pixels alone can say: duplicates, contours, stutter, repetition, a mark in a corner, detail.

Every signal here is a pure function over arrays, so it can be proved on synthetic frames with a
known answer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageFilter

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


def dynamic_range(gray: Arr) -> float:
    """Normalized range between darkest and brightest pixel (0.0 to 1.0)."""
    if gray.size == 0:
        return 0.0
    return float((gray.max() - gray.min()) / 255.0)


def clipping_ratio(gray: Arr) -> float:
    """Share of pixels crushed to 0 or blown out to 255."""
    if gray.size == 0:
        return 0.0
    crushed_or_blown = (gray <= 1) | (gray >= 254)
    return float(np.mean(crushed_or_blown))
