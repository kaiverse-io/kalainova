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
