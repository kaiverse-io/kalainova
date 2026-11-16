"""One span of a chosen song take, repainted into a new take that sits beside the original."""

from __future__ import annotations

import json

import pytest
from fakes import make_job, needs_ffmpeg

from kalainova import songs, takes
from kalainova.__main__ import main
from kalainova.jobfs import ContractError

pytestmark = needs_ffmpeg

VERSE = ["Paper boats on the kitchen floor", "Pencil marks beside the door"]
CHORUS = ["Hold the ladder steady now", "Hand me down the garden hose"]


def _song(**extra):
    return {
        "schema_version": "0.1",
        "job_id": "p1",
        "title": "A Song",
        "style": "warm indie pop, acoustic guitar, clear lead vocal",
        "duration_sec": 16,
        "bpm": 120,
        "sections": [
            {"kind": "verse", "lines": VERSE, "bars": 4},
            {"kind": "chorus", "lines": CHORUS, "bars": 4},
        ],
        **extra,
    }


def _job(tmp_path, song=None, **extra):
    job = make_job(tmp_path, media=["song"], **extra)
    job.write("song", song or _song())
    return job


def _ready(tmp_path, song=None, **extra):
    """A job with a chosen song take, ready to be repaired."""
    job = _job(tmp_path, song, **extra)
    songs.run(job)
    return job


# ---------------------------------------------------------------- section time lookup


def test_a_named_section_is_timed_from_its_bar_count_and_the_songs_bpm(tmp_path, studio):
    job = _ready(tmp_path)

    # one 4-bar section at 120bpm is 8s: the verse runs 0-8s, so the chorus starts at 8s
    assert songs.repair_take(job, section="verse")["repair_span"] == [0.0, 8.0]
    assert songs.repair_take(job, section="chorus")["repair_span"] == [8.0, 16.0]
    # section names are matched without regard to case
    assert songs.repair_take(job, section="CHORUS")["repair_span"] == [8.0, 16.0]


def test_an_explicit_span_is_used_as_is_when_no_section_is_named(tmp_path, studio):
    job = _ready(tmp_path)
    repaired = songs.repair_take(job, start_sec=1.0, end_sec=4.5)
    assert repaired["repair_span"] == [1.0, 4.5]
    assert repaired["repair_section"] is None


def test_repair_span_problems_are_refused_before_any_take_is_made(tmp_path, studio):
    job = _ready(tmp_path)
    before = len(takes.load(job)["shots"]["song"]["takes"])

    with pytest.raises(ContractError, match="no section"):
        songs.repair_take(job, section="bridge")
    with pytest.raises(ContractError, match="--section"):
        songs.repair_take(job, start_sec=3.0)
    with pytest.raises(ContractError, match="end greater"):
        songs.repair_take(job, start_sec=5.0, end_sec=5.0)

    # none of the refused calls left a half-made take behind
    assert len(takes.load(job)["shots"]["song"]["takes"]) == before


def test_a_section_with_no_bar_count_cannot_be_timed(tmp_path, studio):
    song = _song(
        sections=[{"kind": "verse", "lines": VERSE, "bars": 4}, {"kind": "chorus", "lines": CHORUS}]
    )
    job = _ready(tmp_path, song)
    with pytest.raises(ContractError, match="no bar count"):
        songs.repair_take(job, section="chorus")


def test_section_lookup_needs_a_bpm(tmp_path, studio):
    song = _song()
    del song["bpm"]
    job = _ready(tmp_path, song)
    with pytest.raises(ContractError, match="bpm"):
        songs.repair_take(job, section="chorus")


# ---------------------------------------------------------------------- songs.repair_take


def test_repairing_a_take_adds_a_new_one_without_touching_the_original(tmp_path, studio):
    job = _ready(tmp_path)
    before = takes.load(job)["shots"]["song"]["takes"]
    original = takes.chosen(job, "song")

    repaired = songs.repair_take(job, section="chorus", prompt="brighter guitar")

    after = takes.load(job)["shots"]["song"]["takes"]
    assert len(after) == len(before) + 1
    # the original take is still there, byte for byte
    kept = next(t for t in after if t["n"] == original["n"])
    assert kept == original
    assert (job.work / original["file"]).exists()

    assert repaired["n"] == max(t["n"] for t in before) + 1
    assert repaired["file"] == f"takes/song/take-{repaired['n']:02d}-repaired.wav"
    assert (job.work / repaired["file"]).exists()
    assert repaired["repaired_from"] == original["n"]
    assert repaired["repair_section"] == "chorus"
    assert repaired["repair_span"] == [8.0, 16.0]
    assert repaired["prompt"] == "brighter guitar"


def test_repairing_a_named_take_number_instead_of_the_chosen_one(tmp_path, studio):
    job = _ready(tmp_path)
    every = takes.load(job)["shots"]["song"]["takes"]
    other = next((t for t in every if t["n"] != takes.chosen(job, "song")["n"]), None)
    if other is None:
        pytest.skip("only one take was made; nothing else to name")

    repaired = songs.repair_take(job, section="verse", take_n=other["n"])

    assert repaired["repaired_from"] == other["n"]


def test_a_repair_asks_the_model_to_repaint_the_span_of_the_chosen_take(tmp_path, studio):
    job = _ready(tmp_path)
    original = takes.chosen(job, "song")
    studio.calls.clear()

    songs.repair_take(job, start_sec=4.0, end_sec=12.0)

    (call,) = [c for c in studio.calls if c["capability"] == "song"]
    assert call["kw"]["task_type"] == "repaint"
    assert call["kw"]["src_audio_path"] == job.work / original["file"]
    assert (call["kw"]["repainting_start"], call["kw"]["repainting_end"]) == (4.0, 12.0)


def test_a_repaired_take_is_measured_like_any_take(tmp_path, studio):
    job = _ready(tmp_path)
    repaired = songs.repair_take(job, section="chorus")
    ids = {r["id"] for r in repaired["readings"]["readings"]}
    assert {"audio.ending_drop_db", "song.tempo_drift"} <= ids
    assert repaired["ok"] == (not repaired["readings"]["misses"])


def test_with_no_model_that_can_repaint_a_repair_is_refused_and_nothing_is_copied(
    tmp_path, studio, monkeypatch
):
    job = _ready(tmp_path)
    before = takes.load(job)["shots"]["song"]["takes"]
    monkeypatch.setattr(studio, "can_repaint", False)
    studio.calls.clear()

    with pytest.raises(ContractError, match="can repaint"):
        songs.repair_take(job, section="chorus")

    assert takes.load(job)["shots"]["song"]["takes"] == before
    assert not list((job.work / "takes" / "song").glob("*-repaired.wav"))
    assert [c for c in studio.calls if c["capability"] == "song"] == []


def test_repairing_with_no_takes_yet_is_refused(tmp_path, studio):
    job = _job(tmp_path)
    with pytest.raises(ContractError, match="no song takes"):
        songs.repair_take(job, section="chorus")


def test_repairing_an_unknown_take_number_is_refused(tmp_path, studio):
    job = _ready(tmp_path)
    with pytest.raises(ContractError, match="no take 99"):
        songs.repair_take(job, section="chorus", take_n=99)


# --------------------------------------------------------------------------------- CLI


def test_cli_song_repair_makes_a_new_take_and_prints_it(tmp_path, studio, capsys):
    job = _ready(tmp_path, job_id="song-1")
    before = len(takes.load(job)["shots"]["song"]["takes"])

    assert main(["song", "repair", str(job.folder), "--section", "chorus"]) == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed["repair_section"] == "chorus"
    assert printed["repaired_from"] is not None
    assert len(takes.load(job)["shots"]["song"]["takes"]) == before + 1


def test_cli_song_repair_needs_a_section_or_a_span(tmp_path, studio, capsys):
    job = _ready(tmp_path, job_id="song-2")

    assert main(["song", "repair", str(job.folder)]) == 1
    assert "error:" in capsys.readouterr().err


def test_cli_song_without_repair_still_runs_the_song_plainly(tmp_path, studio):
    job = _job(tmp_path, job_id="song-3")
    assert main(["song", str(job.folder)]) in (0, 2)
