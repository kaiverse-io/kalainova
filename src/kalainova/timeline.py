"""Seeing a piece without watching it end to end: shot sheets, filmstrips, and a check at every cut.

A row of first and last frames shows whether a shot moved, whether its geometry holds, and whether
it matches the shot before, none of which a single frame or a number can show. Faults show up at
cuts, so each one gets its own look: a click in the sound, or a flash in the picture.

The filmstrip with a waveform and word labels follows the idea in video-use (MIT).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import bar, media
from .captions import FONTS

SHEET_LANDSCAPE_WIDTH = 480
SHEET_PORTRAIT_WIDTH = 240
MOST_ROWS = 24
TOO_DARK = 12.0  # a frame this dark is a fade, and says nothing about the shot
MARGIN_SEC = 0.3
LABEL_FONT = "Inter.ttf"
WAVE_HEIGHT = 96
FRAME_WIDTH = 320
BENCH_WIDTH = 200
CLICK_WINDOW_SEC = 0.012
CLICK_CONTEXT_SEC = 0.25
CLICK_RATIO = 12.0  # how far a step at a cut stands above the sound around it to read as a click
FLASH_LEVELS = 40.0  # one frame this far from both neighbours is a flash
SILENCE_DB = -45.0


def _label_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONTS / LABEL_FONT), size)
    except OSError:
        return ImageFont.load_default()


def _frame(path: Path, at: float, width: int) -> Image.Image | None:
    with tempfile.TemporaryDirectory() as tmp:
        dst = Path(tmp) / "f.jpg"
        try:
            media.run(
                ["-ss", f"{max(at, 0.0):.3f}", "-i", str(path), "-frames:v", "1",
                 "-vf", f"scale={width}:-2", "-q:v", "3", str(dst)]
            )  # fmt: skip
            return Image.open(dst).convert("RGB") if dst.exists() else None
        except (media.MediaError, OSError):
            return None


def _lit_frame(path: Path, at: float, step: float, width: int) -> Image.Image | None:
    """A frame near this time that is not lost in a fade. Tries a little further, then gives up."""
    frame = None
    for attempt in range(4):
        found = _frame(path, at + attempt * step, width)
        if found is None:
            continue
        frame = found
        if float(np.asarray(found.convert("L")).mean()) >= TOO_DARK:
            break
    return frame


def _spans(cuts: list[dict[str, Any]], duration: float) -> list[tuple[str, float, float]]:
    starts = [float(c.get("start_sec", 0.0)) for c in cuts]
    ends = [*starts[1:], duration]
    rows = []
    for cut, start, end in zip(cuts, starts, ends, strict=True):
        rows.append((str(cut.get("id", "")).replace("cut-", ""), start, end))
    if len(rows) <= MOST_ROWS:
        return rows
    return [rows[i * len(rows) // MOST_ROWS] for i in range(MOST_ROWS)]


def _sheet_row(
    path: Path, start: float, end: float, width: int
) -> tuple[Image.Image, Image.Image] | None:
    last_step = -0.4
    first = _lit_frame(path, start + MARGIN_SEC, 0.5, width)
    last = _lit_frame(path, max(end - MARGIN_SEC, start), last_step, width)
    return (first, last) if first and last else None


def shot_sheet(path: Path, cuts: list[dict[str, Any]], duration: float, dst: Path) -> Path | None:
    """One row per shot, first frame then last frame, at the piece's real shape."""
    info = media.summarize(path)
    if "width" not in info:
        return None
    portrait = info["height"] > info["width"]
    width = SHEET_PORTRAIT_WIDTH if portrait else SHEET_LANDSCAPE_WIDTH
    spans = _spans(cuts, duration) or [("", 0.0, duration)]
    rows = [(label, _sheet_row(path, a, b, width)) for label, a, b in spans]
    kept = [(label, row) for label, row in rows if row]
    if not kept:
        return None
    height = kept[0][1][0].height
    sheet = Image.new("RGB", (width * 2 + 4, (height + 4) * len(kept)), (0, 0, 0))
    draw = ImageDraw.Draw(sheet)
    font = _label_font(max(width // 16, 12))
    for n, (label, (first, last)) in enumerate(kept):
        y = n * (height + 4)
        sheet.paste(first, (0, y))
        sheet.paste(last, (width + 4, y))
        if label:
            draw.text((8, y + 6), label, fill=(255, 255, 255), font=font, stroke_width=2,
                      stroke_fill=(0, 0, 0))  # fmt: skip
    sheet.save(dst, quality=85)
    return dst


def bench_sheet(rows: list[tuple[str, Path]], dst: Path, *, frames: int = 5) -> Path | None:
    """One row per clip, frames spread across its length, labelled, for comparing models."""
    cells = []
    for label, clip in rows:
        duration = media.duration(clip)
        found = [
            _frame(clip, min(duration * (i + 0.5) / frames, max(duration - 0.05, 0.0)), BENCH_WIDTH)
            for i in range(frames)
        ]
        cells.append((label, found))
    height = next((f.height for _, found in cells for f in found if f), 0)
    if not height:
        return None
    gap = 4
    label_h = 22
    sheet = Image.new(
        "RGB",
        (BENCH_WIDTH * frames + gap * (frames - 1), (height + label_h + gap) * len(cells)),
        (16, 16, 18),
    )
    draw = ImageDraw.Draw(sheet)
    font = _label_font(14)
    for r, (label, found) in enumerate(cells):
        y = r * (height + label_h + gap)
        draw.text((6, y + 3), label, fill=(255, 255, 255), font=font)
        for i, frame in enumerate(found):
            if frame:
                sheet.paste(frame, (i * (BENCH_WIDTH + gap), y + label_h))
    sheet.save(dst, quality=85)
    return dst


def _envelope(mono: np.ndarray, columns: int) -> np.ndarray:
    if not mono.size or columns <= 0:
        return np.zeros(max(columns, 1))
    edges = np.linspace(0, mono.size, columns + 1).astype(int)
    return np.array([
        float(np.abs(mono[a:b]).max()) if b > a else 0.0
        for a, b in zip(edges, edges[1:], strict=False)
    ])  # fmt: skip


def _silences(envelope: np.ndarray) -> np.ndarray:
    quiet: np.ndarray = 20 * np.log10(np.maximum(envelope, 1e-6)) < SILENCE_DB
    return quiet


def filmstrip(
    video: Path,
    start: float,
    end: float,
    dst: Path,
    *,
    frames: int = 8,
    words: list[dict[str, Any]] | None = None,
) -> Path:
    """Frames across a span over its waveform, with silence shaded and the words that fall in it."""
    times = np.linspace(start, end, max(frames, 1), endpoint=frames == 1).tolist()
    shots = [_frame(video, t, FRAME_WIDTH) for t in times]
    kept = [s for s in shots if s]
    frame_height = kept[0].height if kept else 180
    width = FRAME_WIDTH * len(times)
    strip = Image.new("RGB", (width, frame_height + WAVE_HEIGHT + 24), (16, 16, 18))
    for n, shot in enumerate(shots):
        if shot:
            strip.paste(shot, (n * FRAME_WIDTH, 0))
    draw = ImageDraw.Draw(strip)
    _draw_wave(draw, video, start, end, width, frame_height)
    _draw_words(draw, words or [], start, end, width, frame_height + WAVE_HEIGHT + 4)
    strip.save(dst, quality=88)
    return dst


def _draw_wave(
    draw: ImageDraw.ImageDraw, video: Path, start: float, end: float, width: int, top: int
) -> None:
    if "sample_rate_hz" not in media.summarize(video):
        return
    left, right, sr = media.decode_stereo(video)
    mono = (left + right)[int(start * sr) : int(end * sr)] / 2
    envelope = _envelope(mono, width)
    quiet = _silences(envelope)
    middle = top + WAVE_HEIGHT // 2
    for x, level in enumerate(envelope):
        if quiet[x]:
            draw.line([(x, top), (x, top + WAVE_HEIGHT)], fill=(48, 34, 34))
        reach = int(min(float(level), 1.0) * WAVE_HEIGHT / 2)
        draw.line([(x, middle - reach), (x, middle + reach)], fill=(120, 196, 160))


def _draw_words(
    draw: ImageDraw.ImageDraw,
    words: list[dict[str, Any]],
    start: float,
    end: float,
    width: int,
    y: int,
) -> None:
    font = _label_font(14)
    span = max(end - start, 1e-3)
    for word in words:
        at = float(word.get("start_sec", -1))
        if start <= at <= end:
            x = int((at - start) / span * width)
            draw.text((x, y), str(word.get("text", "")), fill=(232, 232, 232), font=font)


def _click_ratio(mono: np.ndarray, sr: int, at: float) -> float:
    """How far the biggest sample-to-sample step at a cut stands above the sound around it."""
    centre = int(at * sr)
    reach = int(CLICK_WINDOW_SEC * sr)
    context = int(CLICK_CONTEXT_SEC * sr)
    near = mono[max(centre - reach, 0) : centre + reach]
    around = mono[max(centre - context, 0) : centre + context]
    if near.size < 2 or around.size < 2:
        return 0.0
    floor = float(np.median(np.abs(np.diff(around))))
    return float(np.abs(np.diff(near)).max() / max(floor, 1e-5))


def _flash(path: Path, at: float, fps: float) -> bool:
    """One frame at a cut far from both neighbours: a glitch a viewer sees and no total shows."""
    step = 1.0 / max(fps, 1.0)
    try:
        levels = [
            float(media.gray_frame(path, max(at + k * step, 0.0), width=64).mean())
            for k in (-1, 0, 1)
        ]
    except (IndexError, media.MediaError):
        return False
    return abs(levels[1] - levels[0]) > FLASH_LEVELS and abs(levels[1] - levels[2]) > FLASH_LEVELS


def cut_report(path: Path, cuts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every cut in a finished file, and what is wrong at each one."""
    times = bar._spread(
        [float(c.get("start_sec", 0.0)) for c in cuts if float(c.get("start_sec", 0.0)) > 0.0],
        MOST_ROWS * 4,
    )
    info = media.summarize(path)
    fps = float(info.get("fps") or 24.0)
    mono, sr = np.zeros(0), 48000
    if "sample_rate_hz" in info:
        left, right, sr = media.decode_stereo(path)
        mono = (left + right) / 2
    report = []
    for at in times:
        ratio = _click_ratio(mono, sr, at)
        flash = "width" in info and _flash(path, at, fps)
        entry = {"at_sec": round(at, 3), "click_ratio": round(ratio, 1), "flash": bool(flash)}
        entry["flagged"] = bool(ratio > CLICK_RATIO or flash)
        report.append(entry)
    return report
