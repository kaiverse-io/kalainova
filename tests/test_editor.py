"""Editing arm: notes parsing, defect gates, beat grid, and one end-to-end footage edit."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from kalainova.editor import choose, notes

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def test_a_title_ends_where_the_next_instruction_begins():
    s = notes.resolve(["30s landscape reel, medium pace, title: Lift Off, no captions"])
    assert s["title"] == "Lift Off"
    assert s["captions"] is False


def test_a_quoted_title_keeps_its_comma():
    s = notes.resolve(['title: "Three days, two nights", warm'])
    assert s["title"] == "Three days, two nights"
    assert s["grade"] == "warm"


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


def _long_job(tmp_path, monkeypatch, note):
    from footage_fixtures import talk

    from kalainova.editor import analyze, direct
    from kalainova.jobfs import Job

    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    src = tmp_path / "src"
    src.mkdir()
    take = talk(
        src / "a_talk.mp4",
        [(3.0, True), (4.0, False), (3.0, True), (4.0, False), (3.0, True)],
        size=(320, 180),
    )
    folder = tmp_path / "jobs" / "lf"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "lf",
                "strategy": "owned-derivative",
                "media": ["video", "audio"],
                "rights": "owned",
                "distribution_identity": "owned",
                "status": "draft",
            }
        )
    )
    job = Job(folder)
    analyze.ingest(job, [take])
    direct.add_note(job, note)
    direct.run(job)
    return job


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_a_long_form_edit_keeps_the_words_and_takes_out_the_dead_air(tmp_path, monkeypatch):
    from kalainova import media, render

    job = _long_job(
        tmp_path, monkeypatch, "long form talk, keep the original audio, no music, title: A Walk"
    )
    em = job.read("edit_manifest")
    cuts = em["cuts"]
    spans = [c["out_sec"] - c["in_sec"] for c in cuts]
    assert len(cuts) == 3
    assert sum(spans) < 17.0 - 6.0, "most of the 8 seconds of silence is gone"
    assert sum(spans) >= 9.0, "every word stays"
    assert cuts[0]["title"] == "A Walk" and cuts[0]["role"] == "hook"
    # a jump cut inside one take is hidden by a punch-in on every other segment
    assert [c.get("zoom") for c in cuts] == [None, 1.08, None]
    render.compile_plan(job)
    final = render.execute(job)
    assert media.duration(final) == pytest.approx(sum(spans), abs=0.3)
    assert media.summarize(final).get("sample_rate_hz")


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_a_long_form_edit_with_no_footage_left_is_refused(tmp_path, monkeypatch):
    from kalainova.jobfs import ContractError

    with pytest.raises(ContractError, match="no long-form footage"):
        _long_job(tmp_path, monkeypatch, "long form, drop talk")


def _moment(sig, source="s1"):
    return {"shot": {"source": source, "sig": sig}}


def test_a_shot_that_looks_like_one_already_used_waits_its_turn():
    horizon = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
    other = [6.0, 1.0, 5.0, 2.0, 4.0, 3.0]
    pool = [_moment(list(horizon), "s2"), _moment(other, "s3")]
    assert choose.next_moment(pool, used=[horizon], last_source="s1") is pool[1]
    assert choose.next_moment(pool[:1], used=[horizon], last_source="s1") is None


def test_the_first_moment_is_free_to_be_anything():
    pool = [_moment([1.0, 2.0, 3.0, 4.0])]
    assert choose.next_moment(pool, used=[], last_source=None) is pool[0]


def test_shot_lengths_vary_and_stay_on_the_beat():
    for pace in ("fast", "medium", "cinematic"):
        lengths = [choose.beats_for(pace, i) for i in range(12)]
        assert len(set(lengths)) >= 2, pace
        assert all(n % 2 == 0 for n in lengths), pace


def test_exposure_is_only_nudged_and_a_dark_shot_stays_dark():
    def shot(level):
        return {"series": {"lum": [level] * 4}}

    assert choose.gamma(shot(0.45)) == 1.0  # already fine, so it is left alone
    assert choose.gamma(shot(0.25)) == 1.0  # a night shot is meant to be dark
    assert 1.0 < choose.gamma(shot(0.08)) <= 1.25
    assert 0.85 <= choose.gamma(shot(0.92)) < 1.0


def test_natural_pauses_stay_and_a_long_one_is_only_shortened():
    silences = [(5.0, 5.6), (10.0, 13.0), (20.0, 22.0)]
    keep = choose.speech_keeps(silences, 30.0)
    assert keep == [(0.0, 10.15), (12.85, 20.15), (21.85, 30.0)]


def test_a_sliver_of_speech_between_two_pauses_is_not_left_on_its_own():
    keep = choose.speech_keeps([(4.0, 6.0), (6.4, 9.0)], 15.0)
    assert all(b - a >= 1.5 for a, b in keep)
    assert keep[0][0] == 0.0 and keep[-1][1] == 15.0


def _shot(sig, source="s1", span=20.0):
    return {
        "shot": {"source": source, "sig": sig, "in_sec": 0.0, "out_sec": span},
        "a": 0.0,
        "b": span,
    }


def test_a_shot_long_enough_for_the_beat_is_preferred():
    short = _shot([1.0, 2.0, 3.0, 4.0], "s1", span=1.0)
    long = _shot([4.0, 1.0, 3.0, 2.0], "s2", span=9.0)
    assert choose.next_moment([short, long], used=[], last_source=None, need=4.0) is long
    assert choose.next_moment([short], used=[], last_source=None, need=4.0) is short


def test_the_least_used_source_goes_next_so_two_clips_do_not_trade_turns():
    a, b, c = (
        _shot([1.0, 2.0, 3.0, 4.0], "a"),
        _shot([4.0, 1.0, 3.0, 2.0], "b"),
        _shot([2.0, 4.0, 1.0, 3.0], "c"),
    )
    picked = choose.next_moment([a, b, c], used=[], last_source="z", usage={"a": 3, "b": 3, "c": 1})
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
    lengths = [round(b - a, 1) for a, b in zip(starts, starts[1:], strict=False)]
    assert max(lengths) >= min(lengths) * 1.6, lengths
    assert "too small" in (info["note"] or "")


def _take(name, source, at, quality=0.5, motion=0.5):
    return {
        "id": name,
        "source": source,
        "in_sec": at,
        "quality": quality,
        "scores": {"motion": motion},
    }


SOURCES = {"a": {"name": "first_clip.mp4"}, "b": {"name": "second_clip.mp4"}}
TAKES = [
    _take("s1", "a", 4.0, quality=0.4, motion=0.2),
    _take("s2", "a", 0.0, quality=0.9, motion=0.9),
    _take("s3", "b", 2.0, quality=0.5, motion=0.1),
    _take("s4", "b", 0.0, quality=0.6, motion=0.4),
]


def _ordered(name, start_with="", end_with=""):
    settings = {"order": name, "start_with": start_with, "end_with": end_with}
    return [s["id"] for s in choose.order(list(TAKES), settings, SOURCES)]


def test_chronological_order_follows_each_source_as_it_was_shot():
    assert _ordered("chronological") == ["s2", "s1", "s4", "s3"]


def test_best_first_puts_the_strongest_take_first():
    assert _ordered("best_first") == ["s2", "s4", "s3", "s1"]


def test_story_order_opens_on_the_strongest_moving_shot_and_closes_on_a_calm_one():
    assert _ordered("story") == ["s2", "s1", "s3", "s4"]


def test_story_order_with_too_few_shots_keeps_them_all_and_finds_no_closer():
    settings = {"order": "story", "start_with": "", "end_with": ""}
    assert [s["id"] for s in choose.order(TAKES[:2], settings, SOURCES)] == ["s2", "s1"]
    assert choose.order([], settings, SOURCES) == []


def test_a_note_can_name_the_first_and_last_shot_by_id_or_by_file_name():
    assert _ordered("best_first", start_with="s1")[0] == "s1"
    assert _ordered("best_first", end_with="s2")[-1] == "s2"
    assert _ordered("chronological", start_with="second_clip")[0] == "s4"


def test_a_note_naming_nothing_changes_nothing():
    assert _ordered("best_first", start_with="no such shot") == _ordered("best_first")


def test_an_empty_name_matches_no_shot():
    assert not choose.matches(TAKES[0], SOURCES, "  ")
    assert choose.matches(TAKES[0], SOURCES, "a")
    assert choose.matches(TAKES[0], SOURCES, "FIRST")
    assert not choose.matches(TAKES[0], SOURCES, "second")


def _graded(kind="video", sharpness=0.5, exposure=0.5, shake=0.1, **extra):
    scores = {"sharpness": sharpness, "exposure": exposure, "shake": shake}
    return {"kind": kind, "scores": scores, **extra}


def test_a_soft_video_is_rejected_and_a_still_is_not_judged_for_focus():
    assert "soft focus" in choose.defects(_graded(sharpness=0.1))
    assert choose.defects(_graded(sharpness=0.15)) == []
    assert choose.defects(_graded(kind="still", sharpness=0.1)) == []


def test_a_bad_exposure_is_rejected_at_its_limit_and_not_past_it():
    assert "badly exposed" in choose.defects(_graded(exposure=0.34))
    assert choose.defects(_graded(exposure=0.35)) == []


def test_shake_counts_only_when_the_camera_really_moved():
    assert "shaky" in choose.defects(_graded(jitter_px=3.1))
    assert choose.defects(_graded(jitter_px=3.0)) == []
    assert "shaky" in choose.defects(_graded(shake=0.8, jitter_px=1.6))
    assert choose.defects(_graded(shake=0.7, jitter_px=1.6)) == []
    assert choose.defects(_graded(shake=0.8, jitter_px=1.5)) == []


@pytest.mark.parametrize("level", [0.15, 0.75])
def test_an_exposure_at_the_edge_of_normal_is_left_alone(level):
    assert choose.gamma({"series": {"lum": [level]}}) == 1.0


def test_a_shot_with_no_light_reading_is_left_alone():
    assert choose.gamma({"series": {"lum": []}}) == 1.0


def test_a_dark_shot_is_brought_up_by_the_exponent_that_lands_on_mid_grey():
    assert choose.gamma({"series": {"lum": [0.14]}}) == pytest.approx(1.25)
    assert choose.gamma({"series": {"lum": [0.8]}}) == pytest.approx(0.85)


def test_shots_that_look_alike_are_told_apart_only_when_they_can_be_compared():
    assert choose._looks_like([1.0, 2.0, 3.0], [2.0, 4.0, 6.0])
    assert not choose._looks_like([1.0, 2.0, 3.0], [3.0, 2.0, 1.0])
    assert not choose._looks_like([1.0, 2.0], [1.0, 2.0, 3.0]), "different lengths"
    assert not choose._looks_like([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]), "the first is flat"
    assert not choose._looks_like([1.0, 2.0, 3.0], [1.0, 1.0, 1.0]), "the second is flat"


def test_the_next_moment_prefers_a_shot_long_enough_for_the_rhythm():
    short = {"shot": {"source": "a", "in_sec": 0.0, "out_sec": 1.0, "sig": []}}
    enough = {"shot": {"source": "a", "in_sec": 2.0, "out_sec": 3.0, "sig": []}}
    long_shot = {"shot": {"source": "b", "in_sec": 0.0, "out_sec": 4.0, "sig": []}}
    assert choose.next_moment([short, long_shot], [], None, need=2.0) is long_shot
    assert choose.next_moment([short, enough], [], None, need=1.0) is short, "exactly long enough"


def test_the_next_moment_avoids_the_source_just_used():
    same = {"shot": {"source": "a", "in_sec": 0.0, "out_sec": 2.0, "sig": []}}
    other = {"shot": {"source": "b", "in_sec": 0.0, "out_sec": 2.0, "sig": []}}
    assert choose.next_moment([same, other], [], "a") is other


def test_a_pause_is_shortened_to_a_breath_and_speech_is_never_cut():
    kept = choose.speech_keeps([(3.0, 5.0)], 8.0)
    half = choose.PAUSE_KEPT_SEC / 2
    assert kept == [(0.0, 3.0 + half), (5.0 - half, 8.0)]


def test_a_short_pause_stays_in():
    just_under = choose.MIN_PAUSE_TO_CUT_SEC - 0.01
    assert choose.speech_keeps([(3.0, 3.0 + just_under)], 8.0) == [(0.0, 8.0)]
    assert len(choose.speech_keeps([(4.0, 4.0 + choose.MIN_PAUSE_TO_CUT_SEC)], 8.0)) == 2


def test_no_sliver_of_speech_is_left_between_two_cuts():
    assert choose.speech_keeps([(0.5, 3.0)], 8.0) == [(0.0, 8.0)]


def test_a_source_this_edit_has_to_enlarge_too_far_is_named():
    sources = {
        "a": {"name": "small.mp4", "width": 320, "height": 180},
        "b": {"name": "fine.mp4", "width": 960, "height": 540},
    }
    cuts = [{"source": "a"}, {"source": "b"}]
    prof = {"width": 1920, "height": 1080}
    assert choose.too_small(cuts, sources, prof) == ["small.mp4"], "exactly twice is still sharp"
