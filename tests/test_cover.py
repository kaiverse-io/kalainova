"""The cover: a frame that is not black or blurred, a square cut that keeps the subject, and the
brief's choice winning."""

from __future__ import annotations

import numpy as np
import pytest
from fakes import needs_ffmpeg
from PIL import Image

from kalainova import media
from kalainova.jobfs import ContractError
from kalainova.render import cover, export


def _noise(seed: int, size=(90, 160)) -> np.ndarray:
    return np.random.default_rng(seed).integers(0, 255, size, dtype=np.uint8)


def _blur(gray: np.ndarray) -> np.ndarray:
    h, w = gray.shape
    return np.asarray(Image.fromarray(gray).resize((w // 10, h // 10)).resize((w, h)))


def test_a_blurred_frame_scores_below_a_sharp_one():
    sharp = _noise(1)
    assert cover.sharpness(sharp) > 10 * cover.sharpness(_blur(sharp))


def test_black_and_flat_frames_are_not_usable():
    assert not cover.usable(np.zeros((90, 160), np.uint8))
    assert not cover.usable(np.full((90, 160), 128, np.uint8))
    assert cover.usable(_noise(2))


def test_the_sharpest_usable_frame_inside_the_window_wins():
    black = np.zeros((90, 160), np.uint8)
    frames = np.stack([black, black, _blur(_noise(3)), _noise(4), _noise(5)])
    times = [0.0, 0.5, 1.0, 1.5, 2.0]
    got = cover.best_frame(frames, times, 0.5, 1.5)
    assert got is not None and got[0] == 1.5
    assert cover.best_frame(frames[:2], times[:2], 0.0, 1.0) is None


def test_the_square_crop_keeps_the_detailed_part_of_a_tall_frame(tmp_path):
    img = np.full((1600, 900), 90, np.uint8)
    img[1100:1500, 200:700] = _noise(6, (400, 500))  # the subject, low in the frame
    Image.fromarray(img).convert("RGB").save(tmp_path / "t.png")
    cover.write_square(tmp_path / "t.png", tmp_path / "s.png")
    out = np.asarray(Image.open(tmp_path / "s.png").convert("L"))
    assert out.shape == (900, 900)
    assert out[-400:, 200:700].std() > 40  # the whole noisy block is inside the square


def _clip(path, graph: str, seconds: float):
    media.run(
        ["-filter_complex", graph, "-map", "[v]", "-t", str(seconds), *media.MASTER_ARGS, str(path)]
    )


@needs_ffmpeg
def test_a_clip_that_opens_on_black_gets_a_later_frame(tmp_path):
    graph = (
        "color=black:s=160x90:d=2:r=24[a];testsrc2=s=160x90:d=3:r=24[b];[a][b]concat=n=2:v=1:a=0[v]"
    )
    _clip(tmp_path / "p.mp4", graph, 5)
    info = cover.write(tmp_path / "p.mp4", tmp_path / "t.jpg", None, duration=5.0)
    assert info["how"] == "sharpest" and info["at_sec"] >= 2.0


@needs_ffmpeg
def test_a_blurred_stretch_loses_to_a_sharp_one(tmp_path):
    graph = (
        "testsrc2=s=160x90:d=3:r=24,boxblur=8[a];testsrc2=s=160x90:d=3:r=24[b];"
        "[a][b]concat=n=2:v=1:a=0[v]"
    )
    _clip(tmp_path / "p.mp4", graph, 6)
    info = cover.write(tmp_path / "p.mp4", tmp_path / "t.jpg", None, duration=6.0)
    assert info["at_sec"] >= 3.0


@needs_ffmpeg
def test_the_brief_names_a_time_and_it_wins(tmp_path):
    _clip(tmp_path / "p.mp4", "testsrc2=s=160x90:d=4:r=24[v]", 4)
    info = cover.write(tmp_path / "p.mp4", tmp_path / "t.jpg", None, duration=4.0, at=0.2)
    assert info == {"how": "brief", "at_sec": 0.2, "warnings": []}


@needs_ffmpeg
def test_the_brief_names_a_file_and_it_wins_and_is_checked_for_release(tmp_path):
    _clip(tmp_path / "p.mp4", "testsrc2=s=160x90:d=2:r=24[v]", 2)
    Image.new("RGB", (600, 400), (10, 120, 200)).save(tmp_path / "mine.png")
    info = cover.write(
        tmp_path / "p.mp4", tmp_path / "t.jpg", tmp_path / "s.jpg", file=tmp_path / "mine.png"
    )
    assert info["how"] == "file" and any("square" in w for w in info["warnings"])  # type: ignore[attr-defined]
    assert Image.open(tmp_path / "t.jpg").size == (600, 400)
    assert Image.open(tmp_path / "s.jpg").size == (400, 400)


def test_a_missing_cover_file_is_refused(tmp_path):
    with pytest.raises(ContractError, match="not in the job's work folder"):
        cover.write(tmp_path / "p.mp4", tmp_path / "t.jpg", None, file=tmp_path / "none.png")


@needs_ffmpeg
def test_an_export_can_write_the_square_beside_the_cover(tmp_path):
    _clip(tmp_path / "p.mp4", "testsrc2=s=90x160:d=3:r=24[v]", 3)
    export.op_export(
        tmp_path,
        {
            "video": "p.mp4",
            "out": "final.mp4",
            "thumbnail": "thumb.jpg",
            "thumbnail_square": "thumb_square.jpg",
            "duration_sec": 3.0,
            "fps": 24.0,
        },
    )
    assert Image.open(tmp_path / "thumb_square.jpg").size == (90, 90)
