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
    assert sent["payload"]["start_image_url"].startswith("data:image/png")
    assert "image_url" not in sent["payload"]
    assert sent["payload"]["aspect_ratio"] == "9:16"
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


def test_an_end_frame_goes_in_the_models_own_field(fal):
    provider, sent, tmp = fal
    still, end = tmp / "s.png", tmp / "e.png"
    still.write_bytes(b"s")
    end.write_bytes(b"e")
    uploads = []
    provider._upload = lambda path: uploads.append(path) or f"https://x/{path.name}"
    kling = "fal-ai/kling-video/v3/pro/image-to-video"
    provider.video(
        "p", tmp / "a.mp4", duration=5, aspect="9:16", image=still, end_image=end, model=kling
    )
    assert sent["payload"]["end_image_url"] == "https://x/e.png"
    assert sent["payload"]["start_image_url"] == "https://x/s.png"
    provider.video("p", tmp / "b.mp4", duration=5, aspect="9:16", image=still, end_image=end)
    assert sent["payload"]["end_image_url"] == "https://x/e.png", "the default model takes one too"
    assert sent["payload"]["start_image_url"] == "https://x/s.png"


def test_a_model_whose_schema_lists_no_aspect_ratio_is_sent_none(fal):
    provider, sent, tmp = fal
    still = tmp / "s.png"
    still.write_bytes(b"s")
    kling = "fal-ai/kling-video/v3/pro/image-to-video"
    provider.video("p", tmp / "a.mp4", duration=5, aspect="9:16", image=still, model=kling)
    assert "aspect_ratio" not in sent["payload"]
    provider.video("p", tmp / "b.mp4", duration=5, aspect="9:16")
    assert sent["payload"]["aspect_ratio"] == "9:16"
    assert "start_image_url" not in sent["payload"], "text to video takes no first frame"


def test_a_song_longer_than_the_model_makes_is_bounded_in_config():
    assert config.audio_spec("fal", "minimax/music-3")["max_sec"] == 300


def test_every_section_tag_of_a_song_sits_on_its_own_line():
    from kalainova import songs

    song = {
        "sections": [
            {"kind": "verse", "lines": ["one", "two"]},
            {"kind": "chorus", "lines": ["three"]},
        ]
    }
    lines = songs.lyrics_text(song).splitlines()  # type: ignore[arg-type]  # a minimal song
    tags = [line for line in lines if line.startswith("[")]
    assert len(tags) == 2 and all(line.endswith("]") for line in tags)
