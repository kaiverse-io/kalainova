"""A piece with no picture: narration, a podcast, a story read aloud."""

from __future__ import annotations

import json
import shutil

import pytest

from kalainova import assets, edit, media, publish, qa, render
from kalainova.jobfs import Job

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _job(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    for key in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY"):
        monkeypatch.delenv(key, raising=False)
    folder = tmp_path / "jobs" / "pod"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "pod",
                "strategy": "audio-native",
                "media": ["audio"],
                "rights": "owned",
                "distribution_identity": "test",
                "status": "draft",
                "cost_cap": 0,
                "profile": "podcast",
                "brief": {"subject": "test"},
            }
        )
    )
    (folder / "script_packet.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "pod",
                "beats": [
                    {"id": "b1", "role": "hook", "text": "A first thought for the ear."},
                    {"id": "b2", "role": "body", "text": "And then a second one follows it."},
                ],
            }
        )
    )
    job = Job(folder)
    assets.run(job)
    edit.run(job)
    render.compile_plan(job)
    render.execute(job)
    return job


def test_an_audio_job_delivers_a_mastered_file_and_nothing_with_a_picture(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    master, delivery = job.work / "final.wav", job.work / "final.m4a"
    assert not (job.work / "final.mp4").exists()
    assert job.artifact() == master
    got = media.loudness(master)
    assert abs(got["integrated_lufs"] - -16.0) <= 0.3
    assert got["true_peak_dbtp"] <= -1.0 + 0.1
    assert media.stream_info(master, "audio")["codec_name"] == "pcm_s24le"
    assert media.stream_info(delivery, "audio")["codec_name"] == "aac"
    assert (job.work / "captions.srt").exists()


def test_an_audio_job_passes_qa_on_its_own_bytes_and_stays_a_placeholder(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    report = qa.run(job)
    assert report["passed"], [c for c in report["checks"] if c["status"] == "fail"]
    assert report["artifacts_sha256"]["audio"] == publish.sha256_file(job.work / "final.wav")
    with pytest.raises(Exception, match="placeholder"):
        publish.approve(job, "human", platforms=["youtube"])
