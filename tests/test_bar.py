"""The studio bar's signals, each proved on synthetic media with a known answer."""

from __future__ import annotations

import numpy as np

from kalainova import bar, config

SR = 48000


def _gradient(w: int = 400, h: int = 300, span: float = 24.0, dither: float = 0.0) -> np.ndarray:
    ramp = np.linspace(40, 40 + span, w)[None, :].repeat(h, axis=0)
    if dither:
        ramp = ramp + np.random.default_rng(1).uniform(-dither, dither, ramp.shape)
    return np.round(ramp).astype(np.uint8)


def test_banding_flags_a_stepped_gradient_and_passes_a_dithered_one():
    assert bar.banding_score(_gradient()) > 0.5
    assert bar.banding_score(_gradient(dither=1.5)) < 0.05


def test_banding_ignores_flat_black_and_real_texture():
    assert bar.banding_score(np.zeros((300, 400), np.uint8)) == 0.0
    noise = np.random.default_rng(2).integers(0, 255, (300, 400)).astype(np.uint8)
    assert bar.banding_score(noise) < 0.01


def test_stutter_flags_a_stepped_move_and_passes_a_steady_one():
    steady = np.array([1.0, 1.05, 0.97, 1.02, 0.99, 1.01] * 10)
    stepped = np.array([0.0, 0.0, 3.0, 0.0, 0.0, 3.0] * 10)
    assert bar.stutter_score(steady) < 0.1
    assert bar.stutter_score(stepped) > 0.5


def test_stutter_is_zero_for_a_frozen_or_empty_series():
    assert bar.stutter_score(np.zeros(30)) == 0.0
    assert bar.stutter_score(np.zeros(0)) == 0.0


def _textured(seed: int, size: int = 256) -> np.ndarray:
    rng = np.random.default_rng(seed)
    coarse = rng.uniform(0, 255, (size // 8, size // 8))
    return np.kron(coarse, np.ones((8, 8)))[:size, :size]


def test_repetition_counts_near_duplicates_and_not_distinct_shots():
    a, b, c = _textured(4, 64), _textured(5, 64), _textured(6, 64)
    assert bar.repetition_share([a, b, c]) == 0.0
    assert bar.repetition_share([a, a + 2, c]) == 2 / 3


def test_mark_finds_a_stamp_shared_by_different_shots():
    # The grids are shifted apart, so only the stamp lands in the same place in every shot.
    shots = [
        np.roll(_textured(s, 256), s * 3, axis=(0, 1)).astype(np.uint8) // 4
        for s in (7, 8, 9, 10, 11, 12)
    ]
    clean = [s.copy() for s in shots]
    for s in shots:
        s[230:246, 190:246] = 250
    assert bar.corner_mark_score(shots) > bar.corner_mark_score(clean) * 3
    assert bar.corner_mark_score(shots) > 0.002


def test_detail_ratio_falls_when_a_frame_was_upscaled():
    sharp = np.random.default_rng(13).uniform(0, 255, (512, 512))
    soft = np.kron(sharp[:256, :256], np.ones((2, 2)))
    from PIL import Image

    smooth = np.asarray(
        Image.fromarray(soft.astype(np.uint8)).resize((256, 256)).resize((512, 512))
    )
    assert bar.detail_ratio(sharp) > bar.detail_ratio(smooth) * 4


def _speechlike(seconds: float, *, tail_ms: float = 40.0) -> np.ndarray:
    n = int(seconds * SR)
    t = np.arange(n) / SR
    x = 0.3 * np.sin(2 * np.pi * 220 * t)
    decay = int(tail_ms / 1000 * SR)
    env = np.ones(n)
    env[-decay:] = np.linspace(1, 0, decay)
    return x * env


def test_hard_cuts_count_speech_chopped_mid_word_but_not_a_natural_decay():
    natural = np.concatenate([_speechlike(0.8), np.zeros(SR // 4)] * 6)
    chopped = np.concatenate([_speechlike(0.8, tail_ms=0.5), np.zeros(SR // 4)] * 6)
    assert bar.hard_cuts_per_min(natural, SR) < 2
    assert bar.hard_cuts_per_min(chopped, SR) > 30


def test_clipping_and_dc_are_seen():
    x = np.sin(2 * np.pi * 220 * np.arange(SR) / SR)
    assert bar.clipped_share(0.4 * x) == 0.0
    assert bar.clipped_share(np.clip(2.0 * x, -1, 1)) > 0.2
    assert abs(bar.dc_offset(0.4 * x + 0.05) - 0.05) < 0.001


def test_stereo_correlation_catches_inverted_channels():
    x = np.sin(2 * np.pi * 220 * np.arange(SR) / SR)
    assert bar.stereo_correlation(x, x) > 0.99
    assert bar.stereo_correlation(x, -x) < -0.99
    assert bar.stereo_correlation(np.zeros(10), np.zeros(10)) == 1.0


def test_digital_silence_is_measured_inside_the_piece():
    x = np.concatenate([np.full(SR, 0.1), np.zeros(SR // 2), np.full(SR, 0.1)])
    assert abs(bar.longest_digital_silence(x, SR) - 0.5) < 0.01
    assert bar.longest_digital_silence(np.full(SR, 0.1), SR) == 0.0


def test_ending_drop_tells_a_fade_from_a_hard_stop():
    n = 3 * SR
    tone = 0.3 * np.sin(2 * np.pi * 220 * np.arange(n) / SR)
    faded = tone * np.linspace(1, 0, n)
    assert bar.ending_drop_db(tone, SR) > -6
    assert bar.ending_drop_db(faded, SR) < -18


def test_beat_alignment_scores_cuts_on_and_off_the_grid():
    beats = [i * 0.5 for i in range(40)]
    assert bar.beat_alignment([1.0, 2.0, 3.5], beats, 0.05) == 1.0
    assert bar.beat_alignment([1.2, 2.2, 3.7], beats, 0.05) == 0.0
    assert bar.beat_alignment([], beats, 0.05) == 0.0


def test_an_older_private_config_still_gets_every_limit(monkeypatch):
    monkeypatch.setattr(config, "studio", lambda: {"bar": {"stutter_max": 0.01}})
    limits = bar.limits()
    assert limits["stutter_max"] == 0.01
    assert "voice_to_music_db_max" in limits


def test_voice_to_music_reads_the_gap_while_someone_is_speaking():
    t = np.arange(SR * 2) / SR
    voice = 0.3 * np.sin(2 * np.pi * 220 * t)
    voice[SR:] = 0.0
    music = 0.03 * np.sin(2 * np.pi * 110 * t)
    music[SR:] = 0.3 * np.sin(2 * np.pi * 110 * t[SR:])  # loud only where nobody speaks
    assert abs(bar.voice_to_music_db(voice, music, SR) - 20.0) < 1.0
    assert bar.voice_to_music_db(np.zeros(SR), music[:SR], SR) == 0.0


def test_duplicate_share_finds_held_frames_and_ignores_black():
    rng = np.random.default_rng(14)
    moving = rng.integers(40, 200, (6, 20, 20)).astype(np.uint8)
    held = np.concatenate([moving, np.repeat(moving[-1:], 6, axis=0)])
    assert bar.duplicate_share(moving) == 0.0
    assert bar.duplicate_share(held) > 0.4
    black = np.zeros((5, 20, 20), np.uint8)
    assert bar.duplicate_share(np.concatenate([black, moving, black])) == 0.0


def test_moving_share_reads_runtime_on_footage_not_shot_count():
    em = {
        "duration_sec": 10.0,
        "cuts": [{"source": "a", "start_sec": 0.0}, {"source": "b", "start_sec": 8.0}],
    }
    am = {"assets": [{"id": "a", "kind": "video"}, {"id": "b", "kind": "still"}]}
    assert bar.moving_share(em, am) == 0.8


def test_only_an_objective_defect_blocks_approval():
    report = {
        "readings": [
            {"id": "x", "value": 1, "limit": "<= 0", "ok": False, "blocks": True},
            {"id": "y", "value": 1, "limit": "<= 0", "ok": False, "blocks": False},
            {"id": "z", "value": 0, "limit": "<= 0", "ok": True, "blocks": True},
        ]
    }
    assert [c["status"] for c in bar.as_checks(report)] == ["fail", "warn", "pass"]
