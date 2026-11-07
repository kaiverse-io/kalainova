"""The Mac provider's calls, with the model processes faked. No model and no GPU runs here."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from kalainova import media
from kalainova.providers import base, mac

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


@pytest.fixture
def calls(monkeypatch, tmp_path):
    """Stands in for each model process, writing the file that process would write."""
    monkeypatch.setenv(mac.PYTHON_ENV, str(tmp_path / "env" / "bin" / "python"))
    seen: list[list[str]] = []

    def after(cmd: list[str], flag: str) -> Path:
        return Path(cmd[cmd.index(flag) + 1])

    def tone(path: Path) -> None:
        media.run(["-f", "lavfi", "-i", "sine=f=220:d=2", str(path)])

    def fake(cmd: list[str], timeout: float | None = None) -> str:
        seen.append(cmd)
        if "mlx_audio.tts.generate" in cmd:
            tone(after(cmd, "--output_path") / "v_000.wav")
        elif "mlx_audio.stt.generate" in cmd:
            out = after(cmd, "--output-path")
            segment = {"start": 0.25, "end": 1.75, "text": " Heard words here."}
            out.with_suffix(".json").write_text(json.dumps({"segments": [segment]}))
        elif "mlx_audio.music.generate" in cmd:
            tone(after(cmd, "--output"))
        elif any("z-image" in part for part in cmd):
            Image.linear_gradient("L").save(after(cmd, "--output"))
        else:
            after(cmd, "--output-path").write_bytes(b"lossless frames")
        return ""

    monkeypatch.setattr(mac, "_run", fake)
    return seen


def test_it_is_off_until_its_environment_is_named(monkeypatch):
    monkeypatch.delenv(mac.PYTHON_ENV, raising=False)
    assert mac.Mac().missing_env() == [mac.PYTHON_ENV]
    monkeypatch.setenv(mac.PYTHON_ENV, "/somewhere/python")
    assert mac.Mac().available()


def test_it_is_registered_and_free():
    base.names()
    provider = base._REGISTRY["mac"]()
    assert provider.free and not provider.placeholder
    assert provider.estimate("video", duration=5.0) == 0.0


@pytest.mark.parametrize(("aspect", "shape"), [("16:9", (1472, 832)), ("9:16", (832, 1472))])
def test_a_clip_is_asked_for_in_a_shape_and_length_the_model_accepts(
    calls, tmp_path, aspect, shape
):
    out = tmp_path / "c.mp4"
    res = mac.Mac().video("waves, cinematic film still, 35mm", out, duration=5.0, aspect=aspect)
    cmd = calls[0]
    width, height = int(cmd[cmd.index("--width") + 1]), int(cmd[cmd.index("--height") + 1])
    frames = int(cmd[cmd.index("--num-frames") + 1])
    assert (width, height) == shape and width % 64 == 0 and height % 64 == 0
    assert (frames - 1) % 8 == 0
    assert frames >= (5.0 + mac.VIDEO_MARGIN_SEC) * 24, "a clip runs past its shot"
    assert out.read_bytes() == b"lossless frames" and res.path == out
    assert not out.with_suffix(".raw.mp4").exists()


def test_a_clip_uses_the_fixed_runner_and_is_never_told_to_be_a_still(calls, tmp_path):
    mac.Mac().video(
        "waves, cinematic film still, 35mm", tmp_path / "c.mp4", duration=2.0, aspect="16:9"
    )
    cmd = calls[0]
    assert Path(cmd[1]) == mac.LTX_RUNNER and mac.LTX_RUNNER.is_file()
    assert "film still" not in cmd[cmd.index("--prompt") + 1]
    assert "--image" not in cmd


def test_a_clip_starts_from_its_still_when_given_one(calls, tmp_path):
    mac.Mac().video(
        "waves", tmp_path / "c.mp4", duration=2.0, aspect="16:9", image=tmp_path / "s.png"
    )
    cmd = calls[0]
    assert cmd[cmd.index("--image") + 1] == str(tmp_path / "s.png")
    assert cmd[cmd.index("--image-strength") + 1] == "1.0"  # 1.0 pins the first frame to the still


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_a_still_comes_back_as_a_png_in_a_size_the_model_can_make(calls, tmp_path):
    out = tmp_path / "s.png"
    mac.Mac().image("a bridge", out, width=3840, height=2160)
    cmd = calls[0]
    width, height = int(cmd[cmd.index("--width") + 1]), int(cmd[cmd.index("--height") + 1])
    assert width % 16 == 0 and height % 16 == 0
    assert width * height <= mac.STILL_MOST_PIXELS
    assert Image.open(out).format == "PNG"


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_music_is_instrumental_at_mix_rate(calls, tmp_path):
    out = tmp_path / "m.wav"
    mac.Mac().music("slow piano", out, duration=3.2)
    cmd = calls[0]
    assert cmd[cmd.index("--lyrics") + 1] == "[instrumental]"
    assert cmd[cmd.index("--duration") + 1] == "4"
    info = media.summarize(out)
    assert (info["sample_rate_hz"], info["channels"]) == (48000, 2)


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_a_voice_line_is_timed_by_what_was_heard_in_the_scripts_spelling(calls, tmp_path):
    out = tmp_path / "v.wav"
    res = mac.Mac().voice("Exact script words.", out, voice="bm_george")
    assert media.summarize(out)["sample_rate_hz"] == 48000
    assert calls[0][calls[0].index("--lang_code") + 1] == "b"
    assert [w["text"] for w in res.words] == ["Exact", "script", "words."]
    assert 0.25 <= res.words[0]["start_sec"] < 0.4
    assert 1.6 < res.words[-1]["end_sec"] <= 1.75


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_a_transcript_keeps_what_was_heard(calls, tmp_path):
    res = mac.Mac().transcribe(tmp_path / "a.wav")
    assert res.text == "Heard words here."
    assert [w["text"] for w in res.words] == ["Heard", "words", "here."]


def test_a_failed_model_process_is_a_provider_failure(monkeypatch, tmp_path):
    monkeypatch.setenv(mac.PYTHON_ENV, str(tmp_path / "bin" / "python"))

    class Failed:
        pid = 1
        returncode = 1

        def __init__(self, *a, **k):
            pass

        def communicate(self, timeout=None):
            return "", "out of memory"

    monkeypatch.setattr(subprocess, "Popen", Failed)
    with pytest.raises(RuntimeError, match="out of memory"):
        mac._run(["python", "-m", "something"])
