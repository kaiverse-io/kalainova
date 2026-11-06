"""Editing arm: notes parsing, defect gates, beat grid, and one end-to-end footage edit."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from kalainova.editor import notes

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def test_notes_accumulate_and_override():
    s = notes.resolve(
        [
            "30s reel, warm, cinematic, title: Three days",
            "faster cuts, cooler, drop shaky, open with sunset",
        ]
    )
    assert (s["duration_sec"], s["pace"], s["grade"], s["title"]) == (
        30,
        "fast",
        "cool",
        "Three days",
    )
    assert "shaky" in s["drop"] and s["start_with"] == "sunset"


def test_notes_validate_clamps_llm_output():
    s = notes.validate({"grade": "neon", "duration_sec": 99999, "pace": "fast", "evil": "rm -rf"})
    assert s["grade"] == "natural" and s["duration_sec"] == 3600 and "evil" not in s


def test_long_form_note():
    s = notes.resolve(["long form vlog, keep the original audio, no music"])
    assert s["format"] == "long" and s["original_audio"] and not s["music_on"]


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_footage_edit_rejects_bad_takes(tmp_path, monkeypatch):
    from footage_fixtures import clip, landscape

    from kalainova import qa, render
    from kalainova.editor import analyze, direct
    from kalainova.jobfs import Job

    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    for k in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY"):
        monkeypatch.delenv(k, raising=False)
    src = tmp_path / "in"
    src.mkdir()
    files = [
        clip(src / "a_good.mp4", 1, dur=3, size=(320, 180)),
        clip(src / "b_shaky.mp4", 2, dur=3, shake=6, size=(320, 180)),
        clip(src / "c_good.mp4", 5, dur=3, size=(320, 180)),
        clip(src / "d_dark.mp4", 4, dur=3, dark=0.2, size=(320, 180)),
    ]
    photo = src / "e_photo.jpg"
    landscape(7, 800, 533).save(photo)
    files.append(photo)
    folder = tmp_path / "jobs" / "ed"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "ed",
                "strategy": "owned-derivative",
                "media": ["video", "audio"],
                "rights": "owned",
                "distribution_identity": "owned",
                "status": "draft",
            }
        )
    )
    job = Job(folder)
    analyze.ingest(job, files)
    direct.add_note(job, "8s reel, warm, title: Test trip")
    info = direct.run(job)
    em = job.read("edit_manifest")
    used = {c["source"] for c in em["cuts"]}
    fo = json.loads((folder / "footage.json").read_text())
    names = {x["id"]: x["name"] for x in fo["sources"]}
    assert not any(names[u].startswith(("b_", "d_")) for u in used), [names[u] for u in used]
    render.compile_plan(job)
    render.execute(job)
    report = qa.run(job)
    assert report["passed"], [c for c in report["checks"] if c["status"] == "fail"]
    assert info["settings"]["grade"] == "warm"


def _moment(sig, source="s1"):
    return {"shot": {"source": source, "sig": sig}}


def test_a_shot_that_looks_like_one_already_used_waits_its_turn():
    from kalainova.editor import direct

    horizon = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    other = [6.0, 1.0, 5.0, 2.0, 4.0, 3.0]
    pool = [_moment(list(horizon), "s2"), _moment(other, "s3")]
    assert direct.next_moment(pool, used=[horizon], last_source="s1") is pool[1]
    assert direct.next_moment(pool[:1], used=[horizon], last_source="s1") is None


def test_the_first_moment_is_free_to_be_anything():
    from kalainova.editor import direct

    pool = [_moment([1.0, 2.0, 3.0, 4.0])]
    assert direct.next_moment(pool, used=[], last_source=None) is pool[0]


def test_shot_lengths_vary_and_stay_on_the_beat():
    from kalainova.editor import direct

    for pace in ("fast", "medium", "cinematic"):
        lengths = [direct.beats_for(pace, i) for i in range(12)]
        assert len(set(lengths)) >= 2, pace
        assert all(n % 2 == 0 for n in lengths), pace


def test_exposure_is_only_nudged_and_a_dark_shot_stays_dark():
    from kalainova.editor import direct

    def shot(level):
        return {"series": {"lum": [level] * 4}}

    assert direct._gamma(shot(0.45)) == 1.0  # already fine, so it is left alone
    assert direct._gamma(shot(0.25)) == 1.0  # a night shot is meant to be dark
    assert 1.0 < direct._gamma(shot(0.08)) <= 1.25
    assert 0.85 <= direct._gamma(shot(0.92)) < 1.0


def test_natural_pauses_stay_and_a_long_one_is_only_shortened():
    from kalainova.editor import direct

    silences = [(5.0, 5.6), (10.0, 13.0), (20.0, 22.0)]
    keep = direct.speech_keeps(silences, 30.0)
    assert keep == [(0.0, 10.15), (12.85, 20.15), (21.85, 30.0)]


def test_a_sliver_of_speech_between_two_pauses_is_not_left_on_its_own():
    from kalainova.editor import direct

    keep = direct.speech_keeps([(4.0, 6.0), (6.4, 9.0)], 15.0)
    assert all(b - a >= 1.5 for a, b in keep)
    assert keep[0][0] == 0.0 and keep[-1][1] == 15.0


def _shot(sig, source="s1", span=20.0):
    return {
        "shot": {"source": source, "sig": sig, "in_sec": 0.0, "out_sec": span},
        "a": 0.0,
        "b": span,
    }


def test_a_shot_long_enough_for_the_beat_is_preferred():
    from kalainova.editor import direct

    short = _shot([1.0, 2.0, 3.0, 4.0], "s1", span=1.0)
    long = _shot([4.0, 1.0, 3.0, 2.0], "s2", span=9.0)
    assert direct.next_moment([short, long], used=[], last_source=None, need=4.0) is long
    assert direct.next_moment([short], used=[], last_source=None, need=4.0) is short


def test_the_least_used_source_goes_next_so_two_clips_do_not_trade_turns():
    from kalainova.editor import direct

    a, b, c = (
        _shot([1.0, 2.0, 3.0, 4.0], "a"),
        _shot([4.0, 1.0, 3.0, 2.0], "b"),
        _shot([2.0, 4.0, 1.0, 3.0], "c"),
    )
    picked = direct.next_moment([a, b, c], used=[], last_source="z", usage={"a": 3, "b": 3, "c": 1})
    assert picked is c


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_a_reel_cuts_in_a_phrase_and_warns_about_tiny_sources(tmp_path, monkeypatch):
    from footage_fixtures import clip

    from kalainova.editor import analyze, direct
    from kalainova.jobfs import Job

    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    for k in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY"):
        monkeypatch.delenv(k, raising=False)
    src = tmp_path / "in"
    src.mkdir()
    files = [clip(src / f"{i}.mp4", i + 10, dur=8, size=(320, 180)) for i in range(8)]
    folder = tmp_path / "jobs" / "ph"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "ph",
                "strategy": "owned-derivative",
                "media": ["video", "audio"],
                "rights": "owned",
                "distribution_identity": "owned",
                "status": "draft",
            }
        )
    )
    job = Job(folder)
    analyze.ingest(job, files)
    direct.add_note(job, "12s reel, fast cuts")
    info = direct.run(job)
    em = job.read("edit_manifest")
    starts = [c["start_sec"] for c in em["cuts"]] + [em["duration_sec"]]
    lengths = [round(b - a, 1) for a, b in zip(starts, starts[1:])]
    assert max(lengths) >= min(lengths) * 1.6, lengths
    assert "too small" in (info["note"] or "")
