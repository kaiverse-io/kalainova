"""The sound path: mastering, the music bed, and what a mix delivers."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pytest

from kalainova import bar, media, render

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _tone(dst: Path, seconds: float, *, freq: float = 330.0, volume: float = 0.2) -> Path:
    media.run(
        [
            "-f",
            "lavfi",
            "-i",
            f"sine=f={freq}:d={seconds}:r=48000",
            "-af",
            f"volume={volume}",
            "-ac",
            "2",
            str(dst),
        ]
    )
    return dst


def test_mastering_lands_on_target_and_under_the_ceiling(tmp_path):
    src = _tone(tmp_path / "in.wav", 12.0, volume=0.9)
    out = media.master_loudness(src, tmp_path / "out.wav", -24.0, -2.0)
    got = media.loudness(out)
    assert abs(got["integrated_lufs"] - -24.0) <= 0.3
    assert got["true_peak_dbtp"] <= -2.0 + 0.1
    assert media.stream_info(out, "audio")["sample_rate"] == "48000"


def test_mastering_a_quiet_mix_raises_it_without_clipping(tmp_path):
    src = _tone(tmp_path / "in.wav", 12.0, volume=0.02)
    out = media.master_loudness(src, tmp_path / "out.wav", -14.0, -1.0)
    left, right, _ = media.decode_stereo(out)
    assert abs(media.loudness(out)["integrated_lufs"] - -14.0) <= 0.3
    assert bar.clipped_share((left + right) / 2) == 0.0


def test_a_short_music_bed_loops_to_length_with_no_step_at_the_joins(tmp_path):
    src = _tone(tmp_path / "bed.wav", 4.0)
    out = media.loop_audio(src, tmp_path / "looped.wav", 11.0, crossfade=1.0)
    assert media.duration(out) == pytest.approx(11.0, abs=0.05)
    left, *_ = media.decode_stereo(out)
    assert np.abs(np.diff(left)).max() < 0.1


def _mix(tmp_path: Path, *, voice_seconds: float, total: float) -> Path:
    (tmp_path / "v.wav").write_bytes(_tone(tmp_path / "vs.wav", voice_seconds, volume=0.4).read_bytes())
    _tone(tmp_path / "m.wav", 3.0, freq=110.0, volume=0.5)
    render._op_mix_audio(
        tmp_path,
        {
            "out": "mix.wav",
            "duration_sec": total,
            "voice": "v.wav",
            "voice_chain": True,
            "music": "m.wav",
            "music_gain_db": -18.0,
            "duck": True,
            "sfx": [],
        },
    )
    return tmp_path / "mix.wav"


def test_a_mix_has_no_digital_silence_and_the_music_resolves(tmp_path):
    mix = _mix(tmp_path, voice_seconds=4.0, total=10.0)
    left, right, sr = media.decode_stereo(mix)
    mono = (left + right) / 2
    assert media.duration(mix) == pytest.approx(10.0, abs=0.05)
    assert bar.longest_digital_silence(mono, sr) < 0.05
    assert bar.ending_drop_db(mono, sr) < -12


def test_music_sits_well_under_the_voice_while_it_speaks(tmp_path):
    _mix(tmp_path, voice_seconds=6.0, total=10.0)
    voice, *_ = media.decode_stereo(tmp_path / "voice.stem.wav")
    music, _, sr = media.decode_stereo(tmp_path / "music.stem.wav")
    assert bar.voice_to_music_db(voice, music, sr) >= 15.0
