"""The studio bar's signals, each proved on synthetic media with a known answer."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageFilter

from kalainova import bar, config, media, mediascan

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


# ------------------------------------------------------------------ what moves inside a shot
MOTION_FPS = 24.0
MOTION_LIMIT = config.bar_limits()["shot_motion_min"]


def _scene(seed: int = 7, h: int = 180, w: int = 320, grain: int = 24) -> np.ndarray:
    """Edges at several scales, the way a photograph has them."""
    rng = np.random.default_rng(seed)
    coarse = np.kron(
        rng.uniform(30, 220, (h // grain + 2, w // grain + 2)), np.ones((grain, grain))
    )
    fine = np.kron(rng.uniform(-30, 30, (h // 4 + 2, w // 4 + 2)), np.ones((4, 4)))
    return np.clip(coarse[:h, :w] + fine[:h, :w], 0, 255)


def _clip(frame_at, seconds: float = 2.0) -> np.ndarray:
    return (
        np.array([frame_at(i) for i in range(int(seconds * MOTION_FPS))], dtype=np.float64)
        .clip(0, 255)
        .astype(np.uint8)
    )


def test_a_frozen_shot_with_nothing_moving_reads_as_still():
    scene = _scene()
    assert bar.shot_motion(_clip(lambda _: scene), MOTION_FPS) == 0.0


@pytest.mark.parametrize(
    "window",
    [
        lambda big, i: big[50:230, i : i + 320],  # the camera moves one way
        lambda big, i: big[50:230, 100 - i : 420 - i],  # and back
        lambda big, i: big[i : i + 180, 50:370],  # up
        lambda big, i: big[60 - i : 240 - i, 50:370],  # and down
    ],
)
def test_a_camera_move_across_a_frozen_picture_is_not_motion(window):
    big = _scene(h=280, w=480)
    move = _clip(lambda i: window(big, i))
    assert np.abs(np.diff(move.astype(np.int16), axis=0)).mean() > 2  # plenty changes each frame
    assert bar.shot_motion(move, MOTION_FPS) < MOTION_LIMIT


def _pushed(rate: float, drift: float = 0.0, wide: np.ndarray | None = None, soften: float = 0.0):
    """A camera pushing in on a frozen picture, and drifting, sampled the way a renderer samples."""
    source = _scene(h=280, w=480) if wide is None else wide
    picture = Image.fromarray(source.astype(np.uint8)).filter(ImageFilter.GaussianBlur(soften))

    def frame(i: int) -> np.ndarray:
        shrink = 1.0 / (1.0 + rate * i / MOTION_FPS)
        left, top = 240 + drift * i - 160 * shrink, 140 - 90 * shrink
        box = (shrink, 0, left, 0, shrink, top)
        return np.asarray(picture.transform((320, 180), Image.AFFINE, box, Image.BILINEAR))

    return _clip(frame)


# The slow push a film holds a whole shot, a stills camera move, and the 5.7% a second a
# model gave a generated shot in which nothing else moved.
@pytest.mark.parametrize("rate", [0.012, 0.03, 0.06])
@pytest.mark.parametrize("soften", [0.0, 1.0, 3.0], ids=["sharp", "soft", "fog"])
def test_a_push_in_on_a_frozen_picture_is_not_motion(rate, soften):
    pushed = _pushed(rate, soften=soften)
    assert bar.shot_motion(pushed, MOTION_FPS) < MOTION_LIMIT / 2


@pytest.mark.parametrize("soften", [0.0, 1.0, 3.0], ids=["sharp", "soft", "fog"])
def test_a_push_in_that_also_drifts_is_not_motion(soften):
    pushed = _pushed(0.03, drift=0.5, soften=soften)
    assert bar.shot_motion(pushed, MOTION_FPS) < MOTION_LIMIT / 2


def test_a_pushed_clip_measures_real_change_before_the_camera_is_taken_out():
    # without this, the two tests above would pass on a clip that barely changes
    pushed = _pushed(0.06, soften=1.0).astype(np.int16)
    assert np.abs(pushed[-1] - pushed[0]).mean() > 5


def test_a_push_in_over_moving_water_still_counts_the_water():
    pushed = _pushed(0.03)
    pushed[:, 90:] = np.array([_scene(seed=100 + i)[90:] for i in range(len(pushed))]).astype(
        np.uint8
    )
    assert bar.shot_motion(pushed, MOTION_FPS) > MOTION_LIMIT


def test_a_picture_that_changes_completely_every_frame_reads_as_moving():
    assert bar.shot_motion(_clip(lambda i: _scene(seed=i)), MOTION_FPS) > 0.5


def test_a_flat_frame_reads_as_still_rather_than_failing():
    flat = np.full((180, 320), 90.0)
    assert bar.shot_motion(_clip(lambda _: flat), MOTION_FPS) == 0.0


def test_a_push_in_on_detail_at_one_side_of_a_flat_sky_is_not_motion():
    wide = _scene(h=280, w=480)
    wide[:140] = 90.0  # a flat sky: nothing up here can say where the camera went
    wide[:, :240] = 90.0
    assert bar.shot_motion(_pushed(0.06, wide=wide), MOTION_FPS) < MOTION_LIMIT


def test_a_large_object_moving_on_its_own_does_not_throw_the_camera_fit():
    scene, boat = _scene(), _scene(seed=9, h=90, w=120)

    def shot(i: int) -> np.ndarray:
        frame = scene.copy()
        frame[50:140, 20 + 3 * i : 140 + 3 * i] = boat
        return frame

    # a fifth of the frame moved; had it dragged the fit, the whole frame would read as changed
    assert 0.1 < bar.shot_motion(_clip(shot), MOTION_FPS) < 0.35


def test_a_large_object_moving_during_a_push_in_does_not_throw_the_camera_fit():
    pushed, boat = _pushed(0.06), _scene(seed=9, h=90, w=120).astype(np.uint8)
    for i, frame in enumerate(pushed):
        frame[50:140, 20 + 3 * i : 140 + 3 * i] = boat
    assert 0.1 < bar.shot_motion(pushed, MOTION_FPS) < 0.35


def test_a_peak_between_samples_is_found_to_a_fraction_of_a_sample():
    parabola = -((np.arange(8.0) - 3.3) ** 2)
    assert bar.motion._peak_offset(parabola, 3) == pytest.approx(0.3)


def test_a_source_slower_than_the_measuring_step_can_still_be_read():
    frames = _clip(lambda _: _scene(), seconds=0.5)
    assert bar.shot_motion(frames, 1.0) == 0.0


def test_exactly_one_step_of_frames_is_too_few_to_compare():
    frames = _clip(lambda _: _scene(), seconds=1.0)
    step = round(bar.MOTION_STEP_SEC * MOTION_FPS)
    assert bar.shot_motion(frames[:step], MOTION_FPS) is None
    assert bar.shot_motion(frames[: step + 1], MOTION_FPS) == 0.0


def _still_then_moving(path) -> None:
    media.run(
        [
            "-f", "lavfi", "-i", "smptebars=size=320x180:rate=24:duration=3",
            "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24:duration=1.5",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]",
            "-map", "[v]", "-pix_fmt", "yuv420p", str(path),
        ]
    )  # fmt: skip


def test_only_the_part_of_a_clip_the_edit_uses_is_read(tmp_path):
    _still_then_moving(tmp_path / "clip.mp4")
    am = {"assets": [{"id": "c", "kind": "video", "path": "clip.mp4", "synthetic": True}]}

    def read(**cut) -> float:
        return bar.sources._generated_shots(tmp_path, {"cuts": [{"source": "c", **cut}]}, am)["c"]

    # compared with each other, because an encoder build moves the moving part's reading
    whole_clip = read()
    assert read(in_sec=0.6, out_sec=2.4) < MOTION_LIMIT  # stops before the clip starts moving
    assert read(in_sec=3.1, out_sec=4.4) > whole_clip  # leaves the still part out
    assert read(in_sec=3.1) > whole_clip  # no end named: runs to the end of the clip


def test_a_move_too_far_for_any_camera_is_not_taken_out():
    swing = _scene(w=1400)
    whip = _clip(lambda i: swing[:, 20 * i : 20 * i + 320])
    assert bar.shot_motion(whip, MOTION_FPS) > MOTION_LIMIT


def test_film_grain_over_a_frozen_picture_is_not_motion():
    scene, rng = _scene(), np.random.default_rng(3)
    grainy = _clip(lambda _: scene + rng.normal(0, 2.0, scene.shape))
    assert bar.shot_motion(grainy, MOTION_FPS) < MOTION_LIMIT


def test_water_moving_under_a_still_sky_reads_as_the_share_of_the_frame_that_moves():
    sky = _scene(seed=1)

    def shot(i: int) -> np.ndarray:
        frame = sky.copy()
        frame[90:] = _scene(seed=100 + i)[90:]
        return frame

    assert 0.3 < bar.shot_motion(_clip(shot), MOTION_FPS) <= 0.5


def test_a_pan_over_moving_water_still_counts_the_water():
    wide = _scene(seed=1, w=640)

    def shot(i: int) -> np.ndarray:
        frame = wide[:, i : i + 320].copy()
        frame[90:] = _scene(seed=100 + i)[90:]
        return frame

    assert bar.shot_motion(_clip(shot), MOTION_FPS) > MOTION_LIMIT


def test_a_clip_too_short_to_measure_reads_as_unknown_not_still():
    assert bar.shot_motion(_clip(lambda _: _scene(), seconds=0.1), MOTION_FPS) is None


def _make_clip(path, source: str) -> None:
    media.run(
        ["-f", "lavfi", "-i", source, "-t", "1.5", "-r", "24", "-pix_fmt", "yuv420p", str(path)]
    )


def _two_shot_job(tmp_path, *, frozen_is_generated: bool = True):
    _make_clip(tmp_path / "moving.mp4", "testsrc2=size=320x180:rate=24")
    _make_clip(tmp_path / "frozen.mp4", "smptebars=size=320x180:rate=24")
    media.run(["-i", str(tmp_path / "moving.mp4"), "-c", "copy", str(tmp_path / "final.mp4")])
    frozen = {"id": "b2.video", "kind": "video", "path": "frozen.mp4"}
    am = {
        "assets": [
            {"id": "b1.video", "kind": "video", "path": "moving.mp4", "synthetic": True},
            {**frozen, "synthetic": frozen_is_generated},
        ]
    }
    em = {
        "duration_sec": 3.0,
        "profile": {"width": 320, "height": 180, "fps": 24.0},
        "cuts": [
            {"source": "b1.video", "start_sec": 0.0, "in_sec": 0.0, "out_sec": 1.5},
            {"source": "b2.video", "start_sec": 1.5, "in_sec": 0.0, "out_sec": 1.5},
        ],
    }
    return bar.measure_job(tmp_path, em, am)


def _reading(report, rid):
    return next((r for r in report["readings"] if r["id"] == rid), None)


def test_a_job_with_a_generated_clip_that_never_moves_misses_and_names_the_shot(tmp_path):
    reading = _reading(_two_shot_job(tmp_path), "source.shot_motion")
    assert reading is not None
    assert not reading["ok"]
    assert "b2.video" in reading["value"]


def test_a_quiet_shot_of_real_footage_is_the_editors_choice(tmp_path):
    reading = _reading(_two_shot_job(tmp_path, frozen_is_generated=False), "source.shot_motion")
    assert reading is not None
    assert reading["ok"]
    assert "b1.video" in reading["value"]


def test_a_stamp_shared_by_the_stills_a_piece_uses_is_read_from_the_sources(tmp_path):
    names = ["a.png", "b.png", "c.png", "unused.png"]
    for name in names:
        Image.linear_gradient("L").resize((640, 360)).convert("RGB").save(tmp_path / name)
    assets = [{"id": n, "kind": "still", "path": n} for n in names]
    em = {
        "profile": {"width": 640, "height": 360},
        "duration_sec": 3.0,
        "cuts": [{"source": n, "start_sec": float(i)} for i, n in enumerate(names[:3])],
    }
    found = {r.id: r for r in bar.sources.source_readings(tmp_path, em, {"assets": assets})}
    assert found["source.scale"].value == 1.0
    assert "source.corner_mark" in found
    assert found["edit.moving_share"].ok is False, "three stills and no footage"


def test_with_too_few_stills_no_stamp_can_be_told_from_the_picture(tmp_path):
    Image.linear_gradient("L").save(tmp_path / "a.png")
    assets = [{"id": "a.png", "kind": "still", "path": "a.png"}]
    em = {"profile": {}, "duration_sec": 1.0, "cuts": [{"source": "a.png", "start_sec": 0.0}]}
    found = {r.id for r in bar.sources.source_readings(tmp_path, em, {"assets": assets})}
    assert "source.corner_mark" not in found


def test_with_no_banding_filter_the_reading_is_left_out(monkeypatch, tmp_path):
    monkeypatch.setattr(mediascan, "has_filter", lambda name: False)
    assert mediascan.cambi(tmp_path / "any.mp4") is None


def test_a_banding_run_that_fails_reads_as_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(mediascan, "has_filter", lambda name: True)
    assert mediascan.cambi(tmp_path / "missing.mp4") is None
