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
    (tmp_path / "v.wav").write_bytes(
        _tone(tmp_path / "vs.wav", voice_seconds, volume=0.4).read_bytes()
    )
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


def test_a_fader_lifts_the_quiet_passage_and_leaves_the_loud_one_and_silence_alone():
    sr = 48000
    t = np.arange(sr * 8) / sr
    tone = np.sin(2 * np.pi * 110 * t)
    quiet, loud, silent = 0.005 * tone, 0.5 * tone, np.zeros(t.size)
    gain = media.fader_ride(np.concatenate([quiet, loud, silent]), sr)
    assert 20 * np.log10(gain[sr * 3]) > 25  # 40 dB under, and most of that is taken back
    assert gain[sr * 13] == pytest.approx(1.0, abs=0.02)
    assert gain[sr * 21] == pytest.approx(1.0, abs=0.02)


def test_a_fader_on_nothing_changes_nothing():
    assert (media.fader_ride(np.zeros(48000 * 3), 48000) == 1.0).all()
    assert (media.fader_ride(np.zeros(100), 48000) == 1.0).all()


def _swinging_bed(path: Path) -> Path:
    """A score that spends half its length 30 dB under the rest, as a generated one can."""
    media.run(
        [
            "-f", "lavfi", "-i", "sine=f=110:d=8,volume=-42dB",
            "-f", "lavfi", "-i", "sine=f=110:d=8,volume=-12dB",
            "-filter_complex", "[0:a][1:a]concat=n=2:v=0:a=1,aformat=channel_layouts=stereo",
            "-ar", "48000", str(path),
        ]
    )  # fmt: skip
    return path


def _speech_like(path: Path, volume: float) -> None:
    """A tone that swells and falls about as often as syllables do, so the ducker reacts to it."""
    media.run(
        [
            "-f", "lavfi", "-i", "sine=f=330:d=16:r=48000",
            "-af", f"volume={volume},tremolo=f=4:d=0.9", "-ac", "2", str(path),
        ]
    )  # fmt: skip


def _gap(tmp_path: Path, voice_volume: float = 2.0) -> float:
    _speech_like(tmp_path / "v.wav", voice_volume)
    _swinging_bed(tmp_path / "m.wav")
    render._op_mix_audio(
        tmp_path,
        {
            "out": "mix.wav",
            "duration_sec": 16.0,
            "voice": "v.wav",
            "voice_chain": False,
            "music": "m.wav",
            "music_gain_db": render.MUSIC_UNDER_VOICE_DB,
            "duck": True,
            "sfx": [],
        },
    )
    voice, *_ = media.decode_stereo(tmp_path / "voice.stem.wav")
    music, _, sr = media.decode_stereo(tmp_path / "music.stem.wav")
    return bar.voice_to_music_db(voice, music, sr)


def test_a_score_with_big_swings_stays_audible_under_the_voice(tmp_path):
    gap = _gap(tmp_path)
    assert 12.0 <= gap <= 26.0
    music, _, sr = media.decode_stereo(tmp_path / "music.stem.wav")
    early = float(np.sqrt(np.mean(music[sr * 2 : sr * 6] ** 2)))
    late = float(np.sqrt(np.mean(music[sr * 10 : sr * 14] ** 2)))
    assert abs(20 * np.log10(early / late)) < 15.0  # it went in 30 dB apart


def test_the_music_is_set_against_the_voice_it_will_sit_under(tmp_path):
    (tmp_path / "loud").mkdir()
    (tmp_path / "soft").mkdir()
    assert abs(_gap(tmp_path / "loud", 2.0) - _gap(tmp_path / "soft", 0.8)) < 3.0


def test_music_alone_keeps_its_own_level_and_has_no_voice_stem(tmp_path):
    _tone(tmp_path / "m.wav", 3.0, freq=110.0, volume=1.0)
    render._op_mix_audio(
        tmp_path,
        {"out": "mix.wav", "duration_sec": 3.0, "music": "m.wav", "music_gain_db": -6.0, "sfx": []},
    )
    assert not (tmp_path / "voice.stem.wav").exists()
    assert not (tmp_path / "music.even.wav").exists(), "the fader rides only under a voice"
    want = media.loudness(tmp_path / "m.wav")["integrated_lufs"] - 6.0
    assert media.loudness(tmp_path / "mix.wav")["integrated_lufs"] == pytest.approx(want, abs=1.5)


def test_a_voice_alone_has_no_music_stem_and_an_effect_lands_on_its_mark(tmp_path):
    _tone(tmp_path / "v.wav", 2.0, volume=1.0)
    _tone(tmp_path / "hit.wav", 0.2, freq=1000.0, volume=1.0)
    render._op_mix_audio(
        tmp_path,
        {
            "out": "mix.wav",
            "duration_sec": 4.0,
            "voice": "v.wav",
            "voice_chain": False,
            "sfx": [{"path": "hit.wav", "start_sec": 3.0, "gain_db": 0.0}],
        },
    )
    assert not (tmp_path / "music.stem.wav").exists()
    left, _, sr = media.decode_stereo(tmp_path / "mix.wav")
    assert abs(left[int(sr * 2.5) : int(sr * 2.9)]).max() < 0.02
    assert abs(left[int(sr * 3.05) : int(sr * 3.15)]).max() > 0.05


def test_a_dc_offset_in_generated_music_does_not_reach_the_mix(tmp_path):
    _tone(tmp_path / "v.wav", 4.0, volume=2.0)
    media.run(
        [
            "-f", "lavfi", "-i", "aevalsrc='0.05+0.1*sin(2*PI*110*t)':s=48000:d=4",
            "-ac", "2", str(tmp_path / "m.wav"),
        ]
    )  # fmt: skip
    render._op_mix_audio(
        tmp_path,
        {
            "out": "mix.wav",
            "duration_sec": 4.0,
            "voice": "v.wav",
            "voice_chain": False,
            "music": "m.wav",
            "duck": True,
            "sfx": [],
        },
    )
    music, _, sr = media.decode_stereo(tmp_path / "music.stem.wav")
    level = float(np.sqrt(np.mean(music[sr:-sr] ** 2)))
    assert abs(bar.dc_offset(music[sr:-sr])) < level * 0.05


def test_music_too_quiet_to_hear_misses_the_bar(tmp_path):
    _tone(tmp_path / "voice.stem.wav", 2.0, volume=0.4)
    _tone(tmp_path / "music.stem.wav", 2.0, freq=110.0, volume=0.002)
    readings = {r.id: r for r in bar._stem_readings(tmp_path)}
    assert not readings["audio.music_audible"].ok


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
