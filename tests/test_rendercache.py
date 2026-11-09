"""Change one input, re-run what depends on it, and leave the rest alone."""

from __future__ import annotations

import os

import pytest
from fakes import make_job, needs_ffmpeg

from kalainova import media, render
from kalainova.jobfs import ContractError
from kalainova.render import cache as rendercache

pytestmark = needs_ffmpeg


def _tone(path):
    media.run(["-f", "lavfi", "-i", "sine=f=220:d=1:r=48000", "-ac", "2", str(path)])


def _plan(target=-14):
    return {
        "steps": [
            {
                "op": "loudnorm",
                "args": {
                    "input": "in.wav",
                    "out": "a.wav",
                    "target_lufs": target,
                    "true_peak_dbtp_max": -1,
                },
            },
            {
                "op": "loudnorm",
                "args": {
                    "input": "a.wav",
                    "out": "b.wav",
                    "target_lufs": target,
                    "true_peak_dbtp_max": -1,
                },
            },
        ]
    }


def _job(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path, media=["audio"])
    _tone(job.work / "in.wav")
    return job


def _stamps(job):
    return {n: (job.work / n).stat().st_mtime_ns for n in ("a.wav", "b.wav")}


def test_a_second_run_with_nothing_changed_touches_nothing(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    render.execute(job, _plan())
    before = _stamps(job)
    render.execute(job, _plan())
    assert _stamps(job) == before


def test_a_changed_input_re_runs_its_step_and_every_step_after_it(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    render.execute(job, _plan())
    before = _stamps(job)
    source = job.work / "in.wav"
    os.utime(source, ns=(source.stat().st_atime_ns, source.stat().st_mtime_ns + 5_000_000_000))
    render.execute(job, _plan())
    after = _stamps(job)
    assert after["a.wav"] != before["a.wav"] and after["b.wav"] != before["b.wav"]


def test_a_changed_setting_re_runs_the_step(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    render.execute(job, _plan())
    before = _stamps(job)
    render.execute(job, _plan(target=-20))
    assert _stamps(job)["a.wav"] != before["a.wav"]


def test_a_missing_output_is_made_again(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    render.execute(job, _plan())
    (job.work / "b.wav").unlink()
    render.execute(job, _plan())
    assert (job.work / "b.wav").exists()


def test_a_forced_run_ignores_what_it_remembers(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    render.execute(job, _plan())
    before = _stamps(job)
    render.execute(job, _plan(), cache=False)
    assert _stamps(job)["a.wav"] != before["a.wav"]


def test_a_damaged_memory_is_treated_as_no_memory(tmp_path):
    (tmp_path / rendercache.CACHE_FILE).write_text("{not json")
    assert rendercache.load(tmp_path) == {}


def test_a_step_with_no_declared_output_always_runs(tmp_path):
    done = {"0": "k"}
    assert not rendercache.unchanged(tmp_path, done, 0, "k", {"cues": []})


# ---- clean: the picture chain's intermediates go, everything else stays --------------------------


def _rendered(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path)
    names = (
        "beats/b1.video.mp4",  # a paid asset
        "seg/00.mp4",
        "picture.mp4",
        "picture.ov.mp4",
        "music.stem.wav",  # a dub reuses it
        "final.mp4",
    )
    for name in names:
        path = job.work / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * 10)
    plan = {
        "steps": [
            {"op": "scale", "args": {"input": "beats/b1.video.mp4", "out": "seg/00.mp4"}},
            {"op": "concat", "args": {"inputs": ["seg/00.mp4"], "out": "picture.mp4"}},
            {"op": "overlay_text", "args": {"input": "picture.mp4", "out": "picture.ov.mp4"}},
            {"op": "mix_audio", "args": {"music": "music.wav", "out": "music.stem.wav"}},
            {"op": "export", "args": {"video": "picture.ov.mp4", "out": "final.mp4"}},
        ]
    }
    return job, plan


def _left(job):
    return {p.relative_to(job.work).as_posix() for p in job.work.rglob("*") if p.is_file()}


def test_clean_removes_only_what_the_picture_chain_can_rebuild(tmp_path, monkeypatch):
    job, plan = _rendered(tmp_path, monkeypatch)
    files, freed = rendercache.clean(job.work, plan)
    assert freed == 30 and len(files) == 3
    assert _left(job) == {"beats/b1.video.mp4", "music.stem.wav", "final.mp4"}
    assert not (job.work / "seg").exists()


def test_a_dry_run_clean_deletes_nothing(tmp_path, monkeypatch):
    job, plan = _rendered(tmp_path, monkeypatch)
    before = _left(job)
    files, freed = rendercache.clean(job.work, plan, dry_run=True)
    assert freed == 30 and len(files) == 3
    assert _left(job) == before


def test_clean_refuses_a_plan_that_names_a_file_outside_the_job(tmp_path, monkeypatch):
    job, plan = _rendered(tmp_path, monkeypatch)
    outside = tmp_path / "keep.mp4"
    outside.write_bytes(b"x")
    plan["steps"].append({"op": "scale", "args": {"input": "x", "out": "../../keep.mp4"}})
    with pytest.raises(ContractError, match="escapes"):
        rendercache.clean(job.work, plan)
    assert outside.exists()
