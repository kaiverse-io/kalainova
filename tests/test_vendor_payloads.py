"""What each adapter sends, against the schemas the vendors publish. No network and no spend."""

from __future__ import annotations

from pathlib import Path

import pytest

from kalainova import config
from kalainova.providers import fal as fal_provider


@pytest.fixture
def fal(monkeypatch, tmp_path):
    sent = {}

    def fake_run(self, model, payload, timeout=900):
        sent.update(model=model, payload=payload)
        return {
            "images": [{"url": "x"}],
            "video": {"url": "x"},
            "audio": {"url": "x"},
        }

    def fake_download(url, dst):
        Path(dst).write_bytes(b"x")
        return dst

    monkeypatch.setattr(fal_provider.Fal, "_run", fake_run)
    monkeypatch.setattr(fal_provider, "_download", fake_download)
    monkeypatch.setenv("FAL_KEY", "test")
    return fal_provider.Fal(), sent, tmp_path


def test_a_still_is_requested_at_more_than_the_default_1k(fal):
    provider, sent, tmp = fal
    provider.image("a prompt", tmp / "a.png", width=1080, height=1920)
    assert sent["payload"]["resolution"] == "2K"
    assert sent["payload"]["aspect_ratio"] == "9:16"


def test_image_to_video_uses_a_live_endpoint_with_an_integer_duration(fal):
    provider, sent, tmp = fal
    still = tmp / "s.png"
    still.write_bytes(b"png")
    provider.video("a prompt", tmp / "a.mp4", duration=4.2, aspect="9:16", image=still)
    assert sent["model"] == "alibaba/wan-3.0-prime/image-to-video"
    assert sent["payload"]["duration"] == 5
    assert sent["payload"]["image_url"].startswith("data:image/png")
    assert sent["payload"]["resolution"] == "1080p"
    assert sent["payload"]["audio"] is False


def test_a_shot_is_billed_for_the_nearest_length_not_the_next_ten_seconds(fal):
    provider, sent, tmp = fal
    provider.video("a prompt", tmp / "a.mp4", duration=6.1, aspect="16:9")
    assert sent["payload"]["duration"] == 7


def test_kling_takes_its_first_frame_under_its_own_field_name():
    spec = config.video_spec("fal", "fal-ai/kling-video/v3/pro/image-to-video")
    assert spec["image_param"] == "start_image_url"


def test_no_deprecated_or_missing_model_is_configured():
    assert config.model_for("elevenlabs", "music") == "music_v2_5"
    assert config.model_for("elevenlabs", "sfx") == "eleven_text_to_sound_v2"
    assert "fal-ai/wan/v3" not in config.model_for("fal", "image_to_video")
    assert "fal-ai/wan/v3" not in config.model_for("fal", "video")


def test_lyria_gets_only_the_fields_it_accepts(fal, monkeypatch):
    provider, sent, tmp = fal
    monkeypatch.setattr("kalainova.media.run", lambda *a, **k: None)
    provider.music("a bed", tmp / "m.wav", duration=30.0)
    assert set(sent["payload"]) == {"prompt"}
