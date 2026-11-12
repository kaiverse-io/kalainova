"""Clips: where one starts, which crop adapter placed it, and the cards around it."""

from __future__ import annotations

import pytest
from fakes import cover_source, make_job, needs_ffmpeg
from test_speech_clips import _scored, _transcript_words, _words

from kalainova import config, media, render
from kalainova.editor import clips
from kalainova.jobfs import ContractError


def test_a_clip_that_starts_mid_sentence_moves_back_to_where_the_sentence_starts():
    words = _words(
        (0.0, 0.4, "Before."),
        (1.0, 1.4, "This"),
        (1.5, 1.9, "is"),
        (2.0, 2.4, "it."),
        (3.0, 3.4, "Next."),
    )
    tidied = clips.tidy({"start_sec": 1.5, "end_sec": 3.4}, words)
    assert tidied["start_sec"] == 1.0 and tidied["end_sec"] == 3.4


def test_a_start_that_cannot_move_back_without_running_too_long_moves_forward():
    words = _words(
        (0.0, 0.4, "Long"), (1.0, 1.4, "one"), (30.0, 30.4, "ends."),
        (70.0, 70.4, "New"), (88.0, 89.0, "done."),
    )  # fmt: skip
    assert clips.tidy({"start_sec": 1.0, "end_sec": 89.0}, words)["start_sec"] == 70.0


def test_opening_fillers_come_off_the_front_and_the_clip_never_empties():
    words = _words(
        (0.0, 0.3, "So,"), (0.4, 0.6, "um,"), (0.7, 0.9, "you"), (1.0, 1.2, "know,"),
        (1.3, 1.8, "this"), (1.9, 2.4, "works."),
    )  # fmt: skip
    assert clips.tidy({"start_sec": 0.0, "end_sec": 2.4}, words)["start_sec"] == 1.3
    only = _words((0.0, 0.3, "So"), (0.4, 0.8, "well."))
    assert clips._drop_opening_fillers(only) == only


def test_the_fallback_picks_do_not_open_on_a_filler():
    words = _transcript_words()
    words[0]["text"] = "So"
    words[1]["text"] = "um,"
    assert clips.densest(words, 1)[0]["start_sec"] >= 1.0


def test_an_unknown_crop_adapter_is_refused(tmp_path, studio):
    job = make_job(tmp_path)
    with pytest.raises(ContractError, match="crop must be one of"):
        clips.choose_crop(job, job.work / "x.mp4", {"start_sec": 0, "end_sec": 1}, "eyes", None)


def test_the_face_adapter_runs_a_configured_command_and_falls_back_to_motion(
    tmp_path, studio, monkeypatch
):
    job = make_job(tmp_path)
    source = _scored(job, [(0, 10, 0.2)])
    clip = {"start_sec": 0.0, "end_sec": 5.0}
    assert clips.choose_crop(job, source, clip, "face", None) == (0.2, "motion_centre")
    tool = tmp_path / "face.py"
    tool.write_text("import json\nprint(json.dumps({'x': 0.61}))\n")
    command = ["python3", str(tool), "{source}", "{start}", "{end}"]
    monkeypatch.setitem(config.studio(), "clips", {"face_command": command})
    assert clips.choose_crop(job, source, clip, "face", None) == (0.61, "face")
    assert clips.choose_crop(job, source, clip, "motion", None) == (0.2, "motion_centre")
    assert clips.choose_crop(job, source, clip, "face", 0.9) == (0.9, "given")
    tool.write_text("print('no face')\n")
    assert clips.choose_crop(job, source, clip, "face", None) == (0.2, "motion_centre")


@needs_ffmpeg
def test_a_clip_can_open_and_close_on_a_drawn_card(tmp_path, monkeypatch, studio):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    job = cover_source(make_job(tmp_path))
    source = job.work / "talk.mp4"
    media.run(
        ["-f", "lavfi", "-i", "testsrc2=s=640x360:d=30:r=24", "-f", "lavfi", "-i",
         "sine=f=220:d=30:r=48000", "-pix_fmt", "yuv420p", "-shortest", str(source)]
    )  # fmt: skip
    studio.heard = _transcript_words()
    clip = {"start_sec": 0.0, "end_sec": 20.0, "title": "The turn"}
    child = clips.open_job(
        job, source, clip, "p1-clip-card", hook_text="The turn", close_text="Follow for more"
    )
    em = child.read("edit_manifest")
    assert [em["cuts"][0]["source"], em["cuts"][-1]["source"]] == ["hook-card", "close-card"]
    assert em["cuts"][0]["role"] == "hook" and em["cuts"][1]["role"] == "body"
    assert em["captions"][0]["start_sec"] >= em["cuts"][0]["out_sec"], "words follow the card"
    assert (child.folder / "graphics" / "hook-card" / "index.html").exists()
    assets = {a["id"]: a for a in child.read("asset_manifest")["assets"]}
    assert assets["hook-card"]["synthetic"] is False and assets["close-card"]["kind"] == "video"
    assert em["duration_sec"] == pytest.approx(
        sum(c["out_sec"] - c["in_sec"] for c in em["cuts"]), abs=0.01
    )
    render.compile_plan(child)
    assert media.summarize(render.execute(child))["height"] == 1920
