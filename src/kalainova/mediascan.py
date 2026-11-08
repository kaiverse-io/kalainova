"""Reading a whole file: where its picture sits, its frames one at a time, and how it bands."""

from __future__ import annotations

import json
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from .media import FFMPEG, decode_gray, duration, filter_path, has_filter, summarize

Arr = npt.NDArray[Any]

FULL_FRAME = (0.0, 0.0, 1.0, 1.0)


BAR_LEVEL = 24  # 8-bit luma: video black is 16, and compression lifts it a little


BAR_MISMATCH = 0.01  # a letterbox is centred, to within this share of the frame


def iter_gray(path: str | Path, *, width: int) -> Iterator[Arr]:
    """Luma frames one at a time, so a long file never has to fit in memory."""
    info = summarize(path)
    height = max(round(width * info["height"] / info["width"]) // 2 * 2, 2)
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(path), "-an",
        "-vf", f"scale={width}:{height}:flags=bicubic,format=gray",
        "-f", "rawvideo", "-",
    ]  # fmt: skip
    size = width * height
    # ffmpeg from our own constant, and an argument list with no shell
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL) as proc:  # noqa: S603
        while True:
            assert proc.stdout is not None
            blob = proc.stdout.read(size)
            if len(blob) < size:
                return
            yield np.frombuffer(blob, np.uint8).reshape(height, width)


def cambi(path: str | Path, *, every: int = 6) -> tuple[float, float] | None:
    """The CAMBI banding index, mean and peak, from every Nth frame. None if ffmpeg lacks it.

    About 5 reads as slightly annoying. It needs no reference, so the file is its own second input.
    """
    if not has_filter("libvmaf"):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        log = Path(tmp) / "cambi.json"
        graph = (
            "[0:v][1:v]libvmaf=feature=name=cambi:log_fmt=json:"
            f"log_path={filter_path(log)}:n_subsample={every}"
        )
        # ffmpeg from our own constant, and an argument list with no shell
        proc = subprocess.run(  # noqa: S603
            [FFMPEG, "-hide_banner", "-nostats", "-loglevel", "error", "-i", str(path),
             "-i", str(path), "-lavfi", graph, "-f", "null", "-"],
            capture_output=True,
            text=True,
        )  # fmt: skip
        if proc.returncode != 0 or not log.exists():
            return None
        pooled = json.loads(log.read_text()).get("pooled_metrics", {})
    found = next((v for k, v in pooled.items() if "cambi" in k.lower()), None)
    return (float(found["mean"]), float(found["max"])) if found else None


def _bar_lengths(line: Arr) -> tuple[int, int]:
    """How far black runs in from each end of a row or column. Bars match; a dark sky does not."""
    lit = np.flatnonzero(line > BAR_LEVEL)
    if not lit.size:
        return 0, 0
    first, last = int(lit[0]), int(line.size - 1 - lit[-1])
    if not (first and last) or abs(first - last) > max(line.size * BAR_MISMATCH, 1):
        return 0, 0
    return first + 1, last + 1  # scaling blurs the edge, so take one more than was measured


def picture_box(path: str | Path, samples: int = 24) -> tuple[float, float, float, float]:
    """The part of a source that ever holds picture, as shares of the frame: x, y, w, h.

    A bar has to stay black across the whole source. In any one frame, black space below a planet
    or a night sky above a horizon looks the same.
    """
    width = min(summarize(path).get("width", 0), 640)
    if not width:
        return FULL_FRAME
    frames = decode_gray(path, width=width, fps=samples / max(duration(path), 0.1))
    if not frames.size:
        return FULL_FRAME
    peak = frames.max(axis=0)
    rows, cols = peak.max(axis=1), peak.max(axis=0)
    top, bottom = _bar_lengths(rows)
    left, right = _bar_lengths(cols)
    return (
        left / cols.size,
        top / rows.size,
        (cols.size - left - right) / cols.size,
        (rows.size - top - bottom) / rows.size,
    )
