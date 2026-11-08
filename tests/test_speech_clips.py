"""Cutting speech on words, and finding short pieces in a long recording."""

from __future__ import annotations

import json

import pytest
from fakes import EVERY, make_job, needs_ffmpeg

from kalainova import media, qa, render
from kalainova.editor import analyze, clips, direct, speech
from kalainova.jobfs import ContractError


def _words(*items):
    return [
        {"start_sec": start, "end_sec": end, "text": text, "confidence": 0.9}
        for start, end, text in items
    ]


def test_a_cut_never_lands_inside_a_word_and_every_edge_is_padded():
    words = _words((1.0, 1.4, "One"), (1.5, 2.0, "two."), (5.0, 5.8, "Three."))
    spans = speech.keeps(words, 10.0)
    assert spans == [(0.95, 2.08), (4.95, 5.88)]


def test_a_short_pause_stays_because_cutting_it_reads_as_choppy():
    words = _words((1.0, 2.0, "One"), (2.3, 3.0, "two."))
    assert len(speech.keeps(words, 10.0)) == 1


def test_words_close_together_join_the_run_they_belong_to_not_the_first_one():
    words = _words((1.0, 1.6, "One."), (5.0, 5.4, "Two"), (5.5, 6.0, "three."))
    assert speech.keeps(words, 10.0) == [(0.95, 1.68), (4.95, 6.08)]


def test_a_run_exactly_as_long_as_the_shortest_allowed_is_kept():
    assert speech.keeps(_words((1.0, 1.37, "Yes.")), 10.0) == [(0.95, 1.45)]


def test_a_filler_is_cut_and_can_be_kept():
    words = _words((1.0, 2.0, "Well,"), (2.2, 2.5, "um,"), (2.8, 4.0, "yes."))
    assert len(speech.keeps(words, 10.0)) == 2
    assert len(speech.keeps(words, 10.0, drop_fillers=False)) == 1


def test_an_edge_never_passes_the_ends_of_the_source():
    spans = speech.keeps(_words((0.0, 0.9, "Start."), (9.5, 10.0, "End, now.")), 10.0)
    assert spans[0][0] == 0.0 and spans[-1][1] == 10.0


def test_a_scrap_too_short_to_read_as_speech_is_dropped():
    assert speech.keeps(_words((1.0, 1.1, "A")), 10.0) == []


def test_nothing_said_means_nothing_kept():
    assert speech.keeps([], 10.0) == []


def test_words_move_to_their_time_in_the_finished_cut():
    words = _words((1.0, 1.5, "kept"), (3.0, 3.5, "gone"), (6.0, 6.5, "also"))
    placed = speech.on_output_timeline(words, [(0.5, 2.0), (5.5, 7.0)])
    assert [w["text"] for w in placed] == ["kept", "also"]
    assert placed[0]["start_sec"] == 0.5 and placed[1]["start_sec"] == 2.0
    assert placed[0]["end_sec"] == 1.0 and placed[1]["end_sec"] == 2.5


def test_a_word_that_reaches_the_very_end_of_a_kept_part_stays():
    placed = speech.on_output_timeline(_words((1.0, 2.0, "edge")), [(0.5, 2.0)])
    assert [w["text"] for w in placed] == ["edge"]


def _transcript_words():
    out = []
    at = 0.0
    for n in range(60):
        out.append(
            {
                "start_sec": at,
                "end_sec": at + 0.4,
                "text": f"word{n}." if n % 10 == 9 else f"word{n}",
                "confidence": 0.9,
            }
        )
        at += 0.5
    return out


@needs_ffmpeg
def test_a_transcript_is_made_once_and_kept_by_the_sources_bytes(tmp_path, studio):
    job = make_job(tmp_path)
    source = job.work / "talk.wav"
    media.run(["-f", "lavfi", "-i", "sine=f=220:d=1", str(source)])
    studio.heard = _words((0.1, 0.5, "Hello."))
    assert speech.transcript(job, source)[0]["text"] == "Hello."
    assert speech.transcript(job, source)[0]["text"] == "Hello."
    assert sum(1 for c in studio.calls if c["capability"] == "transcribe") == 1


def test_with_nothing_to_transcribe_there_is_no_transcript(tmp_path, studio):
    job = make_job(tmp_path, providers={"transcribe": []})
    source = job.work / "talk.wav"
    source.write_bytes(b"x")
    assert speech.transcript(job, source) is None


def test_with_no_model_the_densest_whole_sentences_are_chosen_with_no_overlap():
    found = clips.densest(_transcript_words(), 2)
    assert 1 <= len(found) <= 2
    for clip in found:
        assert clips.SHORTEST_SEC <= clip["end_sec"] - clip["start_sec"] <= clips.LONGEST_SEC
    assert found == sorted(found, key=lambda c: c["start_sec"])
    if len(found) == 2:
        assert found[0]["end_sec"] <= found[1]["start_sec"]


def test_a_chosen_clip_is_moved_onto_words_and_an_empty_one_is_thrown_away():
    words = _words((1.0, 1.5, "a"), (2.0, 2.5, "b"), (3.0, 3.5, "c"))
    snapped = clips.snap({"start_sec": 1.2, "end_sec": 2.2, "title": "t"}, words)
    assert snapped["start_sec"] == 1.0 and snapped["end_sec"] == 2.5
    assert clips.snap({"start_sec": 8.0, "end_sec": 9.0}, words) is None


def test_a_model_picks_the_moments_when_one_is_ready(tmp_path, studio):
    studio.replies = [
        json.dumps(
            {
                "clips": [
                    {"start_sec": 0.2, "end_sec": 16.0, "title": "The turn", "why": "a surprise"},
                    {"start_sec": 500.0, "end_sec": 510.0, "title": "Nothing there"},
                ]
            }
        )
    ]
    job = make_job(tmp_path)
    picked = clips.choose(job, _transcript_words(), 3)
    assert [c["title"] for c in picked] == ["The turn"]
    assert "[0.0-4.9]" in studio.calls[0]["prompt"], "the transcript goes in by sentence"


def test_finding_clips_needs_a_transcript(tmp_path, studio):
    job = make_job(tmp_path, providers={"transcribe": []})
    source = job.work / "talk.wav"
    source.write_bytes(b"x")
    with pytest.raises(ContractError, match="transcript"):
        clips.find(job, source)


@needs_ffmpeg
def test_a_clip_with_nothing_said_in_it_opens_no_job(tmp_path, monkeypatch, studio):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    job = make_job(tmp_path)
    source = job.work / "talk.wav"
    media.run(["-f", "lavfi", "-i", "sine=f=220:d=4", str(source)])
    studio.heard = _words((3.0, 3.5, "late"))
    with pytest.raises(ContractError, match="nothing to keep in The turn"):
        clips.open_job(job, source, {"start_sec": 0, "end_sec": 2, "title": "The turn"}, "c0")


@needs_ffmpeg
def test_a_clip_will_not_overwrite_a_job_that_exists(tmp_path, monkeypatch, studio):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    job = make_job(tmp_path)
    source = job.work / "talk.wav"
    media.run(["-f", "lavfi", "-i", "sine=f=220:d=4", str(source)])
    studio.heard = _words((0.5, 1.5, "said"))
    clip = {"start_sec": 0, "end_sec": 2, "title": "The turn"}
    with pytest.raises(ContractError, match="already exists"):
        clips.open_job(job, source, clip, job.id)


@needs_ffmpeg
def test_a_clip_becomes_its_own_job_and_passes_the_same_gates(tmp_path, monkeypatch, studio):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    job = make_job(tmp_path)
    source = job.work / "talk.mp4"
    media.run(
        ["-f", "lavfi", "-i", "testsrc2=s=640x360:d=30:r=24", "-f", "lavfi", "-i",
         "sine=f=220:d=30:r=48000", "-pix_fmt", "yuv420p", "-shortest", str(source)]
    )  # fmt: skip
    studio.heard = _transcript_words()
    clip = {"start_sec": 0.0, "end_sec": 20.0, "title": "The turn"}
    child = clips.open_job(job, source, clip, "p1-clip-00")
    assert child.job["parent_job_id"] == "p1" and child.job["profile"] == "short-9x16"
    em = child.read("edit_manifest")
    assert em["captions"], "its words come with it"
    assert em["captions"][0]["start_sec"] == pytest.approx(0.05, abs=0.1)
    render.compile_plan(child)
    out = render.execute(child)
    info = media.summarize(out)
    assert (info["width"], info["height"]) == (1080, 1920)
    report = qa.run(child)
    assert report["passed"], [c for c in report["checks"] if c["status"] == "fail"]


def _talking_job(tmp_path):
    from footage_fixtures import talk

    take = talk(tmp_path / "a_talk.mp4", [(3.0, True), (4.0, False), (3.0, True)], size=(320, 180))
    no_model = {capability: ["fake"] for capability in EVERY} | {"llm": []}
    job = make_job(
        tmp_path, job_id="lf", strategy="owned-derivative", providers=no_model, profile="landscape"
    )
    analyze.ingest(job, [take])
    direct.add_note(job, "long form talk, keep the original audio, no music")
    return job


@needs_ffmpeg
def test_a_long_piece_cuts_on_its_words_and_carries_them_as_closed_captions(tmp_path, studio):
    job = _talking_job(tmp_path)
    studio.heard = _words((0.2, 1.4, "First"), (1.5, 2.9, "part."), (7.1, 8.0, "Second"))
    direct.run(job)
    em = job.read("edit_manifest")
    assert [(c["in_sec"], c["out_sec"]) for c in em["cuts"]] == [(0.15, 2.98), (7.05, 8.08)]
    assert em["captions"] == [], "a long piece does not burn its words into the picture"
    cues = em["closed_captions"]
    assert "First part." in cues[0]["text"] and "Second" in cues[-1]["text"]
    second_starts = 2.98 - 0.15 + 7.1 - 7.05
    assert cues[-1]["end_sec"] > second_starts, "the words sit where the finished cut says them"
    render.compile_plan(job)
    render.execute(job)
    assert "Second" in (job.work / "captions.vtt").read_text()


@needs_ffmpeg
def test_a_recording_with_no_words_found_falls_back_to_its_silences(tmp_path, studio):
    job = _talking_job(tmp_path)
    studio.heard = []
    direct.run(job)
    em = job.read("edit_manifest")
    assert len(em["cuts"]) == 2, "the silence detector still cuts the dead air"
    assert not em.get("closed_captions")
