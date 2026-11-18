"""A shot sung in one call on fal: what each kind of model is sent, and what it is billed.

A model that takes one picture gets the still and the line. One that takes several gets the still
first, then the kit, with each picture and the line named in the prompt. One that makes set lengths
is asked for the next one up. Field names come from sing_models, so a new model is a config row.
"""

from __future__ import annotations

import numpy as np
import pytest
from fakes import Wire, context, needs_ffmpeg
from test_music_video import SR, _write

from kalainova import config
from kalainova.providers import fal
from kalainova.providers.contract import Billable, Reference, SingRequest

ONE = "vendor/one-picture"
MANY = "vendor/pictures-and-audio"
SET = "vendor/set-lengths"

TABLE = {
    "models": {"fal": {"sing": ONE}},
    "prices": {"fal": {"sing": {"per_sec": 0.2}, ONE: {"per_sec": 0.16}}},
    "sing_models": {
        "fal": {
            ONE: {"image_param": "image_url", "audio_param": "audio_url", "extra": {"res": "4k"}},
            MANY: {
                "images_param": "image_urls",
                "image_tag": "@Image{n}",
                "max_images": 2,
                "audios_param": "audio_urls",
                "audio_tag": "@Audio1",
                "aspect_param": "aspect_ratio",
                "durations": "4,5,6",
            },
            SET: {
                "image_param": "image_url",
                "audio_param": "audio_url",
                "durations": "5,10,15",
                "takes_seed": True,
            },
        }
    },
}

pytestmark = needs_ffmpeg


@pytest.fixture
def wire(monkeypatch):
    monkeypatch.setattr(config, "studio", lambda: TABLE)
    found = Wire(default={"video": {"url": "u"}}, files={"u": b"clip"})
    monkeypatch.setattr(fal.Fal, "transport", found)
    return found


def _sing(tmp_path, model: str, seconds: float = 4.2, refs: int = 2):
    line = _write(tmp_path / "s01.voice.wav", np.zeros(int(seconds * SR), np.float32))
    kit = tuple(
        Reference(path=tmp_path / f"kit{n}.png", sha256=str(n), label=f"the lead, angle {n}")
        for n in range(refs)
    )
    asked = SingRequest(
        prompt="front, waist up: she sings the hook",
        still=tmp_path / "s01.still.png",
        audio=line,
        dst=tmp_path / "s01.mp4",
        aspect="9:16",
        references=kit,
        seed=7,
    )
    return fal.Fal().sing(asked, context(model=model))


def test_a_one_picture_model_gets_the_still_and_the_line_and_runs_as_long_as_it(wire, tmp_path):
    made = _sing(tmp_path, ONE)
    sent = wire.sent[-1]["payload"]
    assert sent["image_url"] == "up:s01.still.png" and sent["audio_url"] == "up:s01.voice.wav"
    assert sent["prompt"] == "front, waist up: she sings the hook" and sent["res"] == "4k"
    assert "duration" not in sent and "seed" not in sent, "it follows the line, and takes no seed"
    assert made.cost == pytest.approx(5 * 0.16), "billed by the whole second, at its own row"
    assert made.recorded()["start_frame_sent"] is True


def test_a_many_picture_model_gets_the_still_first_then_the_kit_with_the_line_named(wire, tmp_path):
    made = _sing(tmp_path, MANY, refs=3)
    sent = wire.sent[-1]["payload"]
    assert sent["image_urls"] == ["up:s01.still.png", "up:kit0.png"], "no more than it takes"
    assert sent["audio_urls"] == ["up:s01.voice.wav"]
    assert "@Image1 is the first frame" in sent["prompt"]
    assert "@Image2 is the lead, angle 0" in sent["prompt"]
    assert "@Audio1 is the vocal she sings" in sent["prompt"]
    assert sent["duration"] == "5" and sent["aspect_ratio"] == "9:16"
    assert made.cost == pytest.approx(5 * 0.2), "no row of its own: the capability's rate"


def test_a_set_length_model_is_asked_for_the_next_length_up_and_seeded(wire, tmp_path):
    made = _sing(tmp_path, SET)
    sent = wire.sent[-1]["payload"]
    assert sent["duration"] == "5" and sent["seed"] == 7
    assert made.seed == 7


def test_a_sung_shot_is_quoted_at_the_length_it_is_billed(monkeypatch):
    monkeypatch.setattr(config, "studio", lambda: TABLE)
    asked = Billable(capability="sing", duration=6.2, image=True)
    assert fal.Fal().billed_seconds(asked) == 7.0
    assert fal.Fal().billed_seconds(asked, SET) == 10.0
    assert fal.Fal().estimate(asked) == pytest.approx(7 * 0.16)
    assert fal.Fal().models("sing") == [ONE, MANY, SET]


def test_a_model_not_listed_to_sing_is_refused_before_anything_is_sent(wire, tmp_path):
    with pytest.raises(ValueError, match="not listed under sing_models"):
        _sing(tmp_path, "vendor/unknown")
    assert not wire.sent
