"""The picture path: the camera, the looks, and what a full render delivers."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
from PIL import Image

from kalainova import assets, bar, edit, look, media, motion, render
from kalainova.jobfs import ContractError, Job

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def test_a_push_in_moves_at_one_steady_rate_with_no_ease():
    zooms = [motion.camera("push_in", i / 30, 4.0).zoom for i in range(120)]
    ratios = np.diff(np.log(zooms))
    assert zooms[0] < zooms[-1]
    assert ratios.max() - ratios.min() < 1e-9


def test_camera_speed_does_not_depend_on_shot_length():
    short = motion.camera("push_in", 1.0, 2.0).zoom / motion.camera("push_in", 0.0, 2.0).zoom
    long = motion.camera("push_in", 1.0, 8.0).zoom / motion.camera("push_in", 0.0, 8.0).zoom
    assert short == pytest.approx(long)


def test_a_pan_stays_inside_the_picture():
    for t in (0.0, 2.0, 4.0):
        cam = motion.camera("pan_right", t, 4.0, crop_x=0.9)
        half = 0.5 / cam.zoom
        assert half <= cam.cx <= 1 - half


def test_sampled_motion_is_even_frame_to_frame():
    rng = np.random.default_rng(1)
    coarse = rng.uniform(0, 1, (60, 40, 3)).astype(np.float32)
    src = np.asarray(
        Image.fromarray((coarse * 255).astype(np.uint8)).resize((400, 600), Image.BICUBIC),
        dtype=np.float32,
    )
    frames = [
        motion.frame(src / 255, motion.camera("push_in", i / 30, 2.0), 200, 300).mean(axis=2)
        for i in range(40)
    ]
    diffs = np.abs(np.diff(np.array(frames), axis=0)).mean(axis=(1, 2))
    assert bar.stutter_score(diffs) < 0.1


def test_each_look_is_monotonic_and_keeps_shadow_detail():
    ramp = np.linspace(0, 1, 256, dtype=np.float32)[:, None].repeat(3, axis=1)
    for name in look.LOOKS:
        out = look.apply(name, ramp).mean(axis=1)
        assert (np.diff(out) >= -1e-6).all(), name
        assert out[6] > out[0], name  # near-black is not crushed flat


def test_bw_has_no_colour_and_skin_stays_close_under_a_strong_look():
    rgb = np.array([[0.72, 0.52, 0.42]], np.float32)
    grey = look.apply("bw", rgb)
    assert grey.max() - grey.min() < 1e-5
    blue = np.array([[0.3, 0.42, 0.72]], np.float32)
    skin_shift = np.abs(look.apply("vivid", rgb) - rgb).max()
    blue_shift = np.abs(look.apply("vivid", blue) - blue).max()
    assert skin_shift < blue_shift


def test_a_cube_file_has_every_grid_point():
    text = look.cube_text("warm", gamma=1.1, size=5)
    rows = [line for line in text.splitlines() if line and line[0].isdigit()]
    assert "LUT_3D_SIZE 5" in text and len(rows) == 125


def test_a_fallback_font_is_refused():
    log = "fontselect: (No Such Font, 400, 0) -> /System/Library/Fonts/Helvetica.ttc, -1, Helvetica"
    with pytest.raises(ContractError, match="No Such Font"):
        render.refuse_fallback_fonts(log)
    render.refuse_fallback_fonts(
        "fontselect: (Inter Display SemiBold, 400, 0) -> InterDisplay-SemiBold, 0, Inter"
    )


def _local_job(tmp_path, monkeypatch, **edit_opts):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    for key in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY"):
        monkeypatch.delenv(key, raising=False)
    folder = tmp_path / "jobs" / "pic"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "pic",
                "strategy": "generated",
                "media": ["video", "audio"],
                "rights": "owned",
                "distribution_identity": "test",
                "status": "draft",
                "skip_funded": True,
                "cost_cap": 0,
                "brief": {"subject": "test", "duration_sec": 6},
                "edit": edit_opts,
            }
        )
    )
    (folder / "script_packet.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "pic",
                "beats": [
                    {"id": "b1", "role": "hook", "text": "First line here.", "on_screen": "Open"},
                    {
                        "id": "b2",
                        "role": "body",
                        "text": "A second thought lands.",
                        "on_screen": "Two",
                    },
                    {"id": "b3", "role": "payoff", "text": "And it ends well.", "on_screen": "End"},
                ],
            }
        )
    )
    return Job(folder)


def _render(job):
    assets.run(job)
    edit.run(job)
    render.compile_plan(job)
    return render.execute(job)


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_a_render_meets_the_picture_bar(tmp_path, monkeypatch):
    job = _local_job(tmp_path, monkeypatch)
    final = _render(job)
    readings = {r["id"]: r for r in bar.measure(final)["readings"]}
    for rid in (
        "delivery.color_tags",
        "delivery.pixel_format",
        "picture.banding",
        "picture.stutter",
    ):
        assert readings[rid]["ok"], readings[rid]


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_every_intermediate_is_lossless_ten_bit(tmp_path, monkeypatch):
    job = _local_job(tmp_path, monkeypatch)
    _render(job)
    video = media.stream_info(job.work / "seg" / "00.mp4", "video")
    assert video["pix_fmt"] == "yuv444p10le"
    assert video["color_space"] == "bt709"


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_a_studio_piece_makes_no_sound_it_will_not_use(tmp_path, monkeypatch):
    job = _local_job(tmp_path, monkeypatch)
    manifest = assets.run(job)
    assert "whoosh" not in {a["id"] for a in manifest["assets"]}


def test_a_clip_long_enough_is_cut_to_its_shot_with_no_frozen_frames(tmp_path, monkeypatch):
    job = _local_job(tmp_path, monkeypatch)
    timeline = [
        {"beat_id": "b1", "start_sec": 0.0, "end_sec": 3.0},
        {"beat_id": "b2", "start_sec": 3.0, "end_sec": 6.0},
        {"beat_id": "b3", "start_sec": 6.0, "end_sec": 9.0},
    ]
    clips = [
        {
            "id": f"{b}.video",
            "kind": "video",
            "role": "visual",
            "beat_id": b,
            "path": f"beats/{b}.mp4",
            "duration_sec": 5.0,
            "rights": "owned",
            "synthetic": True,
            "provider": "test",
        }
        for b in ("b1", "b2", "b3")
    ]
    job.write(
        "asset_manifest",
        {
            "schema_version": "0.1",
            "job_id": "pic",
            "assets": clips,
            "timeline": timeline,
            "duration_sec": 9.0,
        },
    )
    cuts = edit.run(job)["cuts"]
    ends = [c["start_sec"] for c in cuts[1:]] + [9.0]
    for cut, end in zip(cuts, ends, strict=True):
        assert "hold_last_frame" not in cut
        assert cut["out_sec"] - cut["in_sec"] >= end - cut["start_sec"]
