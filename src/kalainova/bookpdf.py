"""A book as real type: live text in embedded fonts, at the same places as its page images.

Pillow can only write a page as a picture, which prints soft and cannot be searched, selected, or
read aloud. Text is set here one word at a time, because the breaker has already justified the line.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from fontTools.ttLib import TTFont as SourceFont
from fontTools.varLib import instancer
from PIL import ImageFont, features
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

DPI = 300
POINTS_PER_PIXEL = 72 / DPI
INK = (22 / 255, 22 / 255, 24 / 255)
# Pillow joins "Th" and "fi" when it can, and a PDF set this way cannot. A joined "Th" is narrower
# by most of a word space, so the page, the breaker, and the print all measure separate letters.
SEPARATE_LETTERS = ["-liga", "-clig"] if features.check("raqm") else None
SMALLEST_KERN_PX = 0.05


@dataclass(frozen=True)
class Placed:
    """One run of type on a page, in pixels from the top left, standing on its baseline."""

    text: str
    x: float
    baseline: float
    size: int
    weight: int = 400
    optical: int = 12
    centred: bool = False


@dataclass(frozen=True)
class Book:
    """What a PDF needs that a page of type does not say."""

    title: str
    author: str
    width: int
    height: int
    cover: Path
    face: Path
    folder: Path  # where the fixed cuts of the variable face are kept


@lru_cache(maxsize=64)
def pil_font(face: Path, size: int, weight: int = 400, optical: int = 12) -> ImageFont.FreeTypeFont:
    """The face as Pillow reads it. Loading one is slow, and a book asks thousands of times."""
    font = ImageFont.truetype(str(face), size)
    font.set_variation_by_axes([optical, weight])
    return font


def width(font: ImageFont.FreeTypeFont, text: str) -> float:
    """How wide type sets, the one way every part of a book measures it."""
    return float(font.getlength(text, features=SEPARATE_LETTERS))


def _cut(book: Book, optical: int, weight: int) -> str:
    """A PDF embeds fixed fonts, so each size and weight in use gets a fixed cut of the face."""
    name = f"{book.face.stem}-{optical}-{weight}"
    path = book.folder / f"{name}.ttf"
    if not path.exists():
        book.folder.mkdir(exist_ok=True)
        instancer.instantiateVariableFont(
            SourceFont(book.face), {"opsz": optical, "wght": weight}
        ).save(path)
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(path)))
    return name


@lru_cache(maxsize=4096)
def _kern(font: ImageFont.FreeTypeFont, left: str, right: str) -> float:
    """How far a pair of letters sits from its plain widths, in pixels of this font."""
    return width(font, left + right) - width(font, left) - width(font, right)


def _pieces(item: Placed, face: Path) -> list[tuple[str, float]]:
    """The run cut wherever a pair of letters kerns, with the shift that follows each piece."""
    font = pil_font(face, item.size, item.weight, item.optical)
    pieces: list[tuple[str, float]] = []
    start = 0
    for at in range(1, len(item.text)):
        nudge = _kern(font, item.text[at - 1], item.text[at])
        if abs(nudge) >= SMALLEST_KERN_PX:
            pieces.append((item.text[start:at], nudge))
            start = at
    pieces.append((item.text[start:], 0.0))
    return pieces


def _set(pdf: Any, item: Placed, book: Book) -> None:
    name = _cut(book, item.optical, item.weight)
    points = item.size * POINTS_PER_PIXEL
    x = item.x * POINTS_PER_PIXEL
    y = (book.height - item.baseline) * POINTS_PER_PIXEL
    if item.centred:
        x -= pdfmetrics.stringWidth(item.text, name, points) / 2
    run = pdf.beginText(x, y)
    run.setFont(name, points)
    run.setFillColorRGB(*INK)
    for piece, nudge in _pieces(item, book.face):
        run.setTextOrigin(x, y)
        run.textOut(piece)
        x += pdfmetrics.stringWidth(piece, name, points) + nudge * POINTS_PER_PIXEL
    pdf.drawText(run)


def write(dst: Path, pages: list[list[Placed]], book: Book) -> Path:
    """The cover as a picture, and every other page as type. The same input gives the same bytes."""
    size = (book.width * POINTS_PER_PIXEL, book.height * POINTS_PER_PIXEL)
    # naming a font of ours keeps the default Helvetica, which is never embedded, out of the file
    pdf = canvas.Canvas(str(dst), pagesize=size, invariant=1, initialFontName=_cut(book, 12, 400))
    pdf.setTitle(book.title)
    pdf.setAuthor(book.author)
    pdf.setCreator("Kalainova")
    pdf.drawImage(str(book.cover), 0, 0, width=size[0], height=size[1])
    pdf.showPage()
    for items in pages:
        for item in items:
            _set(pdf, item, book)
        pdf.showPage()
    pdf.save()
    return dst
