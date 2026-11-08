"""Stories: a typeset book and a real EPUB, from the same text."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
import zipfile

import pypdf
import pytest
from PIL import Image
from reportlab.pdfbase import pdfmetrics

from kalainova import bookpdf, publish, qa, story
from kalainova.jobfs import ContractError, Job


def test_a_paragraph_breaks_into_lines_that_fit_and_lose_no_words():
    text = "The porter walked the platform again that night, as he had every night before it. " * 4
    lines = story.break_lines(text, measure=900, size=46, indent=46)
    assert " ".join(" ".join(line.words) for line in lines).split() == text.split()
    assert all(line.width <= 900 for line in lines)
    assert not lines[-1].justify and lines[0].justify


def test_lines_are_broken_for_the_whole_paragraph_not_one_line_at_a_time():
    text = (
        "train, bolted a grey box to the wall of the ticket room, shaken his hand, and told him he "
        "could go home whenever he liked. That had been a Tuesday. On the Wednesday, at a "
        "quarter to six, he walked the platform anyway, and the extraordinary quiet of the station "
        "met him."
    )
    measure = 900
    lines = story.break_lines(text, measure=measure, size=46, indent=0)
    worst = max(measure - line.width for line in lines if line.justify)
    greedy_worst = story.widest_gap_if_greedy(text, measure=measure, size=46)
    assert worst <= greedy_worst


def test_the_cover_title_sits_on_a_gradient_with_no_hard_edge():
    from PIL import Image as PILImage

    page = PILImage.new("RGB", (100, 400), (120, 130, 140))
    story.darken_foot(page, start=0.5)
    column = [page.getpixel((50, y))[0] for y in range(400)]
    steps = [abs(a - b) for a, b in zip(column, column[1:], strict=False)]
    assert max(steps) <= 3
    assert column[399] < column[100]


def test_a_page_never_ends_or_starts_on_a_stranded_line():
    paragraph = [story.Line(["word"], 100, True, 0)] * 5
    paragraph[-1] = story.Line(["end"], 40, False, 0)
    pages = story.paginate([paragraph, paragraph, paragraph], lines_per_page=7)
    for page in pages:
        assert page, "no page is empty"
    flat = [line for page in pages for line in page]
    assert sum(1 for x in flat if x is not None and x.words) == 15
    # the line after a page break is never the last line of its paragraph
    assert all(page[0].justify or page[0].words != ["end"] for page in pages[1:])


def _job(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    for key in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY"):
        monkeypatch.delenv(key, raising=False)
    folder = tmp_path / "jobs" / "book"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "book",
                "strategy": "text-pack",
                "media": ["story"],
                "rights": "owned",
                "distribution_identity": "test",
                "status": "draft",
                "cost_cap": 0,
                "brief": {"subject": "test"},
            }
        )
    )
    body = "He kept the light for forty years & nobody asked him why. " * 30
    (folder / "story.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "book",
                "title": "A Test Tale",
                "byline": "Test Author",
                "language": "en",
                "cover_art": "a calm sea",
                "chapters": [
                    {"title": "One", "paragraphs": [body, body]},
                    {"title": "Two", "paragraphs": [body]},
                ],
            }
        )
    )
    return Job(folder)


def test_a_paragraph_does_not_end_on_one_short_word():
    text = (
        "The box hummed when he reached the top. It always hummed. It had a green light on its "
        "face that had never once been any other colour, and in the early years he had looked at "
        "it the way you look at a younger man who has been given your job. These days he only "
        "nodded to it, the way you nod to a neighbour you have nothing to say to."
    )
    lines = story.break_lines(text, measure=1220, size=story.BODY_SIZE, indent=story.INDENT)
    assert len(lines[-1].words) >= 2


def _lines(n):
    return [[story.Line(["word"], 100, True, 0)] * n]


@pytest.mark.parametrize("spill", [1, 2, 3, 4])
def test_a_chapter_opener_takes_up_a_few_stranded_lines(spill):
    pages, room = story.set_chapter(_lines(10 + spill), lines_per_page=20, opener=10)
    assert [len(p) for p in pages] == [10 + spill]
    assert room == 10 + spill


def test_a_chapter_opener_keeps_its_place_when_the_last_page_is_already_full_enough():
    pages, room = story.set_chapter(_lines(10 + story.MIN_LAST_PAGE_LINES), 20, 10)
    assert [len(p) for p in pages] == [10, story.MIN_LAST_PAGE_LINES]
    assert room == 10


def test_a_long_chapter_never_ends_on_a_page_of_a_few_lines():
    for total in range(10, 80):
        pages, _ = story.set_chapter(_lines(total), 20, 10)
        assert sum(len(p) for p in pages) == total
        assert len(pages) == 1 or len(pages[-1]) >= story.MIN_LAST_PAGE_LINES


def test_a_second_render_leaves_no_page_from_a_longer_first_one(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    story.run(job)
    (job.work / "book" / "099.png").write_bytes(b"from an earlier, longer layout")
    story.run(job)
    assert not (job.work / "book" / "099.png").exists()


def test_the_story_command_renders_and_reports_qa(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from kalainova import __main__ as cli

    job = _job(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "open_job", lambda name: job)
    assert cli._document(SimpleNamespace(job="s", cmd="story")) in (0, 2)
    out = capsys.readouterr().out
    assert "QA" in out and "final.pdf" in out
    assert (job.work / "final.epub").exists()


def test_a_story_delivers_a_valid_epub_with_the_whole_text(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    story.run(job)
    with zipfile.ZipFile(job.work / "final.epub") as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype" and first.compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype") == b"application/epub+zip"
        ET.fromstring(z.read("META-INF/container.xml"))
        ET.fromstring(z.read("OEBPS/content.opf"))
        ET.fromstring(z.read("OEBPS/nav.xhtml"))
        chapter = z.read("OEBPS/chapter-1.xhtml").decode()
        ET.fromstring(chapter)
        assert "forty years &amp; nobody" in chapter
        assert "chapter-2.xhtml" in z.read("OEBPS/content.opf").decode()


def test_a_story_delivers_a_print_book_page_by_page(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    story.run(job)
    assert job.artifact() == job.work / "final.pdf"
    pages = sorted((job.work / "book").glob("*.png"))
    assert len(pages) >= 3
    assert Image.open(pages[0]).size == (story.PAGE_W, story.PAGE_H)


def _embedded_fonts(reader):
    found = set()
    for page in reader.pages[1:]:
        for ref in page["/Resources"]["/Font"].values():
            font = ref.get_object()
            if "/FontFile2" in font["/FontDescriptor"].get_object():
                found.add(str(font["/BaseFont"]))
    return found


def test_a_printed_book_holds_real_text_set_in_its_own_embedded_type(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    script = job.read("story")
    final = story.run(job)
    reader = pypdf.PdfReader(final)
    assert len(reader.pages) == len(list((job.work / "book").glob("*.png")))
    box = reader.pages[0].mediabox
    assert (float(box.width), float(box.height)) == pytest.approx((396.0, 612.0)), "5.5 x 8.5 in"
    assert reader.metadata.title == script["title"]
    read_back = " ".join(page.extract_text() for page in reader.pages[1:]).split()
    for chapter in script["chapters"]:
        for paragraph in chapter["paragraphs"]:
            assert " ".join(paragraph.split()[:6]) in " ".join(read_back)
    assert all("Literata" in name for name in _embedded_fonts(reader)) and _embedded_fonts(reader)


def test_a_printed_book_is_the_same_bytes_each_time(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    first = story.run(job).read_bytes()
    assert story.run(job).read_bytes() == first, "approval is bound to these bytes"


def test_a_page_image_and_its_pdf_page_put_a_word_in_the_same_place(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    story.run(job)
    laid = story.lay_out(job.read("story")["chapters"][0], 1)
    item = next(i for i in story.page_items(laid, 0) if not i.centred)
    assert item.x == story.MARGIN_X, "the first line of a chapter takes no indent"
    assert story.MARGIN_TOP + story.OPENER_DROP - laid.lift < item.baseline


def test_kerning_moves_a_pair_and_keeps_every_letter():
    item = bookpdf.Placed("AVATAR", 0.0, 0.0, 92, optical=48)
    pieces = bookpdf._pieces(item, story.captions.FONTS / story.BODY_FACE)
    assert "".join(text for text, _ in pieces) == "AVATAR"
    if len(pieces) > 1:  # a Pillow built without text shaping sees no kerning in this face
        assert all(nudge < 0 for _, nudge in pieces[:-1])


def test_a_word_is_as_wide_in_print_as_the_line_breaker_measured_it(tmp_path):
    face = story.captions.FONTS / story.BODY_FACE
    book = bookpdf.Book("t", "", story.PAGE_W, story.PAGE_H, tmp_path, face, tmp_path / "cuts")
    name = bookpdf._cut(book, 12, 400)
    font = bookpdf.pil_font(face, story.BODY_SIZE)
    for word in ("The", "first", "office", "Toward", "AVATAR"):
        pieces = bookpdf._pieces(bookpdf.Placed(word, 0.0, 0.0, story.BODY_SIZE), face)
        printed = sum(
            pdfmetrics.stringWidth(text, name, story.BODY_SIZE) + nudge for text, nudge in pieces
        )
        assert printed == pytest.approx(bookpdf.width(font, word), abs=0.5), word


def test_letters_a_ligature_would_join_are_not_crushed_together():
    font = bookpdf.pil_font(story.captions.FONTS / story.BODY_FACE, 46)
    wide = font.getlength("T") + font.getlength("h")
    assert abs(bookpdf._kern(font, "T", "h")) < wide * 0.02
    assert abs(bookpdf._kern(font, "f", "i")) < wide * 0.02


def test_a_story_passes_qa_on_its_own_bytes_and_placeholder_cover_cannot_be_approved(
    tmp_path, monkeypatch
):
    job = _job(tmp_path, monkeypatch)
    story.run(job)
    report = qa.run(job)
    assert report["passed"], [c for c in report["checks"] if c["status"] == "fail"]
    assert report["artifacts_sha256"]["document"] == publish.sha256_file(job.work / "final.pdf")
    with pytest.raises(ContractError, match="placeholder"):
        publish.approve(job, "human", platforms=["youtube"])
