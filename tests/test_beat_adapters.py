"""The beat seam: in-house by default, `beat_this` by config, called as a command."""

import shutil
import stat
import wave
from pathlib import Path

import pytest

from kalainova import config
from kalainova.editor import beat_this, beats
from kalainova.jobfs import ContractError

FAKE = """#!/bin/sh
# fake beat_this: $1 audio, $2 -o, $3 output
printf '0.50\\t1\\n1.00\\t2\\n1.50\\t3\\n2.00\\t4\\n2.50\\t1\\n3.00\\t2\\n' > "$3"
"""


def _wav(path: Path) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\0\0" * 22050 * 4)
    return path


def _select(monkeypatch, entry: dict) -> None:
    monkeypatch.setattr(config, "studio", lambda: {"adapters": {"beats": entry}})


def test_default_is_inhouse(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "studio", lambda: {})
    grid = beats.beat_grid(_wav(tmp_path / "a.wav"))
    assert {"bpm", "beats", "confidence"} <= grid.keys()
    assert "downbeats" not in grid


def test_parse_reads_downbeats_and_skips_headers():
    got = beat_this.parse("time\tbeat\n0.5\t1\n1.0\t2\n1.5\n2.0\t1\n")
    assert got == ([0.5, 1.0, 1.5, 2.0], [0.5, 2.0])


def test_beat_this_through_a_fake_command(tmp_path, monkeypatch):
    fake = tmp_path / "fake_beat_this"
    fake.write_text(FAKE)
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    _select(monkeypatch, {"use": "beat_this", "command": str(fake)})
    grid = beats.beat_grid(_wav(tmp_path / "a.wav"), duration=2.75)
    assert grid["bpm"] == 120.0
    assert grid["beats"] == [0.5, 1.0, 1.5, 2.0, 2.5]
    assert grid["downbeats"] == [0.5, 2.5]
    assert grid["confidence"] == 1.0


def test_missing_command_names_it(tmp_path, monkeypatch):
    _select(monkeypatch, {"use": "beat_this", "command": "no-such-beat-tool"})
    with pytest.raises(ContractError, match="no-such-beat-tool"):
        beats.beat_grid(_wav(tmp_path / "a.wav"))


def test_unknown_adapter_is_refused(tmp_path, monkeypatch):
    _select(monkeypatch, {"use": "nope"})
    with pytest.raises(ContractError, match="unknown adapter"):
        beats.beat_grid(_wav(tmp_path / "a.wav"))


@pytest.mark.skipif(shutil.which("beat_this") is None, reason="beat_this is not installed")
def test_real_beat_this(tmp_path, monkeypatch):
    _select(monkeypatch, {"use": "beat_this"})
    grid = beats.beat_grid(_wav(tmp_path / "a.wav"))
    assert grid["beats"] is not None
