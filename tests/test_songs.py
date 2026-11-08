"""A song from its words to a finished master, with the model faked and the audio real."""

from __future__ import annotations

import json

import numpy as np
import pytest
from fakes import make_job, needs_ffmpeg

from kalainova import media, publish, qa, songs, takes, writers
from kalainova.bar import song as musicbar
from kalainova.editor import beats
from kalainova.jobfs import ContractError, Job
from kalainova.providers import router

pytestmark = needs_ffmpeg
VERSE = ["Paper boats on the kitchen floor", "Pencil marks beside the door"]
CHORUS = ["Hold the ladder steady now", "Hand me down the garden hose"]


def _song(**extra):
    return {
        "schema_version": "0.1",
        "job_id": "p1",
        "title": "A Song",
        "style": "warm indie pop, acoustic guitar, clear lead vocal",
        "duration_sec": 12,
        "sections": [
            {"kind": "verse", "lines": VERSE, "visual": "paper boats on a floor"},
            {"kind": "chorus", "lines": CHORUS, "style": "full band"},
        ],
        **extra,
    }


def _job(tmp_path, song=None, **extra):
    job = make_job(tmp_path, media=["song"], **extra)
    job.write("song", song or _song())
    return job


def _heard():
    words = [w for line in [*VERSE, *CHORUS] for w in line.split()]
    return [
        {"start_sec": 1.0 + i * 0.4, "end_sec": 1.3 + i * 0.4, "text": w, "confidence": 0.9}
        for i, w in enumerate(words)
    ]


def test_a_song_is_tagged_by_section_the_way_every_song_model_reads_it():
    text = songs.lyrics_text(_song())
    assert text.startswith("[Verse]\nPaper boats on the kitchen floor\n")
    assert "[Chorus]\nHold the ladder steady now" in text


def test_a_pre_chorus_keeps_its_hyphen():
    song = _song(sections=[{"kind": "pre-chorus", "lines": ["Rising"]}])
    assert "[Pre-Chorus]" in songs.lyrics_text(song)


def test_the_style_carries_the_tempo_and_key_it_is_asked_to_hit():
    style = songs.style_text(_song(bpm=96, key="C major"))
    assert "96 bpm" in style and "C major" in style


@pytest.mark.parametrize(
    "style",
    ["pop in the style of a famous band", "sounds like an old crooner", "a cover of that hit"],
)
def test_a_style_asking_to_imitate_someone_never_reaches_a_model(tmp_path, studio, style):
    job = _job(tmp_path, _song(style=style))
    with pytest.raises(ContractError, match="imitate"):
        songs.run(job)
    assert studio.calls == []


def test_a_sung_song_with_no_words_is_refused(tmp_path, studio):
    job = _job(tmp_path, _song(sections=[{"kind": "intro"}]))
    with pytest.raises(ContractError, match="needs lines"):
        songs.run(job)


def test_an_instrumental_needs_no_words(tmp_path, studio):
    job = _job(tmp_path, _song(sections=[{"kind": "intro"}], instrumental=True))
    assert songs.run(job).exists()


def test_several_takes_are_made_each_with_its_own_seed(tmp_path, studio):
    job = _job(tmp_path)
    songs.run(job)
    calls = [c for c in studio.calls if c["capability"] == "song"]
    assert len(calls) >= 2
    assert len({c["seed"] for c in calls}) == len(calls)
    assert len(takes.load(job)["shots"]["song"]["takes"]) == len(calls)


def test_a_silent_file_from_a_model_is_refused_as_a_failed_decode(tmp_path, studio):
    studio.silent_song = True
    with pytest.raises(router.ProviderError, match="no sound"):
        songs.run(_job(tmp_path))


def test_the_finished_file_is_a_master_at_its_target_level(tmp_path, studio):
    final = songs.run(_job(tmp_path))
    loud = media.loudness(final)
    assert abs(loud["integrated_lufs"] - -14) <= 1.0
    assert loud["true_peak_dbtp"] <= -1 + 0.3
    assert media.stream_info(final, "audio")["codec_name"] == "pcm_s24le"
    assert final.with_suffix(".m4a").exists()


def test_a_song_is_faded_so_it_does_not_stop_dead(tmp_path, studio):
    from kalainova import bar

    final = songs.run(_job(tmp_path))
    left, right, sr = media.decode_stereo(final)
    assert bar.ending_drop_db((left + right) / 2, sr) < -12


def test_lyrics_are_timed_to_what_was_heard_when_something_can_hear_them(tmp_path, studio):
    studio.heard = _heard()
    job = _job(tmp_path)
    songs.run(job)
    lrc = (job.work / "final.lrc").read_text()
    assert "[00:01.00]Paper boats on the kitchen floor" in lrc
    assert (job.work / "captions.srt").exists()
    assert job.read("asset_manifest")["assets"][0]["provenance"]["lyric_timing"] == "heard"


def test_lyrics_are_spread_by_length_when_nothing_can_hear_them(tmp_path, studio):
    data = make_job(tmp_path, job_id="p0").job  # the fake's providers, minus a transcriber
    providers = {k: v for k, v in data["providers"].items() if k != "transcribe"}
    job = _job(tmp_path, providers={**providers, "transcribe": []})
    songs.run(job)
    assert job.read("asset_manifest")["assets"][0]["provenance"]["lyric_timing"] == "estimated"
    assert "Paper boats on the kitchen floor" in (job.work / "final.lrc").read_text()


def test_a_line_the_transcript_missed_sits_between_the_lines_around_it(tmp_path):
    final = tmp_path / "s.wav"
    media.run(["-f", "lavfi", "-i", "sine=f=220:d=10:r=48000", "-ac", "2", str(final)])
    words = "Paper boats on the kitchen floor".split() + "Hand me down the garden hose".split()
    heard = [{"start_sec": float(i), "end_sec": i + 0.5, "text": w} for i, w in enumerate(words)]
    song = _song(
        sections=[
            {
                "kind": "verse",
                "lines": ["Paper boats on the kitchen floor", "Pencil marks beside the door"],
            },
            {"kind": "chorus", "lines": ["Hand me down the garden hose"]},
        ]
    )
    cues, how = songs.timed_lines(final, song, heard)
    assert how == "heard"
    assert cues[0]["start_sec"] <= cues[1]["start_sec"] <= cues[2]["start_sec"]
    assert cues[1]["text"] == "Pencil marks beside the door"


def test_stems_are_made_when_a_provider_can_split_them(tmp_path, studio):
    job = _job(tmp_path)
    songs.run(job)
    provenance = job.read("asset_manifest")["assets"][0]["provenance"]
    assert provenance["stems"] == {"vocals": "vocals.wav", "instrumental": "instrumental.wav"}
    assert (job.work / "vocals.wav").exists()


def test_qa_binds_the_exact_file_and_a_person_can_then_approve_it(tmp_path, studio):
    job = _job(tmp_path)
    final = songs.run(job)
    report = qa.run(job)
    assert report["passed"], [c for c in report["checks"] if c["status"] == "fail"]
    assert report["artifacts_sha256"]["audio"] == publish.sha256_file(final)
    assert "song.taste" in {c["id"] for c in report["checks"]}
    assert "conformance" in report["bar"]
    assert publish.approve(job, "human", platforms=["youtube"])["reviewer"] == "human"


def test_a_placeholder_song_can_never_be_approved(tmp_path, monkeypatch, studio):
    job = _job(tmp_path, providers={"song": ["local"], "transcribe": [], "separate": []})
    songs.run(job)
    qa.run(job)
    with pytest.raises(ContractError, match="placeholder"):
        publish.approve(job, "human", platforms=["youtube"])


# ---- readings ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("detected", "asked", "near"),
    [(96, 96, True), (192, 96, True), (48, 96, True), (103, 96, True), (136, 92, False)],
)
def test_half_and_double_time_count_as_the_same_tempo(detected, asked, near):
    assert (musicbar.tempo_miss(detected, asked) <= 0.10) is near


def test_a_tempo_that_means_nothing_is_a_full_miss():
    assert musicbar.tempo_miss(0, 96) == 1.0


def _clicks(path, bpm, seconds=24.0):
    sr = 48000
    x = np.zeros(int(seconds * sr), np.float32)
    at = 0.0
    while at < seconds:
        i = int(at * sr)
        x[i : i + 400] = np.hanning(min(400, x.size - i)) * 0.8
        at += 60.0 / bpm(at)
    from fakes import media as m

    m.subprocess.run(
        [m.FFMPEG, "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-",
         "-ac", "2", str(path)],
        input=x.tobytes(),
        check=True,
    )  # fmt: skip
    return path


def test_a_steady_track_reads_steady_and_a_wandering_one_does_not(tmp_path):
    steady = _clicks(tmp_path / "steady.wav", lambda at: 120.0)
    wander = _clicks(tmp_path / "wander.wav", lambda at: 90.0 + 2.5 * at)
    fps = beats.SR / beats.HOP
    held = musicbar.tempo_drift(beats.onset_envelope(beats._pcm(steady)), fps)
    lost = musicbar.tempo_drift(beats.onset_envelope(beats._pcm(wander)), fps)
    assert held < 0.02 < lost


def test_words_found_counts_what_can_be_picked_out_and_ignores_little_words():
    lines = ["Hold the ladder steady now"]
    assert musicbar.words_found(lines, [{"text": w} for w in "hold ladder steady".split()]) == 1.0
    assert musicbar.words_found(lines, [{"text": "hold"}]) == pytest.approx(1 / 3)
    assert musicbar.words_found([], []) == 1.0


def test_a_take_is_scored_by_readings_met_and_then_by_how_well_the_words_carry():
    report = {
        "met": 2,
        "total": 4,
        "readings": [{"id": "song.words_found", "value": 0.8}],
    }
    assert musicbar.score(report) == pytest.approx(0.5 + 0.2)


def test_a_track_far_from_its_asked_tempo_misses_and_warns_only(tmp_path, studio):
    track = _clicks(tmp_path / "t.wav", lambda at: 136.0)
    report = musicbar.measure(track, _song(bpm=92), None)
    reading = next(r for r in report["readings"] if r["id"] == "song.tempo")
    assert not reading["ok"] and not reading["blocks"]


# ---- a video for it ---------------------------------------------------------------------
def test_a_finished_song_opens_a_job_that_cuts_a_video_to_it(tmp_path, monkeypatch, studio):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    studio.heard = _heard()
    job = _job(tmp_path)
    songs.run(job)
    folder = songs.video_job(job, "p1-video")
    child = Job(folder)
    data = child.job
    assert data["parent_job_id"] == "p1" and data["brief"]["narration"] is False
    assert (child.work / "track.wav").exists()
    packet = child.read("script_packet")
    assert sum(b["duration_sec"] for b in packet["beats"]) == pytest.approx(
        media.duration(job.artifact()), abs=0.3
    )
    assert (
        packet["beats"][0]["visual_cue"] == "paper boats on a floor" or packet["beats"][0]["text"]
    )


def test_a_video_of_a_song_runs_the_line_with_no_voice_and_the_track_unchanged(
    tmp_path, monkeypatch, studio
):
    from kalainova import assets, edit, render

    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    studio.heard = _heard()
    job = _job(tmp_path)
    songs.run(job)
    child = Job(songs.video_job(job, "p1-video", still_only=True))
    studio.calls.clear()
    manifest = assets.run(child)
    assert not [c for c in studio.calls if c["capability"] in ("voice", "music")]
    music = next(a for a in manifest["assets"] if a["id"] == "music")
    assert music["provider"] == "track" and music["provenance"]["parent_job"] == "p1"
    assert manifest["words"], "the lyrics carry through as captions"
    em = edit.run(child)
    assert em["audio"]["music_gain_db"] == 0.0 and em["audio"]["duck"] is False
    render.compile_plan(child)
    assert render.execute(child).exists()


def test_a_video_needs_a_finished_song(tmp_path, monkeypatch, studio):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    with pytest.raises(ContractError, match="make the song first"):
        songs.video_job(_job(tmp_path), "p1-video")


# ---- writing from a brief ---------------------------------------------------------------
def _draft(**extra):
    song = _song(**extra)
    song.pop("schema_version"), song.pop("job_id")
    return json.dumps(song)


def test_a_song_can_start_from_a_brief(tmp_path, studio):
    studio.replies = [_draft()]
    job = make_job(tmp_path, media=["song"])
    writers.ensure(job, "song")
    assert job.read("song")["title"] == "A Song"
    assert "a test" in studio.calls[0]["prompt"], "the brief reaches the writer"


def test_a_writer_that_breaks_the_contract_is_told_and_tries_again(tmp_path, studio):
    studio.replies = ['{"title": "No sections"}', _draft()]
    job = make_job(tmp_path, media=["song"])
    writers.ensure(job, "song")
    assert "failed validation" in studio.calls[1]["prompt"]


def test_a_writer_that_never_gets_it_right_stops_the_job(tmp_path, studio):
    studio.replies = ["not json"] * writers.ATTEMPTS
    with pytest.raises(ContractError, match="failed validation"):
        writers.ensure(make_job(tmp_path, media=["song"]), "song")


def test_a_script_already_written_is_left_alone(tmp_path, studio):
    job = _job(tmp_path)
    writers.ensure(job, "song")
    assert studio.calls == []


def test_with_no_model_the_agent_is_told_what_to_write(tmp_path, studio):
    data = make_job(tmp_path, job_id="p0").job["providers"]
    job = make_job(tmp_path, media=["song"], providers={**data, "llm": []})
    with pytest.raises(ContractError, match="agent write"):
        writers.ensure(job, "song")


def test_a_comic_and_a_book_can_start_from_a_brief_too(tmp_path, studio):
    studio.replies = [
        json.dumps(
            {
                "title": "A Comic",
                "pages": [
                    {
                        "rows": [{"height": 1, "widths": [1]}],
                        "panels": [{"id": "p1", "art": "rain"}],
                    }
                ],
            }
        ),
        json.dumps(
            {"title": "A Book", "chapters": [{"title": "One", "paragraphs": ["It rained."]}]}
        ),
    ]
    comic = make_job(tmp_path, job_id="c1", media=["comic"])
    writers.ensure(comic, "comic")
    assert comic.read("comic_script")["title"] == "A Comic"
    book = make_job(tmp_path, job_id="b1", media=["story"])
    writers.ensure(book, "story")
    assert book.read("story")["title"] == "A Book"


def test_only_checked_research_reaches_a_writer(tmp_path, studio):
    studio.replies = [_draft()]
    job = make_job(tmp_path, media=["song"])
    job.write(
        "research",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "question": "q",
            "sources": [],
            "findings": [
                {
                    "id": "f1",
                    "statement": "CHECKED FACT",
                    "source_ids": ["s"],
                    "quote": "x" * 20,
                    "verified": True,
                },
                {
                    "id": "f2",
                    "statement": "UNCHECKED CLAIM",
                    "source_ids": ["s"],
                    "quote": "y" * 20,
                },
            ],
        },
    )
    writers.ensure(job, "song")
    assert "CHECKED FACT" in studio.calls[0]["prompt"]
    assert "UNCHECKED CLAIM" not in studio.calls[0]["prompt"]
