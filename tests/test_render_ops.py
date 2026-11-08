"""What a model-written plan may ask of the renderer, and what the join and the export do."""

from __future__ import annotations

import pytest
from fakes import needs_ffmpeg

from kalainova import media
from kalainova.jobfs import ContractError
from kalainova.render import export, picture, spec


def _cut_args(**extra):
    return {
        "source": "a.mp4",
        "kind": "video",
        "in_sec": 0,
        "out_sec": 1,
        "fps": 24,
        "out": "b.mp4",
        **extra,
    }


def test_a_well_formed_step_comes_back_with_numbers_as_floats():
    args = spec.coerce("cut", _cut_args(), 0)
    assert args["in_sec"] == 0.0 and isinstance(args["in_sec"], float)


def test_an_argument_the_step_does_not_take_is_refused():
    with pytest.raises(ContractError, match=r"unknown args \['shell'\]"):
        spec.coerce("cut", _cut_args(shell="rm -rf /"), 3)


def test_a_missing_argument_is_named():
    args = _cut_args()
    del args["source"]
    with pytest.raises(ContractError, match=r"step 4 \(cut\): missing source"):
        spec.coerce("cut", args, 4)


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"in_sec": "soon"}, "in_sec"),
        ({"in_sec": float("inf")}, "in_sec"),
        ({"in_sec": True}, "in_sec"),
        ({"source": "-filter_complex"}, "source"),
        ({"source": ""}, "source"),
        ({"kind": "hologram"}, "kind"),
    ],
)
def test_a_value_of_the_wrong_kind_is_refused_by_name(change, fragment):
    with pytest.raises(ContractError, match=fragment):
        spec.coerce("cut", _cut_args(**change), 0)


@pytest.mark.parametrize(
    "box",
    [
        [0, 0, 0, 1],
        [0, 0, 1, 0],
        [-0.1, 0, 1, 1],
        [0, -0.1, 1, 1],
        [0.5, 0, 0.6, 1],
        [0, 0.5, 1, 0.6],
        [0, 0, 1],
        ["a", 0, 1, 1],
        "x",
    ],
)
def test_a_picture_box_has_to_sit_inside_the_frame(box):
    assert not spec.is_box(box)


@pytest.mark.parametrize("box", [[0, 0, 1, 1], [0.5, 0, 0.5, 1], [0, 0.5, 1, 0.5]])
def test_a_box_that_reaches_the_edge_of_the_frame_is_inside_it(box):
    assert spec.is_box(box)


def _scale_args(**extra):
    return {
        "input": "a.mp4",
        "out": "b.mp4",
        "width": 1920,
        "height": 1080,
        "fps": 24,
        "duration_sec": 1,
        **extra,
    }


def test_a_scale_refuses_a_box_outside_the_frame():
    with pytest.raises(ContractError, match="picture_box"):
        spec.coerce("scale", _scale_args(picture_box=[0, 0, 2, 2]), 0)


@pytest.mark.parametrize("width", [True, 0, -1, 8193, 1.5, "4"])
def test_a_size_has_to_be_a_whole_number_a_frame_can_hold(width):
    with pytest.raises(ContractError, match="width"):
        spec.coerce("scale", _scale_args(width=width), 0)


@pytest.mark.parametrize("width", [1, 8192])
def test_the_smallest_and_largest_sizes_a_frame_can_hold_are_allowed(width):
    assert spec.coerce("scale", _scale_args(width=width), 0)["width"] == width


def test_ducking_is_yes_or_no():
    args = {"out": "m.wav", "duration_sec": 1.0, "duck": "yes"}
    with pytest.raises(ContractError, match="duck"):
        spec.coerce("mix_audio", args, 0)
    assert spec.coerce("mix_audio", {**args, "duck": False}, 0)["duck"] is False


@pytest.mark.parametrize("inputs", ["a.mp4", ["-x"], ["a.mp4", ""]])
def test_a_join_refuses_anything_but_a_list_of_plain_paths(inputs):
    with pytest.raises(ContractError, match="inputs"):
        spec.coerce("concat", {"inputs": inputs, "out": "o.mp4", "fps": 24}, 0)


def test_a_join_refuses_a_sound_that_could_be_read_as_a_flag():
    args = {"inputs": ["a.mp4"], "out": "o.mp4", "fps": 24, "audio_inputs": ["-x"]}
    with pytest.raises(ContractError, match="malformed audio input"):
        spec.coerce("concat", args, 0)


@pytest.mark.parametrize("speed", [0.25, 4.0])
def test_a_speed_at_the_edge_of_what_is_allowed_passes(speed):
    assert spec.coerce("cut", _cut_args(speed=speed), 0)["speed"] == speed


def test_a_speed_outside_what_ffmpeg_can_hold_is_refused():
    with pytest.raises(ContractError, match="speed out of range"):
        spec.coerce("cut", _cut_args(speed=9.0), 0)


def test_a_malformed_sound_entry_is_refused():
    args = {"out": "m.wav", "duration_sec": 1.0, "sfx": [{"path": "-x", "start_sec": 0}]}
    with pytest.raises(ContractError, match="malformed sfx entry"):
        spec.coerce("mix_audio", args, 1)


def test_a_path_cannot_leave_the_work_folder(tmp_path):
    assert spec.safe_path(tmp_path, "seg/a.mp4") == (tmp_path / "seg" / "a.mp4").resolve()
    with pytest.raises(ContractError, match="escapes"):
        spec.safe_path(tmp_path, "../../etc/passwd")


def _clip(path, seconds=1.0):
    media.run(
        ["-f", "lavfi", "-i", f"testsrc2=s=160x90:d={seconds}:r=24", "-pix_fmt", "yuv420p",
         str(path)]
    )  # fmt: skip


def _tone(path, seconds=1.0):
    media.run(["-f", "lavfi", "-i", f"sine=f=220:d={seconds}:r=48000", "-ac", "2", str(path)])


def _join_args(**extra):
    return {
        "inputs": ["a.mp4", "b.mp4"],
        "out": "joined.mp4",
        "fps": 24.0,
        "durations": [1.0, 1.0],
        "audio_inputs": ["a.wav", "b.wav"],
        "audio_out": "joined.wav",
        **extra,
    }


@pytest.fixture
def two_takes(tmp_path):
    for name in ("a", "b"):
        _clip(tmp_path / f"{name}.mp4")
        _tone(tmp_path / f"{name}.wav")
    return tmp_path


@needs_ffmpeg
def test_a_straight_cut_adds_the_lengths_up(two_takes):
    picture.op_concat(two_takes, _join_args(transition="cut"))
    assert media.duration(two_takes / "joined.mp4") == pytest.approx(2.0, abs=0.1)
    assert media.duration(two_takes / "joined.wav") == pytest.approx(2.0, abs=0.1)


@needs_ffmpeg
def test_a_dissolve_takes_its_overlap_from_both_picture_and_sound(two_takes):
    picture.op_concat(two_takes, _join_args(transition="dissolve", xfade_sec=0.4))
    assert media.duration(two_takes / "joined.mp4") == pytest.approx(1.6, abs=0.1)
    assert media.duration(two_takes / "joined.wav") == pytest.approx(1.6, abs=0.1)


@needs_ffmpeg
def test_a_join_with_no_sound_writes_no_sound(two_takes):
    picture.op_concat(two_takes, _join_args(audio_inputs=[], audio_out=None, transition="cut"))
    assert (two_takes / "joined.mp4").exists() and not (two_takes / "joined.wav").exists()


def _lossless(path):
    media.run(
        ["-f", "lavfi", "-i", "testsrc2=s=160x90:d=2:r=24", *media.MASTER_ARGS, str(path)]
    )  # fmt: skip


@needs_ffmpeg
def test_an_export_writes_each_file_it_is_asked_for_and_no_other(tmp_path):
    _lossless(tmp_path / "picture.mp4")
    _tone(tmp_path / "mix.wav", 2.0)
    export.op_export(
        tmp_path,
        {
            "video": "picture.mp4",
            "audio": "mix.wav",
            "out": "final.mp4",
            "thumbnail": "thumb.jpg",
            "audio_only": "final.m4a",
            "duration_sec": 2.0,
            "fps": 24.0,
        },
    )
    assert (tmp_path / "thumb.jpg").exists() and (tmp_path / "final.m4a").exists()
    assert media.summarize(tmp_path / "final.mp4").get("sample_rate_hz")


@needs_ffmpeg
def test_a_picture_with_no_sound_exports_with_no_sound_and_no_audio_file(tmp_path):
    _lossless(tmp_path / "picture.mp4")
    export.op_export(
        tmp_path,
        {
            "video": "picture.mp4",
            "audio": None,
            "out": "final.mp4",
            "audio_only": "final.m4a",
            "duration_sec": 2.0,
            "fps": 24.0,
        },
    )
    assert not media.summarize(tmp_path / "final.mp4").get("sample_rate_hz")
    assert not (tmp_path / "final.m4a").exists()
