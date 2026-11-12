"""The beat seam: in-house by default, `beat_this` by config, called as a command."""

import shutil
import stat
import wave
from pathlib import Path

import numpy as np
import pytest

from kalainova import config, media
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


def _clicks(path: Path, bpm: float = 120.0, secs: int = 20) -> Path:
    """A synthetic drum loop: a kick on every beat (low, loud on each fourth), a hat between."""
    sr = 22050
    rng = np.random.default_rng(1)
    pcm = np.zeros(sr * secs)
    step = int(sr * 60 / bpm)
    t = np.arange(int(sr * 0.25)) / sr
    kick = np.sin(2 * np.pi * (50 + 90 * np.exp(-t * 30)) * t) * np.exp(-t * 12)
    hat = rng.standard_normal(int(sr * 0.05)) * np.exp(-np.arange(int(sr * 0.05)) / (sr * 0.01))
    for i, at in enumerate(range(0, len(pcm) - len(kick) - step, step)):
        pcm[at : at + len(kick)] += kick * (1.0 if i % 4 == 0 else 0.7)
        pcm[at + step // 2 : at + step // 2 + len(hat)] += hat * 0.3
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((pcm / np.abs(pcm).max() * 20000).astype("<i2").tobytes())
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


def test_parse_reads_real_output_shape_with_float_bar_position():
    # beat_this writes "<seconds>\t<beat in bar>": 1 is a downbeat, 2..4 are not
    got = beat_this.parse("1.18\t1\n2.2\t1\n2.74\t2\n3.3\t1.0\n3.94\t10\n")
    assert got[1] == [1.18, 2.2, 3.3]


def test_the_tool_is_handed_a_wav_whatever_the_input(tmp_path, monkeypatch):
    seen = tmp_path / "seen.txt"
    fake = tmp_path / "fake_beat_this"
    fake.write_text(
        f'#!/bin/sh\nfile -b "$1" | cut -c1-12 > {seen}\nprintf \'0.5\\t1\\n1.0\\t2\\n\' > "$3"\n'
    )
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    _select(monkeypatch, {"use": "beat_this", "command": str(fake)})
    m4a = tmp_path / "a.m4a"
    media.run(["-i", str(_wav(tmp_path / "a.wav")), str(m4a)])
    beats.beat_grid(m4a)
    assert "RIFF" in seen.read_text()


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
    grid = beats.beat_grid(_clicks(tmp_path / "c.wav"))
    assert 110 < grid["bpm"] < 130 or 55 < grid["bpm"] < 65 or 230 < grid["bpm"] < 250
    assert grid["downbeats"]
