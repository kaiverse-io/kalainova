"""A new provider, an outside tool, and an audio-only piece all use the same contracts."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys

import pytest

from kalainova import intake, media, publish, qa
from kalainova.jobfs import ContractError, Job
from kalainova.providers import base, router

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")


def make_job(tmp_path, monkeypatch, media_kinds, cap=10):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    folder = tmp_path / "jobs" / "c"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(json.dumps({
        "schema_version": "0.1", "job_id": "c", "strategy": "generated", "media": media_kinds, "rights": "owned",
        "distribution_identity": "t", "status": "draft", "cost_cap": cap}))
    return Job(folder)


def record(provider="outside", model="m", cost=1.5):
    return {"assets": [{"id": "x", "kind": "audio", "path": "final.wav", "provider": provider, "model": model,
                        "rights": "owned", "cost": cost, "synthetic": True}]}


def tone(path, seconds=2):
    media.run(["-f", "lavfi", "-i", f"sine=d={seconds}", "-ar", "48000", "-ac", "2", str(path)])
    return path


def clip(path):
    media.run(["-f", "lavfi", "-i", "color=c=blue:s=64x64:d=1", "-pix_fmt", "yuv420p", str(path)])
    return path


def test_a_plugin_registered_first_does_not_hide_the_built_ins():
    code = """
import sys
sys.path.insert(0, ".")
from kalainova.providers.base import Provider, names, register
@register
class G(Provider):
    name = "gpu"
    capabilities = ("image",)
print(names())
"""
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert all(name in out for name in ("gpu", "local", "fal"))


def test_a_provider_can_need_several_keys(monkeypatch):
    class TwoKeys(base.Provider):
        name = "twokeys"
        env_keys = ("LAB_ACCOUNT", "LAB_TOKEN")

    monkeypatch.delenv("LAB_TOKEN", raising=False)
    monkeypatch.setenv("LAB_ACCOUNT", "a")
    assert TwoKeys().missing_env() == ["LAB_TOKEN"]
    assert not TwoKeys().available()
    monkeypatch.setenv("LAB_TOKEN", "t")
    assert TwoKeys().available()


def test_an_asset_can_record_how_it_was_made(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch, ["audio"])
    job.write("asset_manifest", {"schema_version": "0.1", "job_id": job.id, "assets": [
        {"id": "x", "kind": "audio", "path": "a.wav", "provenance": {"node": "n3", "weights_sha256": "ab", "seed": 42}}]})
    assert job.read("asset_manifest")["assets"][0]["provenance"]["seed"] == 42


@needs_ffmpeg
def test_a_song_request_runs_through_the_router(tmp_path, monkeypatch):
    class Songs(base.Provider):
        name = "songs"
        capabilities = ("song",)
        free = True

        def song(self, lyrics, dst, *, style="", duration=None, **kw):
            tone(dst)
            return base.Result(path=dst, model=f"songs-{style}", meta={"lyrics": lyrics})

    base.names()
    monkeypatch.setitem(base._REGISTRY, "songs", Songs)
    job = make_job(tmp_path, monkeypatch, ["audio"])
    data = job.job
    data["providers"] = {"song": ["songs"]}
    job.write("job", data)
    p, res = router.generate(job, "song", "song", "some lyrics", job.work / "song.wav", style="pop")
    assert p.name == "songs" and res.meta["lyrics"] == "some lyrics" and res.path.exists()


@needs_ffmpeg
def test_an_audio_only_piece_goes_from_intake_to_approval(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch, ["audio"])
    src = tone(tmp_path / "song.wav")
    final = intake.run(job, src, record())
    assert final.name == "final.wav" and job.job["status"] == "rendered"
    report = qa.run(job)
    assert report["passed"], report["checks"]
    assert "audio" in report["artifacts_sha256"]
    approval = publish.approve(job, "human", platforms=["youtube"])
    assert approval["artifact_sha256"] == publish.sha256_file(final)
    assert publish.publish(job, "youtube", dry_run=True)["status"] == "dry_run"
    with pytest.raises(ContractError, match="audio-only"):
        publish.publish(job, "youtube", dry_run=False)


@needs_ffmpeg
def test_a_video_file_from_an_outside_tool_passes_through_qa(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch, ["video"])
    intake.run(job, clip(tmp_path / "out.mp4"), record())
    assert not job.has("edit_manifest")
    report = qa.run(job)
    assert "video" in report["artifacts_sha256"]
    assert any(c["id"] == "judge.content" and c["status"] == "warn" for c in report["checks"])


@needs_ffmpeg
def test_intake_refuses_the_wrong_kind_of_file(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch, ["video"])
    with pytest.raises(ContractError, match="needs an .mp4"):
        intake.run(job, tone(tmp_path / "song.wav"), record())


@needs_ffmpeg
@pytest.mark.parametrize("drop", ["provider", "model", "rights"])
def test_intake_refuses_a_record_that_does_not_say_how_it_was_made(tmp_path, monkeypatch, drop):
    job = make_job(tmp_path, monkeypatch, ["audio"])
    bad = record()
    del bad["assets"][0][drop]
    with pytest.raises(ContractError, match=drop):
        intake.run(job, tone(tmp_path / "song.wav"), bad)
    assert job.spent() == 0


@needs_ffmpeg
def test_taking_in_the_same_file_twice_charges_once(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch, ["audio"])
    src = tone(tmp_path / "song.wav")
    intake.run(job, src, record())
    intake.run(job, src, record())
    assert job.spent() == 1.5


@needs_ffmpeg
def test_a_placeholder_from_an_outside_tool_is_still_refused(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch, ["audio"])
    intake.run(job, tone(tmp_path / "song.wav"), record(provider="local", cost=0))
    qa.run(job)
    with pytest.raises(ContractError, match="placeholder"):
        publish.approve(job, "human", platforms=["youtube"])


@needs_ffmpeg
def test_an_audio_file_changed_after_qa_cannot_be_approved(tmp_path, monkeypatch):
    job = make_job(tmp_path, monkeypatch, ["audio"])
    final = intake.run(job, tone(tmp_path / "song.wav"), record())
    qa.run(job)
    tone(final, seconds=3)
    with pytest.raises(ContractError, match="not the file QA checked"):
        publish.approve(job, "human", platforms=["youtube"])
