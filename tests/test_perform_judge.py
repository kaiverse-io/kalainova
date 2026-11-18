"""The performance judge: head, eyes, and a person's movement apart from the background, read
without the face and person models (they run only in the judge's own environment)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace as P

import numpy as np
import pytest

RUNNER = Path(__file__).resolve().parents[1] / "src/kalainova/providers/runners/perform_run.py"


def _runner():
    spec = importlib.util.spec_from_file_location("perform_run", RUNNER)
    module = importlib.util.module_from_spec(spec)
    sys.modules["perform_run"] = module  # its dataclass looks itself up by module name
    spec.loader.exec_module(module)  # the engine never imports a runner; a test reads it as a file
    return module


def test_a_face_looking_straight_ahead_has_no_turn_nod_or_tilt():
    run = _runner()
    assert run.pose(np.eye(4)) == pytest.approx((0.0, 0.0, 0.0))
    turn = np.radians(20)
    yawed = np.array([[np.cos(turn), 0, np.sin(turn)], [0, 1, 0], [-np.sin(turn), 0, np.cos(turn)]])
    assert run.pose(yawed)[0] == pytest.approx(20.0)


def test_where_the_iris_sits_is_measured_in_eye_widths_not_by_how_open_the_lids_are():
    run = _runner()
    eye = {33: P(x=0.6, y=0.5), 133: P(x=0.4, y=0.5), 468: P(x=0.55, y=0.5)}
    across, down = run.eye_ratio(eye, (33, 133, 0, 0, 468))
    assert across == pytest.approx(0.25) and down == pytest.approx(0.0)
    flat = {33: P(x=0.5, y=0.5), 133: P(x=0.5, y=0.5), 468: P(x=0.5, y=0.5)}
    assert run.eye_ratio(flat, (33, 133, 0, 0, 468)) is None, "no width, no reading"


def test_the_cameras_movement_is_taken_out_of_the_persons_and_the_backgrounds():
    run = _runner()
    flow = np.zeros((20, 20, 2))
    flow[..., 0] = 2.0  # the whole frame pans right by two pixels
    mask = np.zeros((20, 20), dtype=bool)
    mask[5:15, 5:15] = True
    flow[5:15, 5:15, 1] = 3.0  # and the person also moves down by three
    camera, subject, background = run.split_flow(flow, mask, diagonal=10.0, fps=10.0)
    assert camera == pytest.approx(2.0) and background == pytest.approx(0.0)
    assert subject == pytest.approx(3.0), "the pan is the camera's, not the person's"


def test_a_blink_is_counted_once_however_long_the_eye_stays_shut():
    run = _runner()
    shut = [0.1] * 10 + [0.9] * 5 + [0.1] * 10 + [0.9] * 2 + [0.1] * 3
    assert run.blinks_per_min(shut, fps=30.0) == pytest.approx(2 * 60.0)


def test_face_readings_are_left_out_when_the_face_is_seldom_found():
    run = _runner()
    seldom = run.Track(fps=25.0, frames=10, yaw=[1.0] + [float("nan")] * 9)
    seldom.subject = [0.01] * 9
    found = run.score(seldom)
    assert found["face_share"] == pytest.approx(0.1) and "head_yaw_range" not in found
    assert found["subject_motion"] == pytest.approx(0.01), "the body still reads without a face"
