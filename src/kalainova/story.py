"""STORIES. story.json -> a typeset book as PDF, and a real EPUB with the whole text.

Book typography, by rule: a comfortable measure, justified lines, and no stranded line at the top or
foot of a page. Both files hold live text, so they can be searched and read aloud. Pages are laid
out once, then drawn twice: as images to review, and as type to print.
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

from . import bookpdf, captions, comic, render
from .bookpdf import Placed
from .jobfs import ContractError, Job
from .providers import router

PAGE_W, PAGE_H = 1650, 2550  # 5.5 x 8.5 inches at 300 dpi
MARGIN_X, MARGIN_TOP, MARGIN_FOOT = 215, 240, 270
BODY_SIZE, LEADING = 46, 67  # 11 pt on 16 pt
INDENT = 46
OPENER_DROP = 620  # a chapter starts a third of the way down its page
LONE_WORD_COST = 1.0  # worth a much looser line elsewhere in the paragraph
MIN_LAST_PAGE_LINES = 5  # fewer than this on a chapter's last page looks like a mistake
TITLE_SIZE, TITLE_OPTICAL, FOLIO_SIZE = 92, 48, 38
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


@dataclass(frozen=True)
class ChapterPages:
    title: str
    pages: list[list[Line]]
    lift: int  # how far the opener rose to take up lines that would have been stranded
    first_folio: int


def _font(size: int, *, weight: int = 400, optical: int = 12) -> ImageFont.FreeTypeFont:
    return bookpdf.pil_font(captions.FONTS / BODY_FACE, size, weight, optical)


def break_lines(text: str, *, measure: float, size: int, indent: int) -> list[Line]:
    """Choose every break at once, so the gaps spread across the paragraph instead of pooling.

    Greedy filling looks fine until one long word leaves a line full of holes. This minimises the
    summed squares of the slack, which is the core of how book typesetters set a paragraph.
    """
    font = _font(size)
    words = text.split()
    widths = [bookpdf.width(font, w) for w in words]
    space = bookpdf.width(font, " ")
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
            if end < count:
                cost = (slack / max(room, 1.0)) ** 2
            else:  # the last line is free to run short, but not down to one stranded word
                cost = LONE_WORD_COST if end - start == 1 and start else 0.0
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
            Line(
                chunk,
                bookpdf.width(font, " ".join(chunk)),
                b != len(words),
                indent if n == 0 else 0,
            )
        )
    return lines


def widest_gap_if_greedy(text: str, *, measure: float, size: int) -> float:
    """The worst slack from filling line by line, as a yardstick for the real breaker."""
    font = _font(size)
    worst, current = 0.0, ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and bookpdf.width(font, trial) > measure:
            worst = max(worst, measure - bookpdf.width(font, current))
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


def _strands_a_line(i: int, remaining: int, room: int) -> bool:
    """One line of room left would strand a paragraph's first or last line across the page."""
    if room != 1:
        return False
    return remaining == 2 or (i == 0 and remaining > 1)


def paginate(
    paragraphs: list[list[Line]], lines_per_page: int, first_page: int | None = None
) -> list[list[Line]]:
    """Fill pages, moving a line across when a page would end or start with one stranded line."""
    pages: list[list[Line]] = [[]]
    room = first_page or lines_per_page
    for paragraph in paragraphs:
        for i, line in enumerate(paragraph):
            if room == 0 or _strands_a_line(i, len(paragraph) - i, room):
                pages.append([])
                room = lines_per_page
            pages[-1].append(line)
            room -= 1
    return [page for page in pages if page]


def set_chapter(
    paragraphs: list[list[Line]], lines_per_page: int, opener: int
) -> tuple[list[list[Line]], int]:
    """A chapter's pages, and the lines its opener holds.

    A typesetter's move: when a chapter would end on a page of a few lines, the opener starts a
    little higher and takes them up.
    """
    for room in range(opener, opener + MIN_LAST_PAGE_LINES):
        pages = paginate(paragraphs, lines_per_page, room)
        if len(pages) == 1 or len(pages[-1]) >= MIN_LAST_PAGE_LINES:
            return pages, room
    return paginate(paragraphs, lines_per_page, opener), opener


# ------------------------------------------------------------------ the printed book
def lay_out(chapter: dict[str, Any], first_folio: int) -> ChapterPages:
    """Every line of a chapter on its page. This decides the book; drawing it decides nothing."""
    measure = PAGE_W - 2 * MARGIN_X
    body_height = PAGE_H - MARGIN_TOP - MARGIN_FOOT
    opener = (body_height - OPENER_DROP) // LEADING
    paragraphs = [
        break_lines(text, measure=measure, size=BODY_SIZE, indent=INDENT if n else 0)
        for n, text in enumerate(chapter["paragraphs"])
    ]
    pages, room = set_chapter(paragraphs, body_height // LEADING, opener)
    return ChapterPages(chapter["title"], pages, (room - opener) * LEADING, first_folio)


def _baseline(y: float, size: int, *, optical: int = 12, middle: bool = False) -> float:
    """Where type stands, for a line's top, or for its middle when it is centred on a point."""
    ascent, descent = _font(size, optical=optical).getmetrics()
    return y + ((ascent - descent) / 2 if middle else ascent)


def _set_line(line: Line, y: float, measure: float) -> list[Placed]:
    font = _font(BODY_SIZE)
    x = float(MARGIN_X + line.indent)
    gaps = len(line.words) - 1
    space = bookpdf.width(font, " ")
    if line.justify and gaps:
        space = (measure - line.indent - sum(bookpdf.width(font, w) for w in line.words)) / gaps
    baseline = _baseline(y, BODY_SIZE)
    placed = []
    for word in line.words:
        placed.append(Placed(word, x, baseline, BODY_SIZE))
        x += bookpdf.width(font, word) + space
    return placed


def page_items(chapter: ChapterPages, n: int) -> list[Placed]:
    """All the type on one page of a chapter."""
    measure = PAGE_W - 2 * MARGIN_X
    items = []
    y = float(MARGIN_TOP)
    if n == 0:
        middle = MARGIN_TOP + 240 - chapter.lift / 2
        baseline = _baseline(middle, TITLE_SIZE, optical=TITLE_OPTICAL, middle=True)
        items.append(
            Placed(
                chapter.title, PAGE_W / 2, baseline, TITLE_SIZE, optical=TITLE_OPTICAL, centred=True
            )
        )
        y += OPENER_DROP - chapter.lift
    for line in chapter.pages[n]:
        items += _set_line(line, y, measure)
        y += LEADING
    if n:  # a chapter opener carries no page number, by convention
        baseline = _baseline(PAGE_H - MARGIN_FOOT / 2, FOLIO_SIZE, middle=True)
        folio = str(chapter.first_folio + n)
        items.append(Placed(folio, PAGE_W / 2, baseline, FOLIO_SIZE, centred=True))
    return items


def _page_image(items: list[Placed]) -> Image.Image:
    page = Image.new("RGB", (PAGE_W, PAGE_H), PAPER)
    draw = ImageDraw.Draw(page)
    for item in items:
        font = _font(item.size, weight=item.weight, optical=item.optical)
        anchor = "ms" if item.centred else "ls"
        draw.text(
            (item.x, item.baseline),
            item.text,
            font=font,
            fill=INK,
            anchor=anchor,
            features=bookpdf.SEPARATE_LETTERS,
        )
    return page


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
    pages: list[list[Placed]] = []
    for chapter in script["chapters"]:
        laid = lay_out(chapter, len(pages) + 1)
        pages += [page_items(laid, n) for n in range(len(laid.pages))]
    folder = job.work / "book"
    comic.empty_page_folder(folder)
    cover_page = folder / "001.png"
    cover.save(cover_page, dpi=(bookpdf.DPI, bookpdf.DPI))
    for n, items in enumerate(pages, 2):
        _page_image(items).save(folder / f"{n:03d}.png", dpi=(bookpdf.DPI, bookpdf.DPI))
    final = bookpdf.write(
        job.work / "final.pdf",
        pages,
        bookpdf.Book(
            title=script["title"],
            author=script.get("byline") or "",
            width=PAGE_W,
            height=PAGE_H,
            cover=cover_page,
            face=captions.FONTS / BODY_FACE,
            folder=job.work / "book.fonts",
        ),
    )
    _write_epub(job, script, cover_page)
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
    embedded = b"/FontFile2" in (job.work / "final.pdf").read_bytes()
    return [
        {
            "id": "story.pdf_type",
            "status": "pass" if embedded else "fail",
            "detail": "the book's type is embedded" if embedded else "a printer needs the fonts",
        },
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
