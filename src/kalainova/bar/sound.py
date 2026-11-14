"""What samples alone can say: clipping, offset, mono safety, hard cuts, silence, a dropped ending.

Every signal here is a pure function over arrays, so it can be proved on synthetic audio with a
known answer.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt

Arr = npt.NDArray[Any]

HARD_CUT_DROP_DB = 28.0


SPEECH_FLOOR_DB = -36.0


SILENCE_EPS = 1.0 / 32768


def _db(x: float) -> float:
    return float(20 * np.log10(max(x, 1e-9)))


# ------------------------------------------------------------------ sound signals
def _envelope_db(x: Arr, sr: int, hop_ms: float = 5.0) -> Arr:
    hop = max(int(sr * hop_ms / 1000), 1)
    n = x.size // hop
    if n == 0:
        return np.zeros(0)
    rms = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    return 20 * np.log10(np.maximum(rms, 1e-9))


def hard_cuts_per_min(x: Arr, sr: int) -> float:
    """Sound that stops dead from speech level. Natural speech decays; a chopped edit does not."""
    env = _envelope_db(x, sr)
    if env.size < 8:
        return 0.0
    now, before, after = env[4:-2], env[:-6], env[6:]
    # Still at full level 20 ms earlier, and gone 10 ms later. A decay has already started by then.
    hit = (now > SPEECH_FLOOR_DB) & (now >= before - 6.0) & (after < now - HARD_CUT_DROP_DB)
    events = np.count_nonzero(np.diff(hit.astype(np.int8)) == 1)
    return events / max(x.size / sr / 60, 1e-6)


def voice_to_music_db(voice: Arr, music: Arr, sr: int) -> float:
    """How far the music sits under the voice, measured only where someone is speaking."""
    hop = max(sr // 10, 1)
    n = min(voice.size, music.size) // hop
    if n == 0:
        return 0.0
    v = np.sqrt((voice[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    m = np.sqrt((music[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    speaking = v > 10 ** (SPEECH_FLOOR_DB / 20)
    if not speaking.any():
        return 0.0
    return float(np.median(20 * np.log10(v[speaking] / np.maximum(m[speaking], 1e-9))))


def clipped_share(x: Arr) -> float:
    """Share of samples in runs of three or more at full scale."""
    hot = np.abs(x) >= 0.9995
    if x.size < 3:
        return 0.0
    run = hot[:-2] & hot[1:-1] & hot[2:]
    return float(run.mean())


def dc_offset(x: Arr) -> float:
    return float(abs(x.mean())) if x.size else 0.0


def stereo_correlation(left: Arr, right: Arr) -> float:
    """1 is identical, 0 unrelated, -1 cancels to nothing on a phone speaker."""
    if left.std() == 0 or right.std() == 0:
        return 1.0
    return float(np.corrcoef(left, right)[0, 1])


def longest_digital_silence(x: Arr, sr: int) -> float:
    """Longest run of true digital zero inside the piece. Real rooms are never silent."""
    quiet = np.concatenate([[False], np.abs(x) < SILENCE_EPS, [False]])
    edges = np.flatnonzero(quiet[1:] != quiet[:-1])
    if edges.size < 2:
        return 0.0
    return float((edges[1::2] - edges[::2]).max() / sr)


def ending_drop_db(x: Arr, sr: int) -> float:
    """Level of the last 100 ms against the loudest of the last 3 s. Near 0 is a hard stop."""
    tail = x[-3 * sr :]
    last = tail[-sr // 10 :]
    if tail.size == 0 or last.size == 0:
        return 0.0
    win = max(sr // 10, 1)
    n = tail.size // win
    peak = float(np.sqrt((tail[: n * win].reshape(n, win) ** 2).mean(axis=1)).max()) if n else 0.0
    return _db(float(np.sqrt((last**2).mean()))) - _db(peak)


def beat_alignment(cuts: Sequence[float], beats: Sequence[float], tolerance: float) -> float:
    """Share of cuts that land on a beat."""
    if not cuts or not beats:
        return 0.0
    grid = np.array(beats)
    return float(np.mean([np.abs(grid - c).min() <= tolerance for c in cuts]))


def pitch_snapping(voice: Arr, sr: int) -> float:
    """Share of voiced frames quantized to chromatic semitones (staircase autotune pattern)."""
    win = max(int(sr * 0.04), 16)
    hop = max(int(sr * 0.02), 8)
    n = (voice.size - win) // hop
    if n <= 0:
        return 0.0

    min_lag = max(int(sr / 800), 2)  # 800 Hz upper bound
    max_lag = min(int(sr / 60), win - 1)  # 60 Hz lower bound
    if max_lag <= min_lag:
        return 0.0

    voiced_snapped = 0
    total_voiced = 0

    for i in range(n):
        frame = voice[i * hop : i * hop + win]
        rms = float(np.sqrt(np.mean(frame**2)))
        if rms < 0.01:
            continue
        corr = np.correlate(frame, frame, mode="full")[win - 1 :]
        if corr[0] <= 1e-9:
            continue
        norm_corr = corr[min_lag:max_lag] / corr[0]
        peak_idx = int(np.argmax(norm_corr))
        peak_val = float(norm_corr[peak_idx])
        if peak_val > 0.45:
            # Sub-sample parabolic interpolation for precise fundamental frequency
            lag_f = float(min_lag + peak_idx)
            if 0 < peak_idx < len(norm_corr) - 1:
                alpha = float(norm_corr[peak_idx - 1])
                beta = peak_val
                gamma = float(norm_corr[peak_idx + 1])
                denom = alpha - 2 * beta + gamma
                if abs(denom) > 1e-9:
                    lag_f += 0.5 * (alpha - gamma) / denom
            f0 = sr / max(lag_f, 1e-6)
            midi = 69.0 + 12.0 * np.log2(max(f0, 1.0) / 440.0)
            dev = abs(midi - round(midi))
            if dev < 0.10:  # within ~10 cents of exact chromatic pitch
                voiced_snapped += 1
            total_voiced += 1

    return float(voiced_snapped / total_voiced) if total_voiced > 5 else 0.0


def groove_steadiness(x: Arr, sr: int) -> float:
    """Steadiness of rhythmic onsets across the track (1.0 is metronome steady, <0.7 is erratic)."""
    hop = max(int(sr * 0.01), 1)
    n = x.size // hop
    if n < 100:
        return 1.0
    env = np.sqrt((x[: n * hop].reshape(n, hop) ** 2).mean(axis=1))
    diff = np.maximum(0, np.diff(env))
    if diff.max(initial=0.0) <= 1e-6:
        return 1.0
    threshold = 0.3 * diff.max()
    is_peak = (diff[1:-1] > diff[:-2]) & (diff[1:-1] > diff[2:]) & (diff[1:-1] > threshold)
    peaks = np.flatnonzero(is_peak)
    if peaks.size < 4:
        return 1.0
    intervals = np.diff(peaks) * (hop / sr)
    med = float(np.median(intervals))
    if med <= 0:
        return 1.0
    cv = float(intervals.std() / med)
    return float(max(0.0, min(1.0, 1.0 - cv * 0.5)))


def mix_balance(left: Arr, right: Arr, sr: int) -> dict[str, float]:
    """Spectral distribution, crest factor, and stereo width across the track."""
    mono = (left + right) / 2
    if mono.size == 0 or float(np.sqrt(np.mean(mono**2))) < 1e-7:
        return {
            "crest_factor_db": 0.0,
            "stereo_width": 0.0,
            "spectral_low": 0.0,
            "spectral_mid": 1.0,
            "spectral_high": 0.0,
        }

    peak = float(np.abs(mono).max())
    rms = float(np.sqrt(np.mean(mono**2)))
    crest = 20 * np.log10(max(peak, 1e-9) / max(rms, 1e-9))

    # Spectral balance via rfft
    n = min(mono.size, 1 << 18)
    segment = mono[:n] * np.hanning(n)
    power = np.abs(np.fft.rfft(segment)) ** 2
    freqs = np.fft.rfftfreq(n, 1.0 / sr)

    low_mask = freqs < 250
    mid_mask = (freqs >= 250) & (freqs < 4000)
    high_mask = freqs >= 4000
    total = float(power.sum()) or 1.0

    low_share = float(power[low_mask].sum() / total)
    mid_share = float(power[mid_mask].sum() / total)
    high_share = float(power[high_mask].sum() / total)

    corr = stereo_correlation(left, right)
    width = float(max(0.0, min(1.0, 1.0 - max(0.0, corr))))

    return {
        "crest_factor_db": round(crest, 2),
        "stereo_width": round(width, 3),
        "spectral_low": round(low_share, 3),
        "spectral_mid": round(mid_share, 3),
        "spectral_high": round(high_share, 3),
    }
