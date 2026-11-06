"""COMICS. comic_script.json -> pages, a print PDF, a reader CBZ, and a phone scroll.

Models garble text in images, so they never letter. Each panel's art is generated with no words in
it, and the engine lays out the page, places every balloon where the art is calm, and letters it.
"""

from __future__ import annotations

import json
import math
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from PIL import Image, ImageDraw, ImageFont

from . import assets, captions, consistency, render
from .jobfs import ContractError, Job
from .providers import router

Arr = npt.NDArray[Any]

PAGE_W, PAGE_H = 1988, 3075  # 6.625 x 10.25 inches at 300 dpi, a standard comic trim
MARGIN, GUTTER = 110, 34
SCROLL_W = 800
PX_PER_PT = 300 / 72
LETTER_PT, MIN_LETTER_PT = 10.0, 7.5  # below this a printed comic is hard to read
ART_SHAPES = ((1, 1), (4, 3), (3, 4), (3, 2), (2, 3), (16, 9), (9, 16), (21, 9))
NO_LETTERING = "no text, no letters, no speech bubbles, no captions, no watermark, no logo"
LETTER_FACE, SFX_FACE = "ComicNeue-Bold.ttf", "Bangers-Regular.ttf"
PAPER = (255, 255, 255)
CAPTION_FILL = (250, 244, 222)
INK = (12, 12, 14)
PANEL_RULE = 6
BALLOON_RULE = 5
INSET = 18
OVERSAMPLE = 2
EXPONENT = 2.6  # between an ellipse and a rectangle, which holds lettered text well
TAIL_REACH = 0.7  # past the balloon's edge, as a share of its height
TAIL_SHARE = 0.6  # of the way to a speaker who is close


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class Block:
    lines: list[str]
    size: int
    width: float
    height: float


def panel_rects(
    rows: list[dict[str, Any]], width: int, height: int, *, margin: int, gutter: int
) -> list[Rect]:
    """Panels in reading order, filling the live area exactly."""
    live_h = height - 2 * margin - gutter * (len(rows) - 1)
    total_h = sum(float(r["height"]) for r in rows)
    rects: list[Rect] = []
    y, used = float(margin), 0.0
    for row in rows:
        used += float(row["height"])
        bottom = margin + live_h * used / total_h + gutter * (rows.index(row))
        widths = [float(w) for w in row["widths"]]
        live_w = width - 2 * margin - gutter * (len(widths) - 1)
        x, spent = float(margin), 0.0
        for i, w in enumerate(widths):
            spent += w
            right = margin + live_w * spent / sum(widths) + gutter * i
            rects.append(
                Rect(round(x), round(y), round(right) - round(x), round(bottom) - round(y))
            )
            x = right + gutter
        y = bottom + gutter
    return rects


def art_size(width: int, height: int) -> tuple[int, int]:
    """The nearest shape a model can make that still covers the panel when cropped."""
    target = width / height
    a, b = min(ART_SHAPES, key=lambda s: abs(math.log((s[0] / s[1]) / target)))
    ratio = a / b
    if ratio >= target:
        return math.ceil(height * ratio), height
    return width, math.ceil(width / ratio)


@lru_cache(maxsize=32)
def _font(face: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(captions.FONTS / face), size)


def text_width(line: str, size: int, face: str = LETTER_FACE) -> float:
    return float(_font(face, size).getlength(line))


def _greedy(words: list[str], size: int, width: float) -> list[str]:
    lines = [""]
    for word in words:
        trial = f"{lines[-1]} {word}".strip()
        if lines[-1] and text_width(trial, size) > width:
            lines.append(word)
        else:
            lines[-1] = trial
    return lines


def letter_block(text: str, size: int, *, max_width: float) -> Block:
    """Capitals, wrapped to the narrowest block that keeps the line count, for an even shape."""
    words = text.upper().split()
    width = max(max_width, max(text_width(w, size) for w in words))
    lines = _greedy(words, size, width)
    while width > size:
        narrower = _greedy(words, size, width * 0.96)
        if len(narrower) > len(lines) or any(text_width(x, size) > width for x in narrower):
            break
        lines, width = narrower, width * 0.96
    widest = max(text_width(line, size) for line in lines)
    return Block(lines, size, widest, len(lines) * size * 1.14)


def fit_lettering(text: str, panel: Rect) -> Block:
    """The largest readable lettering that fits. Too many words is the script's fault."""
    pt = LETTER_PT
    while pt >= MIN_LETTER_PT:
        size = round(pt * PX_PER_PT)
        block = letter_block(text, size, max_width=panel.w * 0.66)
        if block.height <= panel.h * 0.5 and block.width <= panel.w * 0.8:
            return block
        pt -= 0.5
    raise ContractError(f"too much text for a {panel.w}x{panel.h} panel: {text[:60]}")


def overlaps(a: Rect, b: Rect) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


def place(art: Arr, panel: Rect, w: int, h: int, *, taken: list[Rect]) -> Rect:
    """Where a balloon covers the least detail. It reads top first, and never lands on another."""
    energy = np.abs(np.diff(art.astype(np.float64), axis=1, prepend=art[:, :1])).astype(np.float64)
    table = energy.cumsum(axis=0).cumsum(axis=1)
    best: tuple[float, Rect] | None = None
    span_x = max(panel.w - w - 2 * INSET, 0)
    span_y = max(panel.h - h - 2 * INSET, 0)
    for fy in np.linspace(0, 1, 7):
        for fx in np.linspace(0, 1, 7):
            spot = Rect(
                panel.x + INSET + round(span_x * fx), panel.y + INSET + round(span_y * fy), w, h
            )
            if any(overlaps(spot, t) for t in taken):
                continue
            score = _busy(table, spot, panel) * (1 + 0.5 * fy)
            if best is None or score < best[0]:
                best = (score, spot)
    if best is None:
        raise ContractError(
            f"too much text: no room left for a balloon in a {panel.w}x{panel.h} panel"
        )
    return best[1]


def _busy(table: Arr, spot: Rect, panel: Rect) -> float:
    x0, y0 = spot.x - panel.x, spot.y - panel.y
    x1, y1 = min(x0 + spot.w, table.shape[1]) - 1, min(y0 + spot.h, table.shape[0]) - 1
    total = float(table[y1, x1])
    if x0 > 0:
        total -= float(table[y1, x0 - 1])
    if y0 > 0:
        total -= float(table[y0 - 1, x1])
    if x0 > 0 and y0 > 0:
        total += float(table[y0 - 1, x0 - 1])
    return float(total / max((x1 - x0 + 1) * (y1 - y0 + 1), 1))


# ------------------------------------------------------------------ drawing
def _superellipse(cx: float, cy: float, a: float, b: float) -> list[tuple[float, float]]:
    points = []
    for i in range(160):
        t = 2 * math.pi * i / 160
        c, s = math.cos(t), math.sin(t)
        points.append(
            (
                cx + a * math.copysign(abs(c) ** (2 / EXPONENT), c),
                cy + b * math.copysign(abs(s) ** (2 / EXPONENT), s),
            )
        )
    return points


def tail_tip(spot: Rect, speaker: tuple[float, float]) -> tuple[float, float] | None:
    """Where a tail ends: toward the speaker and well short, so it never lands on their face."""
    cx, cy = spot.x + spot.w / 2, spot.y + spot.h / 2
    dx, dy = speaker[0] - cx, speaker[1] - cy
    if abs(dx) <= spot.w / 2 and abs(dy) <= spot.h / 2:
        return None
    distance = math.hypot(dx, dy)
    to_edge = distance * min(
        spot.w / 2 / abs(dx) if dx else math.inf, spot.h / 2 / abs(dy) if dy else math.inf
    )
    length = to_edge + min(spot.h * TAIL_REACH, (distance - to_edge) * TAIL_SHARE)
    return cx + dx / distance * length, cy + dy / distance * length


def _balloon_shapes(spot: Rect, tip: tuple[float, float] | None) -> list[list[tuple[float, float]]]:
    cx, cy = spot.x + spot.w / 2, spot.y + spot.h / 2
    shapes = [_superellipse(cx, cy, spot.w / 2, spot.h / 2)]
    if tip:
        angle = math.atan2(tip[1] - cy, tip[0] - cx)
        base = min(spot.w, spot.h) * 0.16
        px, py = -math.sin(angle) * base, math.cos(angle) * base
        shapes.append([(cx + px, cy + py), tip, (cx - px, cy - py)])
    return shapes


def _ink_balloon(page: Image.Image, spot: Rect, tip: tuple[float, float] | None) -> None:
    """Rule first, then the fill on top, so the tail joins the balloon with no line across it."""
    box = Rect(0, 0, page.width, page.height)
    rule = Image.new("L", (box.w * OVERSAMPLE, box.h * OVERSAMPLE), 0)
    fill = Image.new("L", rule.size, 0)
    draw_rule, draw_fill = ImageDraw.Draw(rule), ImageDraw.Draw(fill)
    for shape in _balloon_shapes(spot, tip):
        big = [(x * OVERSAMPLE, y * OVERSAMPLE) for x, y in shape]
        draw_rule.polygon(big, fill=255)
        draw_rule.line([*big, big[0]], fill=255, width=BALLOON_RULE * 2 * OVERSAMPLE, joint="curve")
        draw_fill.polygon(big, fill=255)
    page.paste(INK, (0, 0), rule.resize(page.size, Image.Resampling.LANCZOS))
    page.paste(PAPER, (0, 0), fill.resize(page.size, Image.Resampling.LANCZOS))


def _letter(page: Image.Image, spot: Rect, block: Block) -> None:
    draw = ImageDraw.Draw(page)
    font = _font(LETTER_FACE, block.size)
    step = block.size * 1.14
    y = spot.y + (spot.h - block.height) / 2
    for line in block.lines:
        draw.text((spot.x + spot.w / 2, y + step / 2), line, font=font, fill=INK, anchor="mm")
        y += step


def _ink_caption(page: Image.Image, panel: Rect, block: Block, row: int) -> Rect:
    pad = block.size // 2
    w, h = int(block.width + 2 * pad), int(block.height + pad)
    spot = Rect(panel.x + INSET, panel.y + INSET + row * (h + INSET), w, h)
    ImageDraw.Draw(page).rectangle(
        [spot.x, spot.y, spot.x + w, spot.y + h], fill=CAPTION_FILL, outline=INK, width=3
    )
    _letter(page, spot, block)
    return spot


def _ink_sfx(page: Image.Image, art: Arr, panel: Rect, text: str, taken: list[Rect]) -> Rect:
    size = max(panel.h // 6, 60)
    word = text.upper()
    w, h = int(text_width(word, size, SFX_FACE) * 1.1), int(size * 1.2)
    spot = place(art, panel, min(w, panel.w - 2 * INSET), h, taken=taken)
    layer = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(
        (20, 20),
        word,
        font=_font(SFX_FACE, size),
        fill=(255, 214, 60, 255),
        stroke_width=max(size // 14, 4),
        stroke_fill=(*INK, 255),
    )
    turned = layer.rotate(5, expand=True, resample=Image.Resampling.BICUBIC)
    page.paste(turned, (spot.x, spot.y), turned)
    return spot


def _letter_panel(page: Image.Image, panel: Rect, lines: list[dict[str, Any]]) -> float:
    """Letter one panel. Returns the smallest lettering it used, in points."""
    region = page.crop((panel.x, panel.y, panel.x + panel.w, panel.y + panel.h))
    art = np.asarray(region.convert("L"), np.float64)
    taken: list[Rect] = []
    smallest = LETTER_PT
    captions_drawn = 0
    for line in lines:
        kind = line["kind"]
        if kind == "sfx":
            taken.append(_ink_sfx(page, art, panel, line["text"], taken))
            continue
        block = fit_lettering(line["text"], panel)
        smallest = min(smallest, block.size / PX_PER_PT)
        if kind == "caption":
            taken.append(_ink_caption(page, panel, block, captions_drawn))
            captions_drawn += 1
            continue
        w, h = int(block.width * 1.42), int(block.height * 1.62)
        spot = place(art, panel, w, h, taken=taken)
        at = line.get("speaker_at")
        tip = (
            tail_tip(spot, (panel.x + at[0] * panel.w, panel.y + at[1] * panel.h))
            if at and kind == "speech"
            else None
        )
        _ink_balloon(page, spot, tip)
        _letter(page, spot, block)
        taken.append(spot)
    return smallest


def _cover(src: Path, width: int, height: int) -> Image.Image:
    with Image.open(src) as opened:
        rgb = opened.convert("RGB")
    fit = max(width / rgb.width, height / rgb.height)
    big = rgb.resize((round(rgb.width * fit), round(rgb.height * fit)), Image.Resampling.LANCZOS)
    x, y = (big.width - width) // 2, (big.height - height) // 2
    return big.crop((x, y, x + width, y + height))


# ------------------------------------------------------------------ the job
def _art_prompt(resolved: Any, panel: dict[str, Any], style: str) -> str:
    beat = {"text": panel["art"], "visual_cue": panel["art"], **_shot_fields(panel)}
    cue = consistency.shot_prompt(resolved, beat, style) if resolved else f"{panel['art']}. {style}"
    return f"{cue}. {NO_LETTERING}"


def _shot_fields(panel: dict[str, Any]) -> dict[str, Any]:
    return {k: panel[k] for k in ("cast", "location", "looks", "props") if k in panel}


def _make_art(job: Job, panel: dict[str, Any], rect: Rect, ctx: dict[str, Any]) -> dict[str, Any]:
    """One panel's art, carrying the kit's references when the job has a lock."""
    (job.work / "panels").mkdir(exist_ok=True)
    dst = job.work / "panels" / f"{panel['id']}.png"
    w, h = art_size(rect.w, rect.h)
    beat = {"text": panel["art"], "visual_cue": panel["art"], **_shot_fields(panel)}
    refs = assets._shot_kw(ctx["resolved"], ctx["lock"], "image", beat)
    prompt = _art_prompt(ctx["resolved"], panel, ctx["style"])
    provider, res = router.generate(job, "image", "image", prompt, dst, width=w, height=h, **refs)
    record = {
        "id": panel["id"],
        "kind": "still",
        "role": "visual",
        "beat_id": panel["id"],
        "path": f"panels/{dst.name}",
        "rights": job.job.get("rights", "owned"),
        "provider": provider.name,
        "model": res.model,
        "prompt": prompt,
        "synthetic": True,
    }
    return {k: v for k, v in record.items() if v}


def _page(
    job: Job, spec: dict[str, Any], ctx: dict[str, Any], records: list[dict[str, Any]]
) -> tuple[Image.Image, float]:
    rects = panel_rects(spec["rows"], PAGE_W, PAGE_H, margin=MARGIN, gutter=GUTTER)
    if len(rects) != len(spec["panels"]):
        raise ContractError(
            f"{job.id}: a page lays out {len(rects)} panels and lists {len(spec['panels'])}"
        )
    page = Image.new("RGB", (PAGE_W, PAGE_H), PAPER)
    smallest = LETTER_PT
    for rect, panel in zip(rects, spec["panels"], strict=True):
        record = _make_art(job, panel, rect, ctx)
        records.append(record)
        page.paste(_cover(job.work / record["path"], rect.w, rect.h), (rect.x, rect.y))
        ImageDraw.Draw(page).rectangle(
            [rect.x, rect.y, rect.x + rect.w, rect.y + rect.h], outline=INK, width=PANEL_RULE
        )
        smallest = min(smallest, _letter_panel(page, rect, panel.get("lines") or []))
    ctx.setdefault("rects", []).append(rects)
    return page, smallest


def _scroll(pages: list[Image.Image], rects_by_page: list[list[Rect]]) -> Image.Image:
    """Panels stacked one above the next for a phone, each with its lettering in place."""
    strips = []
    for page, rects in zip(pages, rects_by_page, strict=True):
        for r in rects:
            crop = page.crop((r.x, r.y, r.x + r.w, r.y + r.h))
            strips.append(
                crop.resize((SCROLL_W, round(r.h * SCROLL_W / r.w)), Image.Resampling.LANCZOS)
            )
    gap = 48
    tall = sum(s.height for s in strips) + gap * (len(strips) + 1)
    out = Image.new("RGB", (SCROLL_W, tall), PAPER)
    y = gap
    for s in strips:
        out.paste(s, (0, y))
        y += s.height + gap
    return out


def preflight(job: Job, script: dict[str, Any]) -> None:
    """Refuse a script that cannot be lettered before any art is paid for."""
    for number, spec in enumerate(script["pages"], 1):
        rects = panel_rects(spec["rows"], PAGE_W, PAGE_H, margin=MARGIN, gutter=GUTTER)
        panels = spec["panels"]
        if len(rects) != len(panels):
            raise ContractError(
                f"{job.id}: page {number} lays out {len(rects)} panels and lists {len(panels)}"
            )
        for rect, panel in zip(rects, panels, strict=True):
            for line in panel.get("lines") or []:
                if line["kind"] != "sfx":
                    fit_lettering(line["text"], rect)


def run(job: Job) -> Path:
    script = job.read("comic_script")
    preflight(job, script)
    locked = consistency.for_job(job)
    resolved, lock = locked if locked else (None, {})
    style = script.get("style") or (job.job.get("brief") or {}).get("visual_style") or ""
    ctx: dict[str, Any] = {"resolved": resolved, "lock": lock, "style": style}
    records: list[dict[str, Any]] = []
    built = [_page(job, spec, ctx, records) for spec in script["pages"]]
    pages = [p for p, _ in built]
    folder = job.work / "pages"
    folder.mkdir(exist_ok=True)
    names = []
    for n, page in enumerate(pages, 1):
        names.append(f"{n:03d}.png")
        page.save(folder / names[-1], dpi=(300, 300))
    final = job.work / "final.pdf"
    pages[0].save(final, save_all=True, append_images=pages[1:], resolution=300.0)
    with zipfile.ZipFile(job.work / "final.cbz", "w", zipfile.ZIP_STORED) as cbz:
        for name in names:
            cbz.write(folder / name, name)
    _scroll(pages, ctx["rects"]).save(job.work / "final.scroll.png")
    job.write(
        "asset_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "assets": records,
            **({"kit_lock_sha256": consistency.lock_sha256(job)} if locked else {}),
        },
    )
    render.stamp(job, final)
    smallest = min(s for _, s in built)
    job.set_status("rendered")
    report = {"pages": len(pages), "panels": len(records), "smallest_letter_pt": round(smallest, 1)}
    (job.work / "comic_report.json").write_text(json.dumps(report) + "\n")
    return final


def checks(job: Job) -> list[dict[str, str]]:
    """What can be proved about a lettered comic. A human still reads every page."""
    report = json.loads((job.work / "comic_report.json").read_text())
    smallest = float(report["smallest_letter_pt"])
    return [
        {
            "id": "comic.lettering_size",
            "status": "pass" if smallest >= MIN_LETTER_PT else "fail",
            "detail": f"smallest lettering {smallest:.1f} pt (at least {MIN_LETTER_PT} pt)",
        },
        {
            "id": "comic.pages",
            "status": "pass",
            "detail": f"{report['pages']} pages, {report['panels']} panels",
        },
        {
            "id": "comic.art_lettering",
            "status": "warn",
            "detail": "art is requested with no words; a human checks no model drew any",
        },
    ]
