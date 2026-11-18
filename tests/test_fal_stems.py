"""What the fal adapter sends for stems and for the open song model. No network and no spend."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest
from fakes import Wire, context, needs_ffmpeg

from kalainova import config
from kalainova.providers import fal as fal_provider
from kalainova.providers.contract import Billable, SeparateRequest, SongRequest

pytestmark = needs_ffmpeg


def _mix(path: Path, seconds: float = 2.0) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * seconds))
    return path


class FalWire(Wire):
    _upload = fal_provider.FalQueue._upload
    _key = staticmethod(lambda: "test")


@pytest.fixture
def api(monkeypatch):
    ran: list = []
    stems = {k: {"url": k} for k in ("vocals", "drums", "bass", "other", "audio")}
    wire = FalWire(default=stems, files={k: b"x" for k in stems})
    monkeypatch.setattr(fal_provider.Fal, "transport", wire)
    monkeypatch.setattr("kalainova.media.run", lambda args, **k: ran.append(args))
    monkeypatch.setenv("FAL_KEY", "test")
    return wire, ran


def split(tmp_path):
    asked = SeparateRequest(
        src=_mix(tmp_path / "mix.wav"), vocals=tmp_path / "v.wav", rest=tmp_path / "r.wav"
    )
    return fal_provider.Fal().separate(asked, context())


def test_stems_are_asked_of_demucs_and_billed_by_the_second(api, tmp_path):
    wire, ran = api
    result = split(tmp_path)
    assert wire.sent[-1]["endpoint"] == "fal-ai/demucs"
    assert wire.payloads[-1]["audio_url"].startswith("data:audio/")
    assert wire.payloads[-1]["output_format"] == "wav"
    assert wire.payloads[-1]["stems"] == ["vocals", "drums", "bass", "other"]
    assert result.cost == pytest.approx(2.0 * 0.0007)
    assert any("amix=inputs=3:normalize=0" in a for a in ran[-1])
    assert (tmp_path / "v.wav").exists()


def test_stems_missing_from_the_reply_are_billed_and_refused(api, tmp_path):
    wire, _ = api
    wire.default = {"audio": {"url": "x"}}
    with pytest.raises(fal_provider.BilledError):
        split(tmp_path)


def test_separation_is_priced_before_the_call():
    asked = Billable(capability="separate", duration=100.0)
    assert fal_provider.Fal().estimate(asked) == pytest.approx(0.07)


def test_ace_step_takes_tags_and_a_per_second_price(api, tmp_path):
    wire, _ = api
    asked = SongRequest(
        lyrics="[Verse]\nla",
        dst=tmp_path / "s.wav",
        style="warm",
        duration=100.0,
        instrumental=True,
    )
    result = fal_provider.Fal().song(asked, context(model="fal-ai/ace-step"))
    assert wire.payloads[-1] == {"tags": "warm", "lyrics": "[inst]", "duration": 100}
    assert result.cost == pytest.approx(0.02)
    assert config.audio_spec("fal", "fal-ai/ace-step")["max_sec"] == 240
