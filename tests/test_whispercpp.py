"""The whisper.cpp transcribe provider: real word times, run as a command."""

import json
import shutil
import subprocess

import pytest

from kalainova.providers import whispercpp
from kalainova.providers.whispercpp import MODEL_ENV, WhisperCpp

DOC = {
    "transcription": [
        {"text": " [_BEG_]", "offsets": {"from": 0, "to": 0}},
        {"text": " Hello", "offsets": {"from": 120, "to": 480}},
        {"text": " world.", "offsets": {"from": 500, "to": 900}},
        {"text": " [BLANK_AUDIO]", "offsets": {"from": 900, "to": 1000}},
    ]
}


def test_parse_keeps_words_and_drops_markers():
    words = whispercpp.parse_words(DOC)
    assert [w["text"] for w in words] == ["Hello", "world."]
    assert (words[0]["start_sec"], words[0]["end_sec"]) == (0.12, 0.48)


def test_unavailable_without_the_command_or_a_model(monkeypatch, tmp_path):
    monkeypatch.setattr(whispercpp.shutil, "which", lambda name: None)
    assert any("whisper-cli" in m for m in WhisperCpp().missing_env())
    monkeypatch.setattr(whispercpp.shutil, "which", lambda name: "/bin/whisper-cli")
    monkeypatch.delenv(MODEL_ENV, raising=False)
    assert WhisperCpp().missing_env() == [MODEL_ENV]
    monkeypatch.setenv(MODEL_ENV, str(tmp_path / "none.bin"))
    assert not WhisperCpp().available()
    model = tmp_path / "m.bin"
    model.write_bytes(b"x")
    monkeypatch.setenv(MODEL_ENV, str(model))
    assert WhisperCpp().available()


def test_transcribe_through_a_fake_command(monkeypatch, tmp_path):
    model = tmp_path / "ggml-fake.bin"
    model.write_bytes(b"x")
    monkeypatch.setenv(MODEL_ENV, str(model))
    monkeypatch.setattr(whispercpp.shutil, "which", lambda name: "/bin/whisper-cli")
    monkeypatch.setattr(whispercpp.media, "run", lambda args, **k: None)
    seen = {}

    def run(cmd, **kw):
        seen["cmd"] = cmd
        out = cmd[cmd.index("-of") + 1] + ".json"
        open(out, "w").write(json.dumps(DOC))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(whispercpp.subprocess, "run", run)
    res = WhisperCpp().transcribe(tmp_path / "a.wav")
    assert res.text == "Hello world."
    assert "-sow" in seen["cmd"] and seen["cmd"][seen["cmd"].index("-m") + 1] == str(model)


def test_a_failed_command_is_a_provider_failure(monkeypatch, tmp_path):
    model = tmp_path / "m.bin"
    model.write_bytes(b"x")
    monkeypatch.setenv(MODEL_ENV, str(model))
    monkeypatch.setattr(whispercpp.shutil, "which", lambda name: "/bin/whisper-cli")
    monkeypatch.setattr(whispercpp.media, "run", lambda args, **k: None)
    failed = subprocess.CompletedProcess([], 1, "", "bad model")
    monkeypatch.setattr(whispercpp.subprocess, "run", lambda *a, **k: failed)
    with pytest.raises(RuntimeError, match="bad model"):
        WhisperCpp().transcribe(tmp_path / "a.wav")


@pytest.mark.skipif(
    shutil.which("whisper-cli") is None or not __import__("os").environ.get(MODEL_ENV),
    reason="whisper-cli or KALAINOVA_WHISPER_CPP_MODEL missing",
)
def test_real_whisper_cpp_is_available():
    assert WhisperCpp().available()
