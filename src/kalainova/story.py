"""STORIES. story.json -> a typeset book as PDF, and a real EPUB with the whole text.

Book typography, by rule: a comfortable measure, justified lines, and no stranded line at the top or
foot of a page. The EPUB holds live text, so it reflows and is read aloud by any reader.
"""

from __future__ import annotations

import datetime as dt
import uuid
import zipfile
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import captions, comic, render
from .jobfs import ContractError, Job
from .providers import router

PAGE_W, PAGE_H = 1650, 2550  # 5.5 x 8.5 inches at 300 dpi
MARGIN_X, MARGIN_TOP, MARGIN_FOOT = 215, 240, 270
BODY_SIZE, LEADING = 46, 67  # 11 pt on 16 pt
INDENT = 46
OPENER_DROP = 620  # a chapter starts a third of the way down its page
BODY_FACE = "Literata.ttf"
FOOT_DARKNESS = 0.82
INK = (22, 22, 24)
PAPER = (255, 255, 255)


@dataclass(frozen=True)
class Line:
    words: list[str]
    width: float
    justify: bool
    indent: int


def _font(size: int, *, weight: int = 400, optical: int = 12) -> ImageFont.FreeTypeFont:
    font = ImageFont.truetype(str(captions.FONTS / BODY_FACE), size)
    font.set_variation_by_axes([optical, weight])
    return font


def break_lines(text: str, *, measure: float, size: int, indent: int) -> list[Line]:
    """Choose every break at once, so the gaps spread across the paragraph instead of pooling.

    Greedy filling looks fine until one long word leaves a line full of holes. This minimises the
    summed squares of the slack, which is the core of how book typesetters set a paragraph.
    """
    font = _font(size)
    words = text.split()
    widths = [font.getlength(w) for w in words]
    space = font.getlength(" ")
    count = len(words)
    best = [float("inf")] * (count + 1)
    came_from = [0] * (count + 1)
    best[0] = 0.0
    for start in range(count):
        room = measure - (indent if start == 0 else 0)
        used = -space
        for end in range(start + 1, count + 1):
            used += widths[end - 1] + space
            if used > room and end > start + 1:
                break
            slack = max(room - used, 0.0)
            cost = 0.0 if end == count else (slack / max(room, 1.0)) ** 2
            if best[start] + cost < best[end]:
                best[end] = best[start] + cost
                came_from[end] = start
    return _lines_from_breaks(words, came_from, font, indent)


def _lines_from_breaks(
    words: list[str], came_from: list[int], font: ImageFont.FreeTypeFont, indent: int
) -> list[Line]:
    stops = []
    at = len(words)
    while at > 0:
        stops.append((came_from[at], at))
        at = came_from[at]
    stops.reverse()
    lines = []
    for n, (a, b) in enumerate(stops):
        chunk = words[a:b]
        lines.append(
            Line(chunk, font.getlength(" ".join(chunk)), b != len(words), indent if n == 0 else 0)
        )
    return lines


def widest_gap_if_greedy(text: str, *, measure: float, size: int) -> float:
    """The worst slack from filling line by line, as a yardstick for the real breaker."""
    font = _font(size)
    worst, current = 0.0, ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and font.getlength(trial) > measure:
            worst = max(worst, measure - font.getlength(current))
            current = word
        else:
            current = trial
    return worst


def darken_foot(page: Image.Image, *, start: float) -> None:
    """Fade the lower part of a page to near black, so type reads with no visible edge."""
    width, height = page.size
    top = int(height * start)
    ramp = Image.linear_gradient("L").resize((width, height - top))
    mask = Image.new("L", page.size, 0)
    mask.paste(ramp.point(lambda v: int(v * FOOT_DARKNESS)), (0, top))
    page.paste((8, 10, 14), (0, 0), mask)


def paginate(
    paragraphs: list[list[Line]], lines_per_page: int, first_page: int | None = None
) -> list[list[Line]]:
    """Fill pages, moving a line across when a page would end or start with one stranded line."""
    pages: list[list[Line]] = [[]]
    room = first_page or lines_per_page
    for paragraph in paragraphs:
        for i, line in enumerate(paragraph):
            remaining = len(paragraph) - i
            orphan = i == 0 and remaining > 1 and room == 1
            widow = remaining == 2 and room == 1
            if room == 0 or orphan or widow:
                pages.append([])
                room = lines_per_page
            pages[-1].append(line)
            room -= 1
    return [page for page in pages if page]


# ------------------------------------------------------------------ the printed book
def _draw_line(draw: ImageDraw.ImageDraw, line: Line, y: float, measure: float) -> None:
    font = _font(BODY_SIZE)
    x = float(MARGIN_X + line.indent)
    gaps = len(line.words) - 1
    natural = sum(font.getlength(w) for w in line.words)
    space = font.getlength(" ")
    if line.justify and gaps:
        space = (measure - line.indent - natural) / gaps
    for word in line.words:
        draw.text((x, y), word, font=font, fill=INK)
        x += font.getlength(word) + space


def _chapter_pages(chapter: dict[str, Any], first_folio: int) -> list[Image.Image]:
    measure = PAGE_W - 2 * MARGIN_X
    body_height = PAGE_H - MARGIN_TOP - MARGIN_FOOT
    per_page = body_height // LEADING
    opener = (body_height - OPENER_DROP) // LEADING
    paragraphs = [
        break_lines(text, measure=measure, size=BODY_SIZE, indent=INDENT if n else 0)
        for n, text in enumerate(chapter["paragraphs"])
    ]
    images = []
    for n, lines in enumerate(paginate(paragraphs, per_page, opener)):
        page = Image.new("RGB", (PAGE_W, PAGE_H), PAPER)
        draw = ImageDraw.Draw(page)
        y = float(MARGIN_TOP)
        if n == 0:
            title = _font(92, weight=400, optical=48)
            draw.text(
                (PAGE_W / 2, MARGIN_TOP + 240), chapter["title"], font=title, fill=INK, anchor="mm"
            )
            y += OPENER_DROP
        for line in lines:
            _draw_line(draw, line, y, measure)
            y += LEADING
        if n:  # a chapter opener carries no page number, by convention
            draw.text(
                (PAGE_W / 2, PAGE_H - MARGIN_FOOT / 2),
                str(first_folio + n),
                font=_font(38),
                fill=INK,
                anchor="mm",
            )
        images.append(page)
    return images


def _cover(job: Job, script: dict[str, Any]) -> tuple[Image.Image, dict[str, Any] | None]:
    page = Image.new("RGB", (PAGE_W, PAGE_H), (14, 16, 20))
    record = None
    if script.get("cover_art"):
        dst = job.work / "cover.art.png"
        prompt = f"{script['cover_art']}. {comic.NO_LETTERING}"
        provider, res = router.generate(job, "image", "image", prompt, dst, width=1024, height=1536)
        page = comic._cover(dst, PAGE_W, PAGE_H)
        record = {
            "id": "cover",
            "kind": "still",
            "role": "visual",
            "path": dst.name,
            "rights": job.job.get("rights", "owned"),
            "provider": provider.name,
            "model": res.model,
            "prompt": prompt,
            "synthetic": True,
        }
    darken_foot(page, start=0.5)
    draw = ImageDraw.Draw(page, "RGBA")
    title = _font(128, weight=500, optical=72)
    words = comic._greedy(script["title"].split(), 40, PAGE_W * 0.42)
    y = PAGE_H * 0.70
    for row in words:
        draw.text((PAGE_W / 2, y), row, font=title, fill=(250, 250, 248, 255), anchor="mm")
        y += 150
    if script.get("byline"):
        draw.text(
            (PAGE_W / 2, PAGE_H * 0.92),
            script["byline"],
            font=_font(50),
            fill=(240, 240, 238, 255),
            anchor="mm",
        )
    return page, record


# ------------------------------------------------------------------ the EPUB
CONTAINER = """<?xml version="1.0" encoding="UTF-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
STYLE = """body { font-family: serif; line-height: 1.45; margin: 5%; }
h1 { font-weight: normal; text-align: center; margin: 3em 0 2em; }
p { margin: 0; text-indent: 1.4em; text-align: justify; }
h1 + p { text-indent: 0; }
"""


def _chapter_xhtml(chapter: dict[str, Any], language: str) -> str:
    body = "\n".join(f"<p>{escape(p, quote=False)}</p>" for p in chapter["paragraphs"])
    title = escape(chapter["title"], quote=False)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="{language}" lang="{language}">'
        f'<head><title>{title}</title><link rel="stylesheet" href="style.css"/></head>'
        f"<body><h1>{title}</h1>\n{body}\n</body></html>\n"
    )


def _opf(script: dict[str, Any], language: str, has_cover: bool, stamp: str, book_id: str) -> str:
    count = len(script["chapters"])
    items = "\n    ".join(
        f'<item id="c{i}" href="chapter-{i}.xhtml" media-type="application/xhtml+xml"/>'
        for i in range(1, count + 1)
    )
    spine = "\n    ".join(f'<itemref idref="c{i}"/>' for i in range(1, count + 1))
    cover = (
        '<item id="cover" href="cover.png" media-type="image/png" properties="cover-image"/>'
        if has_cover
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:uuid:{book_id}</dc:identifier>
    <dc:title>{escape(script["title"], quote=False)}</dc:title>
    <dc:language>{language}</dc:language>
    <dc:creator>{escape(script.get("byline") or "Kalainova", quote=False)}</dc:creator>
    <meta property="dcterms:modified">{stamp}</meta>
  </metadata>
  <manifest>
    <item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
    <item id="style" href="style.css" media-type="text/css"/>
    {cover}
    {items}
  </manifest>
  <spine>
    {spine}
  </spine>
</package>
"""


def _nav(script: dict[str, Any], language: str) -> str:
    links = "".join(
        f'<li><a href="chapter-{i}.xhtml">{escape(c["title"], quote=False)}</a></li>'
        for i, c in enumerate(script["chapters"], 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops" '
        f'xml:lang="{language}" lang="{language}"><head><title>Contents</title></head><body>'
        f'<nav epub:type="toc"><ol>{links}</ol></nav></body></html>\n'
    )


def _write_epub(job: Job, script: dict[str, Any], cover: Path | None) -> Path:
    language = script.get("language") or "en"
    stamp = dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    book_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"kalainova:{job.id}"))
    out = job.work / "final.epub"
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER, compress_type=zipfile.ZIP_DEFLATED)
        z.writestr(
            "OEBPS/content.opf",
            _opf(script, language, cover is not None, stamp, book_id),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        z.writestr("OEBPS/nav.xhtml", _nav(script, language), compress_type=zipfile.ZIP_DEFLATED)
        z.writestr("OEBPS/style.css", STYLE, compress_type=zipfile.ZIP_DEFLATED)
        if cover:
            z.write(cover, "OEBPS/cover.png")
        for i, chapter in enumerate(script["chapters"], 1):
            z.writestr(
                f"OEBPS/chapter-{i}.xhtml",
                _chapter_xhtml(chapter, language),
                compress_type=zipfile.ZIP_DEFLATED,
            )
    return out


def _missing_glyphs(text: str) -> list[str]:
    """Characters the book face cannot set, which would print as empty boxes."""
    font = _font(BODY_SIZE)
    blank = font.getmask("￿").getbbox()
    return sorted(
        {c for c in text if not c.isspace() and font.getmask(c).getbbox() == blank and blank}
    )


# ------------------------------------------------------------------ the job
def run(job: Job) -> Path:
    script = job.read("story")
    text = " ".join(p for c in script["chapters"] for p in c["paragraphs"])
    missing = _missing_glyphs(text)
    if missing:
        raise ContractError(
            f"{job.id}: the book face cannot set {missing[:12]}; choose another face"
        )
    cover, record = _cover(job, script)
    pages = [cover]
    for chapter in script["chapters"]:
        pages += _chapter_pages(chapter, len(pages))
    folder = job.work / "book"
    folder.mkdir(exist_ok=True)
    for n, page in enumerate(pages, 1):
        page.save(folder / f"{n:03d}.png", dpi=(300, 300))
    final = job.work / "final.pdf"
    pages[0].save(final, save_all=True, append_images=pages[1:], resolution=300.0)
    _write_epub(job, script, folder / "001.png")
    job.write(
        "asset_manifest",
        {"schema_version": "0.1", "job_id": job.id, "assets": [record] if record else []},
    )
    render.stamp(job, final)
    job.set_status("rendered")
    return final


def checks(job: Job) -> list[dict[str, str]]:
    epub = job.work / "final.epub"
    with zipfile.ZipFile(epub) as z:
        first = z.infolist()[0]
        valid = first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
    pages = len(list((job.work / "book").glob("*.png")))
    return [
        {
            "id": "story.epub",
            "status": "pass" if valid else "fail",
            "detail": "EPUB container is well formed"
            if valid
            else "mimetype must come first, stored",
        },
        {"id": "story.pages", "status": "pass" if pages else "fail", "detail": f"{pages} pages"},
        {
            "id": "story.prose",
            "status": "warn",
            "detail": "the bar cannot judge prose; a human reads it",
        },
    ]
