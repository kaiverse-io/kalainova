"""Comics: the art is generated with no text, and the engine lays out and letters every page."""

from __future__ import annotations

import json
import shutil
import zipfile

import numpy as np
import pytest
from PIL import Image

from kalainova import comic, publish, qa
from kalainova.jobfs import ContractError, Job

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def test_panels_fill_the_page_inside_its_margins_in_reading_order():
    rows = [{"height": 2, "widths": [1]}, {"height": 1, "widths": [1, 2]}]
    rects = comic.panel_rects(rows, 1000, 2000, margin=100, gutter=20)
    assert len(rects) == 3
    assert rects[0].x == 100 and rects[0].y == 100 and rects[0].w == 800
    assert rects[1].y > rects[0].y + rects[0].h and rects[2].x > rects[1].x
    assert rects[2].x + rects[2].w == 900 and rects[2].y + rects[2].h == 1900
    assert rects[0].h > rects[1].h and rects[2].w > rects[1].w


def test_a_panel_is_requested_at_a_shape_a_model_can_make():
    for w, h in [(800, 300), (300, 800), (500, 500), (1768, 900)]:
        ask_w, ask_h = comic.art_size(w, h)
        assert ask_w * ask_h >= w * h * 0.9
        assert any(abs(ask_w / ask_h - a / b) < 0.02 for a, b in comic.ART_SHAPES)


def test_a_line_is_lettered_in_capitals_and_wrapped_to_a_balanced_block():
    block = comic.letter_block("he kept the light for forty long years", 40, max_width=420)
    assert all(line == line.upper() for line in block.lines)
    assert len(block.lines) >= 2
    assert block.width <= 420
    widths = [comic.text_width(line, 40) for line in block.lines]
    assert max(widths) - min(widths) < 0.6 * max(widths)


def test_a_balloon_goes_where_the_art_is_calm_and_avoids_other_balloons():
    calm = np.zeros((300, 300))
    busy = np.random.default_rng(1).uniform(0, 255, (300, 300))
    art = busy.copy()
    art[:120, 150:] = calm[:120, 150:]  # only the top right is quiet
    panel = comic.Rect(0, 0, 300, 300)
    spot = comic.place(art, panel, 100, 60, taken=[])
    assert spot.x >= 150 and spot.y < 120
    second = comic.place(art, panel, 100, 60, taken=[spot])
    assert not comic.overlaps(spot, second)


def test_too_many_words_for_a_panel_is_refused_rather_than_shrunk_past_reading():
    words = "word " * 400
    with pytest.raises(ContractError, match="too much text"):
        comic.fit_lettering(words, comic.Rect(0, 0, 300, 200))


def _job(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    for key in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY"):
        monkeypatch.delenv(key, raising=False)
    folder = tmp_path / "jobs" / "strip"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "strip",
                "strategy": "generated",
                "media": ["comic"],
                "rights": "owned",
                "distribution_identity": "test",
                "status": "draft",
                "skip_funded": True,
                "cost_cap": 0,
                "brief": {"subject": "test"},
            }
        )
    )
    (folder / "comic_script.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "strip",
                "title": "A Test",
                "style": "ink and flat colour",
                "pages": [
                    {
                        "rows": [{"height": 1, "widths": [1]}, {"height": 1, "widths": [1, 1]}],
                        "panels": [
                            {
                                "id": "p1",
                                "art": "a wide scene",
                                "lines": [{"kind": "caption", "text": "It began quietly."}],
                            },
                            {
                                "id": "p2",
                                "art": "a figure at left",
                                "lines": [
                                    {
                                        "kind": "speech",
                                        "text": "Are you there?",
                                        "speaker_at": [0.3, 0.7],
                                    }
                                ],
                            },
                            {
                                "id": "p3",
                                "art": "a door",
                                "lines": [{"kind": "sfx", "text": "Slam"}],
                            },
                        ],
                    }
                ],
            }
        )
    )
    return Job(folder)


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_a_comic_job_delivers_print_and_reader_files(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    comic.run(job)
    assert job.artifact() == job.work / "final.pdf"
    page = Image.open(job.work / "pages" / "001.png")
    assert page.size == (comic.PAGE_W, comic.PAGE_H)
    with zipfile.ZipFile(job.work / "final.cbz") as cbz:
        assert cbz.namelist() == ["001.png"]
    assert Image.open(job.work / "final.scroll.png").width == comic.SCROLL_W


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_no_prompt_ever_asks_a_model_for_lettering(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    comic.run(job)
    for asset in job.read("asset_manifest")["assets"]:
        assert "no text" in asset["prompt"]
        assert "Are you there" not in asset["prompt"]


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_a_comic_passes_qa_and_its_placeholder_art_cannot_be_approved(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    comic.run(job)
    report = qa.run(job)
    assert report["passed"], [c for c in report["checks"] if c["status"] == "fail"]
    assert report["artifacts_sha256"]["document"] == publish.sha256_file(job.work / "final.pdf")
    assert any(c["id"] == "comic.lettering_size" for c in report["checks"])
    with pytest.raises(ContractError, match="placeholder"):
        publish.approve(job, "human", platforms=["youtube"])


def test_a_page_whose_panels_do_not_match_its_layout_is_refused_before_any_art_is_made(
    tmp_path, monkeypatch
):
    job = _job(tmp_path, monkeypatch)
    script = job.read("comic_script")
    script["pages"][0]["panels"].pop()
    job.write("comic_script", script)
    with pytest.raises(ContractError, match="lists 2"):
        comic.run(job)
    assert not (job.work / "panels").exists()


def test_too_many_words_is_refused_before_any_art_is_made(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    script = job.read("comic_script")
    script["pages"][0]["panels"][1]["lines"][0]["text"] = "word " * 400
    job.write("comic_script", script)
    with pytest.raises(ContractError, match="too much text"):
        comic.run(job)
    assert not (job.work / "panels").exists()
