"""Stories: a typeset book and a real EPUB, from the same text."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
import zipfile

import pytest
from PIL import Image

from kalainova import publish, qa, story
from kalainova.jobfs import ContractError, Job


def test_a_paragraph_breaks_into_lines_that_fit_and_lose_no_words():
    text = "The keeper climbed the stairs again that night, as he had every night before it. " * 4
    lines = story.break_lines(text, measure=900, size=46, indent=46)
    assert " ".join(" ".join(line.words) for line in lines).split() == text.split()
    assert all(line.width <= 900 for line in lines)
    assert not lines[-1].justify and lines[0].justify


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
