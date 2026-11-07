"""What leaves the building: the delivery master, its caption files, and where type lands."""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET

import numpy as np
import pytest

from kalainova import assets, bar, captions, config, edit, media, render
from kalainova.jobfs import Job

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def _film_job(tmp_path, monkeypatch, profile="film-hd"):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    for key in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY"):
        monkeypatch.delenv(key, raising=False)
    folder = tmp_path / "jobs" / "film"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "film",
                "strategy": "generated",
                "media": ["video", "audio"],
                "rights": "owned",
                "distribution_identity": "test",
                "status": "draft",
                "skip_funded": True,
                "cost_cap": 0,
                "profile": profile,
                "brief": {"subject": "test", "duration_sec": 6},
            }
        )
    )
    (folder / "script_packet.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "film",
                "beats": [
                    {
                        "id": "b1",
                        "role": "hook",
                        "text": "A first line of speech.",
                        "on_screen": "Title",
                    },
                    {"id": "b2", "role": "payoff", "text": "And a second line follows it."},
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


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_a_film_job_delivers_a_master_that_meets_the_spec(tmp_path, monkeypatch):
    job = _film_job(tmp_path, monkeypatch)
    master = job.work / "final.master.mov"
    report = bar.measure_master(master, target_fps=24.0)
    bad = [r for r in report if not r["ok"]]
    assert not bad, bad


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_film_master_begins_and_ends_on_black(tmp_path, monkeypatch):
    job = _film_job(tmp_path, monkeypatch)
    master = job.work / "final.master.mov"
    frames = media.decode_gray(master, width=192)
    assert frames[0].mean() < 20 and frames[-1].mean() < 20
    assert frames[len(frames) // 2].mean() > frames[0].mean()


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_a_film_opens_on_picture_and_music_and_holds_after_the_last_word(tmp_path, monkeypatch):
    job = _film_job(tmp_path, monkeypatch)
    prof = config.profile("film-hd")
    em = json.loads(job.path("edit_manifest").read_text())
    cues = em["closed_captions"]
    assert em["cuts"][0]["start_sec"] == 0  # the picture is there from the first frame
    assert cues[0]["start_sec"] >= prof["open_sec"]
    assert media.duration(job.work / "final.master.mov") - cues[-1]["end_sec"] >= prof["close_sec"]
    voice, _, sr = media.decode_stereo(job.work / "voice.wav")
    assert abs(voice[: int(sr * (prof["open_sec"] - 0.2))]).max() < 0.001
    assert abs(voice[int(sr * prof["open_sec"]) : int(sr * (prof["open_sec"] + 2))]).max() > 0.01


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_new_assets_are_never_cut_with_the_old_edit(tmp_path, monkeypatch):
    job = _film_job(tmp_path, monkeypatch)
    first = job.read("edit_manifest")
    am = job.read("asset_manifest")
    am["timeline"][-1]["end_sec"] += 5.0
    am["duration_sec"] += 5.0
    job.write("asset_manifest", am)
    rebuilt = edit.run(job)
    assert rebuilt["cuts"][-1]["out_sec"] > first["cuts"][-1]["out_sec"]
    assert job.read("edit_manifest") == rebuilt


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_the_edit_is_kept_while_its_assets_have_not_changed(tmp_path, monkeypatch):
    job = _film_job(tmp_path, monkeypatch)
    em = job.read("edit_manifest")
    em["fade_out_sec"] = 2.5  # a hand change, which a re-run must not undo
    job.write("edit_manifest", em)
    assert edit.run(job)["fade_out_sec"] == 2.5


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_a_master_with_no_sound_misses_the_audio_reading(tmp_path):
    silent = tmp_path / "silent.mov"
    media.run(["-f", "lavfi", "-i", "testsrc2=s=64x64:d=1:r=24", "-c:v", "prores_ks", str(silent)])
    readings = {r["id"]: r for r in bar.measure_master(silent, target_fps=24.0)}
    assert not readings["master.audio"]["ok"]
    assert "master.lkfs" not in readings


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_the_bar_command_reads_a_job_and_a_loose_file(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace

    from kalainova import __main__ as cli

    job = _film_job(tmp_path, monkeypatch)
    monkeypatch.setattr(cli, "open_job", lambda name: job)
    assert cli._bar(SimpleNamespace(target="film")) in (0, 2)
    whole_job = capsys.readouterr().out
    assert "master.codec" in whole_job and "studio bar" in whole_job

    assert cli._bar(SimpleNamespace(target=str(job.work / "final.mp4"))) in (0, 2)
    one_file = capsys.readouterr().out
    assert "picture.banding" in one_file and "master.codec" not in one_file


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_film_keeps_captions_out_of_the_picture_and_in_files(tmp_path, monkeypatch):
    job = _film_job(tmp_path, monkeypatch)
    assert not (job.work / "picture.cap.mp4").exists()
    for name in ("captions.srt", "captions.vtt", "captions.itt"):
        assert (job.work / name).stat().st_size > 0
    root = ET.parse(job.work / "captions.itt").getroot()
    assert root.tag.endswith("tt")
    assert "second line" in ET.tostring(root, encoding="unicode")


def test_timed_text_files_carry_the_cues_in_order():
    cues = [
        {"start_sec": 0.5, "end_sec": 1.5, "text": "One & two"},
        {"start_sec": 2.0, "end_sec": 3.25, "text": "Three"},
    ]
    files = captions.sidecars(cues, fps=24.0)
    assert "00:00:00,500 --> 00:00:01,500" in files["captions.srt"]
    assert files["captions.vtt"].startswith("WEBVTT")
    assert "00:00:02.000 --> 00:00:03.250" in files["captions.vtt"]
    assert "One &amp; two" in files["captions.itt"]
    ET.fromstring(files["captions.itt"])


def _ink_bounds(ass_text, w, h, tmp_path):
    (tmp_path / "t.ass").write_text(ass_text)
    out = tmp_path / "t.png"
    media.run(
        [
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={w}x{h}:d=2",
            "-vf",
            f"subtitles=t.ass:fontsdir={media.filter_path(captions.FONTS)}",
            "-ss",
            "1.0",
            "-frames:v",
            "1",
            out.name,
        ],
        cwd=tmp_path,
    )
    from PIL import Image

    ink = np.asarray(Image.open(out).convert("L")) > 120
    ys, xs = np.nonzero(ink)
    return xs.min() / w, xs.max() / w, ys.min() / h, ys.max() / h


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
@pytest.mark.parametrize("size", [(1080, 1920), (1920, 1080), (1080, 1080), (3840, 2160)])
def test_type_stays_inside_the_safe_area_at_every_shape(tmp_path, size):
    w, h = size
    safe = captions.safe_area(w, h)
    text = "A long headline that has to wrap neatly on every single shape"
    words = text.split()
    card = {
        "start_sec": 0.0,
        "end_sec": 2.0,
        "text": text,
        "words": [
            {"text": t, "start_sec": i * 0.2, "end_sec": (i + 1) * 0.2} for i, t in enumerate(words)
        ],
    }
    for ass_text in (
        captions.studio_captions([card], w, h)[0],
        captions.studio_titles([{"text": text, "start_sec": 0.0, "end_sec": 2.0}], w, h),
    ):
        x0, x1, y0, y1 = _ink_bounds(ass_text, w, h, tmp_path)
        assert x0 >= safe["side"] - 0.005 and x1 <= 1 - safe["side"] + 0.005
        assert y0 >= safe["top"] - 0.005 and y1 <= 1 - safe["bottom"] + 0.005


def test_a_bright_background_gets_a_scrim_that_reaches_readable_contrast():
    for level in (0.1, 0.4, 0.7, 1.0):
        alpha = captions.scrim_alpha(level)
        assert captions.contrast_after(level, alpha) >= 4.5
    assert captions.scrim_alpha(0.05) == 0.0


def test_a_title_goes_where_the_picture_is_calm():
    frame = np.random.default_rng(1).integers(0, 255, (160, 90)).astype(np.float64)
    frame[10:40] = 30.0  # the only quiet band sits near the top
    assert captions.calmest_band(frame, [0.16, 0.5, 0.8]) == 0.16
