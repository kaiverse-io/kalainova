"""What ElevenLabs' own API is sent and what it keeps: lossless audio and its fallback, and a song
as the same composition plan every host of the model sends. No network."""

from __future__ import annotations

import base64

import pytest
from fakes import Reply, context

from kalainova import media
from kalainova.providers import remote, transport
from kalainova.providers.contract import SongRequest, UnauthorizedError, VoiceRequest


@pytest.fixture
def eleven(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    sent = []
    made = []

    def post(url, **kw):
        sent.append({"url": url, **kw})
        return replies.pop(0)

    replies: list[Reply] = []
    monkeypatch.setattr(transport.requests, "post", post)
    monkeypatch.setattr(media, "run", lambda args, **k: made.append(args))
    return remote.ElevenLabs(), sent, replies, made


def _speech(blob=b"pcm"):
    return Reply(body={"audio_base64": base64.b64encode(blob).decode(), "alignment": {}})


def test_speech_is_asked_for_losslessly_and_read_as_raw_samples(eleven, tmp_path):
    provider, sent, replies, made = eleven
    replies.append(_speech())
    res = provider.voice(VoiceRequest(text="A line.", dst=tmp_path / "v.wav"), context())
    assert sent[0]["params"]["output_format"] == "pcm_48000"
    assert res.meta["audio_format"] == "pcm_48000"
    assert made[0][:6] == ["-f", "s16le", "-ar", "48000", "-ac", "1"]


def test_a_plan_without_lossless_audio_falls_back_and_the_record_says_so(eleven, tmp_path):
    provider, sent, replies, made = eleven
    replies += [Reply(status=403, text="output_format not allowed on this tier"), _speech()]
    res = provider.voice(VoiceRequest(text="A line.", dst=tmp_path / "v.wav"), context())
    assert sent[1]["params"]["output_format"] == "mp3_44100_128"
    assert res.meta["audio_format"] == "mp3_44100_128"
    assert made[0][0] == "-i", "an mp3 needs no raw format"


def test_some_other_failure_is_not_mistaken_for_a_plan_limit(eleven, tmp_path):
    provider, sent, replies, _ = eleven
    replies.append(Reply(status=401, text="bad key"))
    with pytest.raises(UnauthorizedError):
        provider.voice(VoiceRequest(text="A line.", dst=tmp_path / "v.wav"), context())
    assert len(sent) == 1


def test_a_song_goes_as_a_chunked_composition_plan(eleven, tmp_path):
    provider, sent, replies, _ = eleven
    replies.append(Reply(content=b"pcm"))
    sections = [
        {"kind": "verse", "lines": ["One", "Two"], "style": "soft"},
        {"kind": "chorus", "lines": ["Three", "Four", "Five", "Six"]},
    ]
    asked = SongRequest(
        lyrics="ignored",
        dst=tmp_path / "s.wav",
        style="pop",
        duration=60,
        sections=sections,
        avoid="dark",
    )
    provider.song(asked, context())
    body = sent[0]["json"]
    assert body["model_id"] == "music_v2_5" and "prompt" not in body
    chunks = body["composition_plan"]["chunks"]
    assert chunks[0]["text"] == "[Verse]\nOne\nTwo"
    # the same plan fal sends this model: each section's own note leads, the style once, first
    assert chunks[0]["positive_styles"] == ["soft", "pop"] and chunks[1]["negative_styles"] == [
        "dark"
    ]
    assert chunks[1]["positive_styles"] == ["pop"], "a section with no note keeps the style"
    assert chunks[1]["duration_ms"] == 2 * chunks[0]["duration_ms"], "time follows the lines"


def test_a_song_goes_to_elevenlabs_as_the_plan_fal_sends_it(eleven, tmp_path):
    """One builder for a model family: the host decides how the request travels, never what the
    model is asked."""
    from kalainova.providers import song_text

    provider, sent, replies, _ = eleven
    replies.append(Reply(content=b"pcm"))
    sections = [
        {"kind": "intro", "bars": 8, "style": "pads alone", "avoid": "kick"},
        {"kind": "pre-chorus", "bars": 4, "lines": ["Juntos, one breath in"]},
    ]
    said = {"juntos": "HOON-tohs"}
    asked = SongRequest(lyrics="", dst=tmp_path / "s.wav", style="house", duration=180, bpm=120,
                        sections=sections, avoid="rap", seed=9, pronounce=said)  # fmt: skip
    res = provider.song(asked, context())
    body = sent[0]["json"]
    assert body["composition_plan"]["chunks"] == song_text.plan(
        sections, "house", "rap", 120, 180, {"juntos": "HOON-tohs"}
    )
    assert body["seed"] == 9
    assert res.cost == pytest.approx(24 / 60 * 0.80)  # priced on the 24 s the plan runs


def test_a_song_plan_past_the_apis_limits_is_refused_before_sending(eleven, tmp_path):
    provider, sent, _, _ = eleven
    many = [{"kind": "verse", "lines": ["x"]} for _ in range(50)]
    asked = SongRequest(lyrics="", dst=tmp_path / "s.wav", style="pop", duration=600, sections=many)
    with pytest.raises(ValueError, match="1 to 30 sections"):
        provider.song(asked, context())
    assert not sent


def test_a_song_with_no_sections_goes_as_a_prompt(eleven, tmp_path):
    provider, sent, replies, _ = eleven
    replies.append(Reply(content=b"pcm"))
    provider.song(
        SongRequest(lyrics="The words", dst=tmp_path / "s.wav", style="pop", duration=30), context()
    )
    assert sent[0]["json"]["prompt"] == "pop\nThe words"
