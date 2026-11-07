"""Change one input, re-run what depends on it, and leave the rest alone."""

from __future__ import annotations

import os

from fakes import make_job, needs_ffmpeg

from kalainova import media, render
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
