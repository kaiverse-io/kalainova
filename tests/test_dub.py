"""A piece in another language: its own music and effects, with new words where old ones were."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import make_job, needs_ffmpeg

from kalainova import assets, dub, edit, media, publish, qa, render
from kalainova.jobfs import ContractError

pytestmark = needs_ffmpeg


def _rendered(tmp_path, monkeypatch, studio):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    beats = [{"id": "b1", "role": "hook", "text": "One short line.", "visual_kind": "still"}]
    job = make_job(tmp_path, beats=beats)
    assets.run(job)
    edit.run(job)
    render.compile_plan(job)
    render.execute(job)
    return job


def _reply(job):
    return json.dumps(
        {"cues": [{"id": c["id"], "text": f"translated {c['id']}"} for c in dub.cues_of(job)]}
    )


def test_a_line_is_stretched_to_fit_only_as_far_as_still_sounds_like_speech():
    assert dub.tempo_for(4.0, 4.0) == 1.0
    assert dub.tempo_for(5.0, 4.0) == 1.25
    assert dub.tempo_for(10.0, 4.0) == dub.FASTEST
    assert dub.tempo_for(1.0, 4.0) == dub.SLOWEST
    assert dub.tempo_for(0.0, 4.0) == 1.0


def test_a_dub_is_a_new_job_with_the_same_picture_and_new_words(tmp_path, monkeypatch, studio):
    job = _rendered(tmp_path, monkeypatch, studio)
    studio.replies = [_reply(job)]
    child = dub.run(job, "hi", "p1-hi")
    assert child.job["parent_job_id"] == "p1"
    assert media.summarize(child.artifact())["width"] == media.summarize(job.artifact())["width"]
    voiced = [c["text"] for c in studio.calls if c["capability"] == "voice"]
    assert any(text.startswith("translated") for text in voiced)
    assert (child.work / "captions.srt").exists()


def test_a_dub_is_built_on_the_music_and_effects_so_the_old_voice_never_leaks(
    tmp_path, monkeypatch, studio
):
    job = _rendered(tmp_path, monkeypatch, studio)
    assert (job.work / dub.ME_STEM).exists()
    studio.replies = [_reply(job)]
    seen = []
    real = dub._mix
    monkeypatch.setattr(
        dub,
        "_mix",
        lambda lines, bed, length, dst: (seen.append(bed), real(lines, bed, length, dst)),
    )
    dub.run(job, "hi", "p1-hi")
    assert seen[0] == job.work / dub.ME_STEM


def test_a_dub_passes_its_own_gate_and_a_person_still_approves_it(tmp_path, monkeypatch, studio):
    job = _rendered(tmp_path, monkeypatch, studio)
    studio.replies = [_reply(job)]
    child = dub.run(job, "hi", "p1-hi")
    report = qa.run(child)
    assert report["passed"], [c for c in report["checks"] if c["status"] == "fail"]
    assert publish.approve(child, "human", platforms=["youtube"])["reviewer"] == "human"


def test_a_translation_is_asked_for_once_and_kept(tmp_path, monkeypatch, studio):
    job = _rendered(tmp_path, monkeypatch, studio)
    studio.replies = [_reply(job)]
    cues = dub.cues_of(job)
    first = dub.translate(job, cues, "hi")
    assert dub.translate(job, cues, "hi") == first, "the second call must not ask again"


def test_a_translation_that_drops_a_line_is_refused(tmp_path, monkeypatch, studio):
    job = _rendered(tmp_path, monkeypatch, studio)
    studio.replies = [json.dumps({"cues": []})]
    with pytest.raises(ContractError, match="left out"):
        dub.translate(job, dub.cues_of(job), "hi")


def test_with_no_model_the_agent_is_told_where_to_write_the_translation(
    tmp_path, monkeypatch, studio
):
    job = _rendered(tmp_path, monkeypatch, studio)
    data = job.job
    data["providers"]["llm"] = []
    job.write("job", data)
    with pytest.raises(ContractError, match="agent write"):
        dub.translate(job, dub.cues_of(job), "hi")


def test_a_written_translation_is_used_with_no_model(tmp_path, monkeypatch, studio):
    job = _rendered(tmp_path, monkeypatch, studio)
    data = job.job
    data["providers"]["llm"] = []
    job.write("job", data)
    (job.folder / f"{dub.TRANSLATION_FILE}.hi").write_text(_reply(job))
    assert dub.translate(job, dub.cues_of(job), "hi")[0]["text"] == "translated 0"


def test_a_piece_must_be_rendered_first(tmp_path, monkeypatch, studio):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    with pytest.raises(ContractError, match="render the piece"):
        dub.run(make_job(tmp_path), "hi", "p1-hi")


def test_a_dub_with_lipsync_swaps_the_picture_for_the_synced_one(tmp_path, monkeypatch, studio):
    job = _rendered(tmp_path, monkeypatch, studio)
    studio.replies = [_reply(job)]
    child = dub.run(job, "hi", "p1-hi", lipsync=True)
    sync = next(c for c in studio.calls if c["capability"] == "lipsync")
    assert Path(sync["video"]).name == "final.mp4"
    assert Path(sync["audio"]).name == "mix.norm.wav"
    assert (child.work / "final.mp4").is_file()
    assert not (child.work / "final.lipsync.mp4").exists()


def test_a_dub_with_lipsync_refuses_when_no_provider_is_configured(tmp_path, monkeypatch, studio):
    job = _rendered(tmp_path, monkeypatch, studio)
    data = job.job
    data["providers"]["lipsync"] = []
    job.write("job", data)
    studio.replies = [_reply(job)]
    with pytest.raises(ContractError, match="lipsync requested but no lipsync provider"):
        dub.run(job, "hi", "p1-hi", lipsync=True)
