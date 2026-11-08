"""The commands a person runs on a piece, driven the way they run them, from plan to record."""

from __future__ import annotations

import json

import pytest
from fakes import EVERY, make_job, needs_ffmpeg

from kalainova.__main__ import main

pytestmark = needs_ffmpeg


NO_LLM = {capability: ["fake"] for capability in EVERY} | {"llm": []}


def _beat(n, **extra):
    return {
        "id": f"b{n}",
        "role": "hook" if n == 1 else "body",
        "text": f"Line number {n} of the piece.",
        "visual_kind": "video",
        "visual_cue": "Waves rolling in",
        **extra,
    }


@pytest.fixture
def home(tmp_path, monkeypatch, studio):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def piece(home):
    """A job with two moving shots, with no model to write its script or read its frames."""
    return make_job(home, beats=[_beat(1), _beat(2)], providers=NO_LLM)


def _out(capsys):
    return capsys.readouterr().out


def test_a_plan_is_reviewed_before_any_money_is_spent(piece, studio, capsys):
    assert main(["shotplan", "p1"]) == 0
    assert "plan.slideshow_risk" not in _out(capsys)
    assert studio.calls == []


def test_a_plan_that_cannot_be_made_exits_with_a_failure(home, capsys):
    make_job(home, beats=[_beat(1, on_camera=True)])
    assert main(["shotplan", "p1"]) == 1
    assert "plan.on_camera" in _out(capsys)


def test_a_piece_goes_from_takes_to_a_record_through_the_commands(piece, studio, capsys, tmp_path):
    assert main(["make", "p1", "--from", "assets"]) in (0, 2)
    _out(capsys)

    assert main(["takes", "p1"]) == 0
    listed = _out(capsys)
    assert "b1: uses take 0, chosen by reading" in listed and "seed" in listed

    assert main(["retake", "p1", "b1", "The light is wrong."]) == 0
    assert "take 1 is in use" in _out(capsys)
    assert "The light is wrong." in studio.calls[-1]["prompt"]

    assert main(["take", "p1", "b1", "0"]) == 0
    assert "b1 uses take 0" in _out(capsys)
    takes_file = json.loads((piece.folder / "takes.json").read_text())
    assert takes_file["shots"]["b1"]["chosen_by"] != "reading", "a person's choice is recorded"

    assert main(["make", "p1", "--from", "edit"]) in (0, 2)
    _out(capsys)

    assert main(["sheet", "p1"]) == 0
    assert (piece.work / "shots.jpg").exists()
    _out(capsys)

    final = piece.work / "final.mp4"
    strip = tmp_path / "strip.jpg"
    assert main(["filmstrip", str(final), "0", "1", "--frames", "4", "--out", str(strip)]) == 0
    assert strip.exists()
    _out(capsys)

    assert main(["cutcheck", "p1"]) in (0, 2)
    assert "cuts," in _out(capsys)
    assert (piece.work / "cutcheck.json").exists()

    for kind, suffix in (("fcpxml", ".fcpxml"), ("otio", ".otio"), ("edl", ".edl")):
        assert main(["export", "p1", "--to", kind]) == 0
        assert _out(capsys).strip().endswith(suffix)

    assert main(["verdict", "p1", "fix", "--reviewer", "someone", "--note", "Too slow."]) == 0
    assert json.loads(_out(capsys))["reviewer"] == "someone"

    assert main(["signals"]) == 0
    assert _out(capsys).strip(), "says what it can, even when that is nothing yet"

    assert main(["provenance", "p1"]) == 0
    assert "provenance" in _out(capsys)

    assert main(["ledger", "p1", "--invoice", "1.5"]) == 0
    assert "gap" in _out(capsys)
    assert json.loads((piece.folder / "invoices.jsonl").read_text())["invoice"] == 1.5


def test_a_person_cannot_take_a_take_that_was_never_made(piece, capsys):
    assert main(["make", "p1", "--from", "assets"]) in (0, 2)
    _out(capsys)
    assert main(["take", "p1", "b1", "9"]) != 0


def test_research_needs_a_question_or_something_to_check(piece, capsys):
    assert main(["research", "p1"]) != 0


def test_research_gathers_sources_and_check_fails_a_quote_they_do_not_hold(piece, studio, capsys):
    studio.hits = [
        {
            "url": "https://example.org/bridge",
            "title": "The bridge",
            "publisher": "An Archive",
            "text": "The bridge first opened in 1849.",
        }
    ]
    studio.replies = ["{}"]
    assert main(["research", "p1", "When did the bridge open?"]) == 0
    assert "1 sources" in _out(capsys)
    data = piece.read("research")
    data["findings"] = [
        {
            "id": "f1",
            "statement": "It opened in 1900.",
            "source_ids": ["s01"],
            "quote": "first opened in 1900",
        }
    ]
    piece.write("research", data)
    assert main(["research", "p1", "--check"]) == 2
    assert "[fail]" in _out(capsys)


def test_a_song_is_made_and_opens_a_video_job_through_the_commands(home, studio, capsys):
    job = make_job(
        home,
        media=["song"],
        providers=NO_LLM,
    )
    job.write(
        "song",
        {
            "schema_version": "0.1",
            "job_id": "p1",
            "title": "A Song",
            "style": "warm indie pop",
            "duration_sec": 12,
            "sections": [{"kind": "verse", "lines": ["Paper boats on the kitchen floor"]}],
        },
    )
    assert main(["song", "p1"]) in (0, 2)
    assert "final.wav" in _out(capsys)
    assert main(["song-video", "p1", "p1-video", "--stills"]) == 0
    assert "make p1-video --from assets" in _out(capsys)


def test_a_recording_gives_short_clips_and_each_opens_a_job(home, studio, capsys):
    from footage_fixtures import talk

    from kalainova.editor import analyze

    take = talk(home / "a_talk.mp4", [(20.0, True)], size=(320, 180))
    job = make_job(
        home,
        strategy="owned-derivative",
        providers=NO_LLM,
    )
    analyze.ingest(job, [take])
    studio.heard = [
        {
            "start_sec": n * 0.5,
            "end_sec": n * 0.5 + 0.4,
            "text": f"word{n}." if n % 10 == 9 else f"word{n}",
            "confidence": 0.9,
        }
        for n in range(38)
    ]
    assert main(["clips", "p1", "--count", "1", "--open"]) == 0
    printed = _out(capsys)
    assert "p1-clip-00" in printed and "0:" not in printed.split("p1-clip-00")[1]


def test_a_recording_with_nothing_said_gives_no_clips(home, studio, capsys):
    from footage_fixtures import talk

    from kalainova.editor import analyze

    take = talk(home / "a_talk.mp4", [(4.0, False)], size=(320, 180))
    job = make_job(
        home,
        strategy="owned-derivative",
        providers=NO_LLM,
    )
    analyze.ingest(job, [take])
    studio.heard = []
    assert main(["clips", "p1"]) == 1
