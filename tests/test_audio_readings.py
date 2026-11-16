from __future__ import annotations

import numpy as np
import pytest

from kalainova.bar import sound


def test_pitch_snapping() -> None:
    sr = 24000
    # Create pure 440 Hz tone (exact MIDI note 69 / A4)
    t = np.linspace(0, 1.0, sr, endpoint=False)
    pure_tone = 0.5 * np.sin(2 * np.pi * 440.0 * t)
    snap_score = sound.pitch_snapping(pure_tone, sr)
    assert snap_score > 0.8

    # Noise / vibrato tone with continuous pitch drift
    f_drift = 440.0 + 30.0 * np.sin(2 * np.pi * 10 * t)
    drift_phase = 2 * np.pi * np.cumsum(f_drift) / sr
    drift_tone = 0.5 * np.sin(drift_phase)
    drift_score = sound.pitch_snapping(drift_tone, sr)
    assert drift_score < snap_score


SR = 24000


def _drums(
    seconds: float = 24,
    bpm: float = 120,
    *,
    jitter: float = 0.0,
    swing: bool = False,
    random_onsets: bool = False,
    seed: int = 0,
) -> np.ndarray:
    """A kick on every beat, a snare on two and four, hats on sixteenths: a real pattern's gaps
    between neighbouring onsets are uneven even when the groove is metronome steady."""
    rng = np.random.default_rng(seed)
    x = np.zeros(int(SR * seconds))

    def hit(at: float, amp: float, length: float, hz: float | None = None) -> None:
        i, m = int(at * SR), min(int(length * SR), x.size - int(at * SR))
        if i < 0 or m <= 0:
            return
        t = np.arange(m) / SR
        tone = np.sin(2 * np.pi * hz * t) if hz else rng.standard_normal(m)
        x[i : i + m] += amp * tone * np.exp(-t / (length / 4))

    beat = 60 / bpm
    if random_onsets:
        for at in np.sort(rng.uniform(0, seconds, int(seconds / beat * 3))):
            hit(at, rng.uniform(0.3, 0.9), 0.05)
        return x
    sixteenths = (0, 0.33, 0.5, 0.83) if swing else (0, 0.25, 0.5, 0.75)
    for n in range(int(seconds / beat)):
        at = n * beat + rng.uniform(-jitter, jitter)
        hit(at, 0.9, 0.12, 55)
        if n % 2:
            hit(at, 0.6, 0.08)
        for k, offset in enumerate(sixteenths):
            hit(at + offset * beat, 0.25 + 0.1 * (k % 2), 0.02)
    return x


@pytest.mark.parametrize("groove", [{}, {"swing": True}, {"bpm": 90}, {"bpm": 128}], ids=str)
def test_a_steady_pattern_reads_steady_however_busy_it_is(groove) -> None:
    # A reading that compared the gaps between neighbouring onsets put every such pattern near 0
    assert sound.groove_steadiness(_drums(**groove), SR) > 0.8


@pytest.mark.parametrize("jitter", [0.03, 0.08])
def test_beats_that_drift_off_the_pulse_read_below_the_limit(jitter) -> None:
    assert sound.groove_steadiness(_drums(jitter=jitter), SR) < 0.5


def test_onsets_with_no_common_period_read_near_zero() -> None:
    assert sound.groove_steadiness(_drums(random_onsets=True), SR) < 0.2


def test_a_breakdown_without_drums_does_not_decide_the_reading() -> None:
    steady = _drums(seconds=40)
    steady[int(SR * 16) : int(SR * 24)] = 0.01 * np.sin(np.arange(SR * 8) / 9)  # 8 s pad
    assert sound.groove_steadiness(steady, SR) > 0.8


def test_too_short_to_judge_reads_as_steady() -> None:
    assert sound.groove_steadiness(_drums(seconds=2), SR) == 1.0


def test_mix_balance() -> None:
    sr = 24000
    left = np.random.randn(sr) * 0.1
    right = np.random.randn(sr) * 0.1
    mix = sound.mix_balance(left, right, sr)
    assert "crest_factor_db" in mix
    assert "stereo_width" in mix
    assert "spectral_low" in mix
    assert "spectral_mid" in mix
    assert "spectral_high" in mix
    assert 0.0 <= mix["stereo_width"] <= 1.0
