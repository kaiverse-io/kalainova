"""What the fal adapter sends for stems and for the open song model. No network and no spend."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest
from fakes import needs_ffmpeg

from kalainova import config
from kalainova.providers import fal as fal_provider

pytestmark = needs_ffmpeg


def _mix(path: Path, seconds: float = 2.0) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x00" * int(8000 * seconds))
    return path


@pytest.fixture
def api(monkeypatch):
    sent: dict = {}
    ran: list = []

    def fake_run(self, model, payload, timeout=900):
        sent.update(model=model, payload=payload)
        return sent.get("reply") or {
            k: {"url": k} for k in ("vocals", "drums", "bass", "other", "audio")
        }

    monkeypatch.setattr(fal_provider.Fal, "_run", fake_run)
    monkeypatch.setattr(fal_provider, "_download", lambda url, dst: Path(dst).write_bytes(b"x"))
    monkeypatch.setattr("kalainova.media.run", lambda args, **k: ran.append(args))
    monkeypatch.setenv("FAL_KEY", "test")
    return sent, ran


def test_stems_are_asked_of_demucs_and_billed_by_the_second(api, tmp_path):
    sent, ran = api
    result = fal_provider.Fal().separate(
        _mix(tmp_path / "mix.wav"), tmp_path / "v.wav", tmp_path / "r.wav"
    )
    assert sent["model"] == "fal-ai/demucs"
    assert sent["payload"]["audio_url"].startswith("data:audio/")
    assert sent["payload"]["output_format"] == "wav"
    assert result.cost == pytest.approx(2.0 * 0.0007)
    assert any("amix=inputs=3:normalize=0" in a for a in ran[-1])
    assert (tmp_path / "v.wav").exists()


def test_stems_missing_from_the_reply_are_billed_and_refused(api, tmp_path):
    sent, _ = api
    sent["reply"] = {"audio": {"url": "x"}}
    with pytest.raises(fal_provider.BilledError):
        fal_provider.Fal().separate(
            _mix(tmp_path / "mix.wav"), tmp_path / "v.wav", tmp_path / "r.wav"
        )


def test_separation_is_priced_before_the_call():
    assert fal_provider.Fal().estimate("separate", duration=100.0) == pytest.approx(0.07)


def test_ace_step_takes_tags_and_a_per_second_price(api, tmp_path):
    sent, _ = api
    result = fal_provider.Fal().song(
        "[Verse]\nla",
        tmp_path / "s.wav",
        style="warm",
        duration=100.0,
        model="fal-ai/ace-step",
        instrumental=True,
    )
    assert sent["payload"] == {"tags": "warm", "lyrics": "[inst]", "duration": 100}
    assert result.cost == pytest.approx(0.02)
    assert config.audio_spec("fal", "fal-ai/ace-step")["max_sec"] == 240
