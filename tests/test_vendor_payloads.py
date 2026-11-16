"""What each adapter sends, against the schemas the vendors publish. No network and no spend."""

from __future__ import annotations

import pytest
from fakes import Wire, context

from kalainova import config
from kalainova.providers import fal as fal_provider
from kalainova.providers.contract import ImageRequest, MusicRequest, VideoRequest


class FalWire(Wire):
    """fal's own way of sending a small input (inline), with no network for the rest."""

    _upload = fal_provider.FalQueue._upload
    _key = staticmethod(lambda: "test")


@pytest.fixture
def fal(monkeypatch, tmp_path):
    reply = {"images": [{"url": "x"}], "video": {"url": "x"}, "audio": {"url": "x"}}
    wire = FalWire(default=reply, files={"x": b"x"})
    monkeypatch.setattr(fal_provider.Fal, "transport", wire)
    monkeypatch.setenv("FAL_KEY", "test")

    class Sent:
        def __getitem__(self, key):
            last = wire.sent[-1]
            return last["endpoint"] if key == "model" else last[key]

    return fal_provider.Fal(), Sent(), tmp_path


def ask(provider, request, model=None):
    return getattr(provider, request.capability)(request, context(model=model))


def test_a_still_is_requested_at_more_than_the_default_1k(fal):
    provider, sent, tmp = fal
    ask(provider, ImageRequest(prompt="a prompt", dst=tmp / "a.png", width=1080, height=1920))
    assert sent["payload"]["resolution"] == "2K"
    assert sent["payload"]["aspect_ratio"] == "9:16"


def test_image_to_video_uses_a_live_endpoint_with_an_integer_duration(fal):
    provider, sent, tmp = fal
    still = tmp / "s.png"
    still.write_bytes(b"png")
    ask(
        provider,
        VideoRequest(
            prompt="a prompt", dst=tmp / "a.mp4", duration=4.2, aspect="9:16", start=still
        ),
    )
    assert sent["model"] == "alibaba/wan-3.0-prime/image-to-video"
    assert sent["payload"]["duration"] == 5
    assert sent["payload"]["start_image_url"].startswith("data:image/png")
    assert "image_url" not in sent["payload"]
    assert sent["payload"]["aspect_ratio"] == "9:16"
    assert sent["payload"]["resolution"] == "1080p"
    assert sent["payload"]["audio"] is False


def test_a_shot_is_billed_for_the_nearest_length_not_the_next_ten_seconds(fal):
    provider, sent, tmp = fal
    ask(provider, VideoRequest(prompt="a prompt", dst=tmp / "a.mp4", duration=6.1, aspect="16:9"))
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
    ask(provider, MusicRequest(prompt="a bed", dst=tmp / "m.wav", duration=30.0))
    assert set(sent["payload"]) == {"prompt"}


def test_an_end_frame_goes_in_the_models_own_field(fal):
    provider, sent, tmp = fal
    still, end = tmp / "s.png", tmp / "e.png"
    still.write_bytes(b"s")
    end.write_bytes(b"e")
    provider.transport._upload = lambda path: f"https://x/{path.name}"
    kling = "fal-ai/kling-video/v3/pro/image-to-video"
    clip = VideoRequest(
        prompt="p", dst=tmp / "a.mp4", duration=5, aspect="9:16", start=still, end=end
    )
    ask(provider, clip, kling)
    assert sent["payload"]["end_image_url"] == "https://x/e.png"
    assert sent["payload"]["start_image_url"] == "https://x/s.png"
    clip = VideoRequest(
        prompt="p", dst=tmp / "b.mp4", duration=5, aspect="9:16", start=still, end=end
    )
    ask(provider, clip)
    assert sent["payload"]["end_image_url"] == "https://x/e.png", "the default model takes one too"
    assert sent["payload"]["start_image_url"] == "https://x/s.png"


def test_a_model_whose_schema_lists_no_aspect_ratio_is_sent_none(fal):
    provider, sent, tmp = fal
    still = tmp / "s.png"
    still.write_bytes(b"s")
    kling = "fal-ai/kling-video/v3/pro/image-to-video"
    clip = VideoRequest(prompt="p", dst=tmp / "a.mp4", duration=5, aspect="9:16", start=still)
    ask(provider, clip, kling)
    assert "aspect_ratio" not in sent["payload"]
    ask(provider, VideoRequest(prompt="p", dst=tmp / "b.mp4", duration=5, aspect="9:16"))
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
