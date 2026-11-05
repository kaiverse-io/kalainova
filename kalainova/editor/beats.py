"""Music beat grid from audio, so cuts land on the beat.

Spectral-flux onset envelope -> tempo by autocorrelation (70-180 BPM) -> beat phase that best
aligns with the onsets. Good enough for cut placement; not a DJ tool.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .. import media

SR, HOP, WIN = 22050, 512, 2048


def _pcm(path: Path) -> np.ndarray:
    proc = subprocess.run([media.FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(path), "-ac", "1",
                           "-ar", str(SR), "-f", "s16le", "-"], capture_output=True)
    return np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768


def onset_envelope(x: np.ndarray) -> np.ndarray:
    if x.size < WIN:
        return np.zeros(1)
    n = 1 + (x.size - WIN) // HOP
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(x[idx] * np.hanning(WIN), axis=1))
    spec = np.log1p(spec)
    flux = np.maximum(np.diff(spec, axis=0), 0).sum(axis=1)
    flux = np.concatenate([[0], flux])
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")
    return np.maximum(flux, 0)


def beat_grid(path: Path, duration: float | None = None) -> dict:
    x = _pcm(path)
    env = onset_envelope(x)
    fps = SR / HOP
    dur = duration or x.size / SR
    if env.max() <= 0:
        bpm = 120.0
        return {"bpm": bpm, "beats": list(np.arange(0, dur, 60 / bpm).round(3)), "confidence": 0.0}
    ac = np.correlate(env, env, mode="full")[env.size - 1:]
    lags = np.arange(ac.size) / fps
    valid = (lags >= 60 / 180) & (lags <= 60 / 70)
    # prefer tempi near 110 BPM a little, to avoid octave errors
    weight = np.exp(-0.5 * (np.log2(np.where(lags > 0, 60 / np.maximum(lags, 1e-6), 1) / 110) / 0.9) ** 2)
    cand = np.where(valid, ac * weight, 0)
    lag = int(np.argmax(cand))
    period = lag / fps
    bpm = 60 / period if period else 120.0
    # phase: the offset whose comb sums the most onset energy
    best, phase = -1.0, 0.0
    for off in np.arange(0, period, 1 / fps):
        ticks = (np.arange(off, dur, period) * fps).astype(int)
        ticks = ticks[ticks < env.size]
        sc = env[ticks].sum()
        if sc > best:
            best, phase = sc, off
    beats = np.arange(phase, dur, period)
    conf = float(min(1.0, ac[lag] / (ac[0] + 1e-9) * 2))
    return {"bpm": round(float(bpm), 2), "beats": beats.round(3).tolist(), "confidence": round(conf, 3)}
