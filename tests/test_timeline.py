"""Seeing a piece: a sheet of shots, a filmstrip, and a check at every cut."""

from __future__ import annotations

import subprocess

import numpy as np
import pytest
from fakes import make_job, needs_ffmpeg
from PIL import Image

from kalainova import assets, edit, media, prompts, qa, qachecks, render, timeline

pytestmark = needs_ffmpeg


def _clip(path, size="320x180", seconds=2.0):
    media.run(
        ["-f", "lavfi", "-i", f"testsrc2=s={size}:d={seconds}:r=24", "-f", "lavfi", "-i",
         f"sine=f=220:d={seconds}:r=48000", "-pix_fmt", "yuv420p", "-shortest", str(path)]
    )  # fmt: skip
    return path


CUTS = [{"id": "cut-b1", "start_sec": 0.0}, {"id": "cut-b2", "start_sec": 1.0}]


@pytest.mark.parametrize(("size", "portrait"), [("320x180", False), ("180x320", True)])
def test_a_shot_sheet_keeps_the_pieces_real_shape(tmp_path, size, portrait):
    out = timeline.shot_sheet(_clip(tmp_path / "c.mp4", size), CUTS, 2.0, tmp_path / "s.jpg")
    sheet = Image.open(out)
    frame_width = (sheet.width - 4) // 2
    frame_height = sheet.height // 2 - 4
    assert (frame_height > frame_width) is portrait, "a frame is not squashed into another shape"


def test_a_shot_sheet_has_a_row_for_every_shot_with_two_frames_each(tmp_path):
    out = timeline.shot_sheet(_clip(tmp_path / "c.mp4"), CUTS, 2.0, tmp_path / "s.jpg")
    sheet = Image.open(out)
    assert sheet.width == timeline.SHEET_LANDSCAPE_WIDTH * 2 + 4
    assert sheet.height > sheet.width / 2


def test_a_very_long_piece_samples_shots_from_end_to_end():
    cuts = [{"id": f"cut-{n}", "start_sec": float(n)} for n in range(1000)]
    rows = timeline._spans(cuts, 1000.0)
    assert len(rows) == timeline.MOST_ROWS
    assert rows[0][1] == 0.0 and rows[-1][1] > 900


def test_a_sheet_of_an_audio_file_is_nothing_rather_than_a_crash(tmp_path):
    tone = tmp_path / "t.wav"
    media.run(["-f", "lavfi", "-i", "sine=f=220:d=1", str(tone)])
    assert timeline.shot_sheet(tone, CUTS, 1.0, tmp_path / "s.jpg") is None


def test_a_filmstrip_shows_frames_over_a_waveform_with_the_words_on_it(tmp_path):
    words = [{"start_sec": 0.5, "text": "hello"}, {"start_sec": 99.0, "text": "elsewhere"}]
    out = timeline.filmstrip(
        _clip(tmp_path / "c.mp4"), 0.0, 2.0, tmp_path / "f.jpg", frames=4, words=words
    )
    strip = Image.open(out)
    assert strip.width == timeline.FRAME_WIDTH * 4
    assert strip.height > timeline.WAVE_HEIGHT


def _with_step(path, *, at=1.0, step=0.9):
    """A tone that jumps in level at a cut, which is the click a viewer hears."""
    sr = 48000
    t = np.arange(int(2 * sr)) / sr
    x = 0.05 * np.sin(2 * np.pi * 220 * t)
    x[int(at * sr)] = step
    x[int(at * sr) + 1] = -step
    subprocess.run(
        [media.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", "testsrc2=s=160x90:d=2:r=24",
         "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-", "-pix_fmt", "yuv420p",
         "-c:a", "pcm_s16le", "-shortest", str(path)],
        input=x.astype(np.float32).tobytes(),
        check=True,
    )  # fmt: skip
    return path


def test_a_click_at_a_cut_is_flagged_and_a_clean_cut_is_not(tmp_path):
    clicky = _with_step(tmp_path / "bad.mov")
    report = timeline.cut_report(clicky, [{"start_sec": 0.0}, {"start_sec": 1.0}])
    assert report[0]["flagged"] and report[0]["click_ratio"] > timeline.CLICK_RATIO
    clean = _clip(tmp_path / "good.mp4")
    assert not timeline.cut_report(clean, [{"start_sec": 0.0}, {"start_sec": 1.0}])[0]["flagged"]


def test_the_start_of_a_piece_is_not_a_cut(tmp_path):
    assert timeline.cut_report(_clip(tmp_path / "c.mp4"), [{"start_sec": 0.0}]) == []


def test_a_flash_is_one_frame_far_from_both_its_neighbours(tmp_path, monkeypatch):
    levels = iter([100.0, 250.0, 100.0])
    monkeypatch.setattr(timeline.media, "gray_frame", lambda *a, **k: np.full((4, 4), next(levels)))
    assert timeline._flash(tmp_path / "x.mp4", 1.0, 24.0)
    steady = iter([100.0, 110.0, 120.0])
    monkeypatch.setattr(timeline.media, "gray_frame", lambda *a, **k: np.full((4, 4), next(steady)))
    assert not timeline._flash(tmp_path / "x.mp4", 1.0, 24.0)


# ---- what QA does with them -------------------------------------------------------------
def test_the_judges_rubric_is_told_the_real_shape_and_the_shots(tmp_path):
    text = prompts.load("qa_rubric").format(shape="landscape", script="[the shots]")
    assert "landscape" in text and "[the shots]" in text
    assert "short vertical" not in text


def test_a_judge_that_saw_a_problem_says_which_shot(tmp_path):
    checks = qachecks.judged_shots(
        {
            "shots": [
                {
                    "id": "b3",
                    "moved": True,
                    "geometry_ok": False,
                    "note": "the door opens the wrong way",
                }
            ]
        }
    )
    assert checks[0]["status"] == "warn" and "b3: the door" in checks[0]["detail"]


def test_a_judge_with_no_shot_notes_adds_nothing(tmp_path):
    assert qachecks.judged_shots({"verdict": "ship"}) == []


def test_a_finished_piece_is_checked_at_its_cuts_and_gets_a_real_sheet(tmp_path, studio):
    beats = [
        {
            "id": "b1",
            "role": "hook",
            "text": "One line.",
            "visual_kind": "video",
            "visual_cue": "Waves rolling",
        },
        {
            "id": "b2",
            "role": "payoff",
            "text": "Two lines.",
            "visual_kind": "video",
            "visual_cue": "Clouds drifting",
        },
    ]
    job = make_job(tmp_path, beats=beats)
    assets.run(job)
    edit.run(job)
    render.compile_plan(job)
    render.execute(job)
    report = qa.run(job)
    ids = {c["id"] for c in report["checks"]}
    assert "edit.cuts" in ids
    assert (job.work / report["artifacts"]["contact_sheet"]).exists()


# ---- rights -----------------------------------------------------------------------------
def _manifest(*assets_):
    return {"assets": [{"id": "a", "kind": "video", "path": "x", **a} for a in assets_]}


def test_a_model_nobody_has_read_the_terms_of_is_named():
    checks = qachecks.licence_checks(_manifest({"provider": "mac", "model": "some-new-model"}))
    assert checks[0]["id"] == "rights.model_licence" and "some-new-model" in checks[0]["detail"]


def test_what_a_licence_asks_of_whoever_releases_a_piece_is_surfaced():
    model = "mlx-community/MiniMax-Music3-8bit"
    checks = qachecks.licence_checks(_manifest({"provider": "mac", "model": model}))
    owed = next(c for c in checks if c["id"] == "rights.obligations")
    assert "MiniMax-Music3 prominently" in owed["detail"]


def test_a_voice_model_is_read_without_its_voice_name():
    model = "mlx-community/Kokoro-82M-bf16:am_michael"
    assert qachecks.licence_checks(_manifest({"provider": "mac", "model": model})) == []


def test_a_hosted_app_is_flagged_as_not_confirmed_for_commercial_use():
    checks = qachecks.licence_checks(_manifest({"provider": "spaces", "model": "someone/app"}))
    assert "rights.commercial_use" in {c["id"] for c in checks}


def test_what_a_person_or_the_engine_made_has_no_model_licence():
    made = [{"provider": p, "model": "m"} for p in ("operator", "kit", "chained", "clip", "track")]
    assert qachecks.licence_checks(_manifest(*made)) == []


def test_a_film_with_only_voice_and_music_is_told_so():
    prof = {"delivery": "mezzanine"}
    assert qachecks.sound_checks(prof, _manifest({"role": "voice"}))[0]["id"] == "sound.layers"
    assert qachecks.sound_checks(prof, _manifest({"role": "sfx"})) == []
    assert qachecks.sound_checks({}, _manifest({"role": "voice"})) == []


def test_a_film_built_on_lossy_audio_is_told_so():
    lossy = {"role": "sfx", "provenance": {"audio_format": "mp3_44100_128"}}
    checks = qachecks.sound_checks({"delivery": "mezzanine"}, _manifest(lossy))
    assert checks[0]["id"] == "sound.source_quality"
