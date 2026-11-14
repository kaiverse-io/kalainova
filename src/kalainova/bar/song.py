"""What can be measured about a song. Candidates, not a verdict.

Reviewed tracks taught two things. Lyric error rate ran against the human verdict: a track accepted
had twice the error of one sent back, because transcribers struggle with singing. And distance from
words to the beat did not separate them either. So words found stands in for error rate, and these
readings warn and pick among takes. They never block a song on taste.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from .. import media
from ..editor import beats
from .readings import Reading, at_least, at_most, summarise
from .sound import (
    clipped_share,
    dc_offset,
    ending_drop_db,
    hard_cuts_per_min,
    longest_digital_silence,
    stereo_correlation,
)

Song = dict[str, Any]
Word = dict[str, Any]
WINDOW_SEC = 8.0
HOP_SEC = 4.0
LOW_BPM, HIGH_BPM = 70.0, 180.0
SHORT_WORD = 3  # "the", "of", and "me" are heard anywhere and prove nothing


def tempo_miss(detected: float, asked: float) -> float:
    """How far a tempo sits from the one asked for. Half or double time counts as the same tempo."""
    if detected <= 0 or asked <= 0:
        return 1.0
    return min(abs(detected * factor / asked - 1.0) for factor in (0.5, 1.0, 2.0))


def _window_tempo(env: np.ndarray, fps: float) -> float | None:
    if env.max(initial=0.0) <= 0:
        return None
    corr = np.correlate(env, env, mode="full")[env.size - 1 :]
    low, high = int(fps * 60 / HIGH_BPM), int(fps * 60 / LOW_BPM)
    if high <= low or corr.size <= high:
        return None
    lag = low + int(np.argmax(corr[low:high]))
    return 60.0 * fps / lag if lag else None


def tempo_drift(env: np.ndarray, fps: float) -> float:
    """How much the tempo wanders across a track, as a share of itself. Near zero holds steady."""
    size, hop = int(WINDOW_SEC * fps), int(HOP_SEC * fps)
    found = [_window_tempo(env[i : i + size], fps) for i in range(0, max(env.size - size, 1), hop)]
    tempi = np.array([t for t in found if t], dtype=np.float64)
    if tempi.size < 2:
        return 0.0
    base = float(np.median(tempi))
    folded = np.array([min((t, t / 2, t * 2), key=lambda v: abs(v - base)) for t in tempi])
    return float(folded.std() / max(folded.mean(), 1e-6))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def lyric_lines(song: Song) -> list[str]:
    return [line for section in song["sections"] for line in section.get("lines") or []]


def words_found(lines: list[str], heard: list[Word]) -> float:
    """Share of a song's distinct words that a listener can pick out."""
    wanted = {t for line in lines for t in _tokens(line) if len(t) > SHORT_WORD}
    if not wanted:
        return 1.0
    got = {t for word in heard for t in _tokens(str(word.get("text", "")))}
    return len(wanted & got) / len(wanted)


def _sound_readings(path: Path) -> list[Reading]:
    left, right, sr = media.decode_stereo(path)
    mono = (left + right) / 2
    return [
        at_most("audio.clipping", clipped_share(mono), "clipped_share_max", blocks=True),
        at_most("audio.dc_offset", dc_offset(mono), "dc_offset_max"),
        at_least("audio.mono_safe", stereo_correlation(left, right), "stereo_correlation_min"),
        at_most("audio.hard_cuts_per_min", hard_cuts_per_min(mono, sr), "hard_cuts_per_min_max"),
        at_most(
            "audio.digital_silence_sec",
            longest_digital_silence(mono[sr // 4 : -sr // 4], sr),
            "digital_silence_sec_max",
        ),
        at_most("audio.ending_drop_db", ending_drop_db(mono, sr), "ending_drop_db_max"),
    ]


def _tempo_readings(path: Path, song: Song) -> list[Reading]:
    env = beats.onset_envelope(beats._pcm(path))
    fps = beats.SR / beats.HOP
    out = [at_most("song.tempo_drift", tempo_drift(env, fps), "song_tempo_drift_max")]
    if song.get("bpm"):
        detected = float(beats.beat_grid(path)["bpm"])
        miss = tempo_miss(detected, float(song["bpm"]))
        out.append(at_most("song.tempo", miss, "song_tempo_tolerance"))
    return out


def measure(path: Path, song: Song, heard: list[Word] | None) -> dict[str, Any]:
    """A take's readings. A reading that needs a transcript waits until there is one."""
    readings: list[Reading] = [*_sound_readings(path), *_tempo_readings(path, song)]
    duration = media.duration(path)
    if song.get("duration_sec"):
        miss = abs(duration / float(song["duration_sec"]) - 1.0)
        readings.append(at_most("song.length", miss, "song_length_tolerance"))
    lra = media.loudness(path).get("loudness_range_lu")
    if lra is not None:
        readings.append(at_least("song.shape", float(lra), "song_range_lu_min"))
    if heard is not None and not song.get("instrumental"):
        found = words_found(lyric_lines(song), heard)
        readings.append(at_least("song.words_found", found, "song_words_found_min"))
    return summarise([asdict(r) for r in readings])


def score(report: dict[str, Any]) -> float:
    """For choosing among takes: how many readings it meets, then how well the words carry."""
    met = report["met"] / max(report["total"], 1)
    words = next((r["value"] for r in report["readings"] if r["id"] == "song.words_found"), 0.0)
    return float(round(met + 0.25 * float(words), 4))


def master_readings(path: Path, target: float, ceiling: float) -> list[dict[str, Any]]:
    """The finished file against its own targets. These do block: a wrong level is not taste."""
    loud = media.loudness(path)
    level, peak = loud["integrated_lufs"], loud["true_peak_dbtp"]
    readings = [
        Reading(
            "song.loudness",
            level,
            f"{target:g} +/- 1",
            level is not None and abs(level - target) <= 1,
            True,
        ),
        Reading(
            "song.true_peak",
            peak,
            f"<= {ceiling:g}",
            peak is not None and peak <= ceiling + 0.3,
            True,
        ),
    ]
    return [asdict(r) for r in readings]
