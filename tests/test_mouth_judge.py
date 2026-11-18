"""The mouth-against-voice judge: its lag and correlation, without the face model it reads with."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

RUNNER = Path(__file__).resolve().parents[1] / "src/kalainova/providers/runners/mouth_run.py"


def _runner():
    spec = importlib.util.spec_from_file_location("mouth_run", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # the engine never imports a runner; a test reads it as a file
    return module


def test_a_mouth_that_opens_three_frames_after_the_voice_reads_as_late_by_three():
    run = _runner()
    rng = np.random.default_rng(7)
    voice = rng.normal(size=100)
    mouth = np.concatenate([np.zeros(3), voice[:-3]])  # the same shape, three frames later
    found = run.best_lag(mouth, voice, fps=25.0)
    assert found["lag"] == 3.0 and found["lag_sec"] == pytest.approx(0.12)
    assert found["corr"] > 0.95 and found["corr_at_0"] < 0.5


def test_a_mouth_that_ignores_the_voice_reads_low_and_missing_frames_are_skipped():
    run = _runner()
    rng = np.random.default_rng(8)
    voice, mouth = rng.normal(size=100), rng.normal(size=100)
    mouth[::7] = np.nan  # frames where the face was not found
    found = run.best_lag(mouth, voice, fps=25.0)
    assert abs(found["corr"]) < 0.35
    assert found["face_share"] == pytest.approx(np.mean(~np.isnan(mouth)), abs=1e-3)


def test_a_mouth_that_never_moves_cannot_be_scored():
    run = _runner()
    assert run.best_lag(np.ones(50), np.arange(50.0), fps=25.0) is None
