from __future__ import annotations

import numpy as np

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


def test_groove_steadiness() -> None:
    sr = 24000
    # Create regular pulse every 0.5s (120 bpm)
    x = np.zeros(sr * 3)
    for onset in [0.0, 0.5, 1.0, 1.5, 2.0, 2.5]:
        idx = int(onset * sr)
        x[idx : idx + 200] = 0.8
    steady_score = sound.groove_steadiness(x, sr)
    assert steady_score > 0.8

    # Irregular pulses
    x_irreg = np.zeros(sr * 3)
    for onset in [0.0, 0.2, 0.9, 1.1, 2.3, 2.4]:
        idx = int(onset * sr)
        x_irreg[idx : idx + 200] = 0.8
    irreg_score = sound.groove_steadiness(x_irreg, sr)
    assert irreg_score < steady_score


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
