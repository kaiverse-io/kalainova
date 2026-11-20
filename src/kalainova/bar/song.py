"""What can be measured about a song. Candidates, not a verdict.

Reviewed tracks taught two things. Lyric error rate ran against the human verdict: a track accepted
had twice the error of one sent back, because transcribers struggle with singing. And distance from
words to the beat did not separate them either. So words found stands in for error rate, and these
readings warn and pick among takes. They never block a song on taste.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from .. import media
from ..editor import beats
from . import plan
from .readings import Reading, at_least, at_most, summarise
from .sound import (
    clipped_share,
    dc_offset,
    ending_drop_db,
    groove_steadiness,
    hard_cuts_per_min,
    longest_digital_silence,
    mix_balance,
    pitch_snapping,
    stereo_correlation,
)

Song = dict[str, Any]
Word = dict[str, Any]
WINDOW_SEC = 8.0
HOP_SEC = 4.0
LOW_BPM, HIGH_BPM = 70.0, 180.0
SHORT_WORD = 3  # "the", "of", and "me" are heard anywhere and prove nothing
STEM_HEARD = ".vocals.heard.json"  # beside a take: what was heard of its vocal stem alone
MIX_HEARD = ".heard.json"  # beside a take: what was heard of the take itself
# What one window's tempo can be mistaken for: half or double time, and the 3:2 and 4:3 of dotted
# and triplet figures, which dance percussion can put in more than half the windows of a steady
# take (a 126 bpm take read 83.8 in 27 of 44 windows, and 169.8 in 3).
METRIC_FOLDS = (0.5, 2 / 3, 0.75, 1.0, 4 / 3, 1.5, 2.0)
MAD_TO_SD = 1.4826  # the median absolute deviation of a normal spread, as its standard deviation


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
    if high <= low or corr.size <= high + 1:
        return None
    lag = float(low + int(np.argmax(corr[low:high])))
    # between frames: a whole-frame lag at 43 frames a second reads 126 bpm only as 123 or 129
    a, b, c = corr[int(lag) - 1], corr[int(lag)], corr[int(lag) + 1]
    bend = a - 2 * b + c
    if bend < 0:
        lag += float(np.clip(0.5 * (a - c) / bend, -0.5, 0.5))
    return 60.0 * fps / lag if lag else None


def tempo_drift(env: np.ndarray, fps: float, base: float | None = None) -> float:
    """How much the tempo wanders across a track, as a share of itself. Near zero holds steady.

    Each window's tempo is read as the metric relation nearest `base` (the tempo asked for, when
    there is one), so a window that locks onto a 3:2 figure is not counted as drift. The spread is
    robust (from the median absolute deviation), so a few misread windows cannot pass for drift,
    while a tempo that really wanders moves most windows and still reads."""
    size, hop = int(WINDOW_SEC * fps), int(HOP_SEC * fps)
    found = [_window_tempo(env[i : i + size], fps) for i in range(0, max(env.size - size, 1), hop)]
    tempi = np.array([t for t in found if t], dtype=np.float64)
    if tempi.size < 2:
        return 0.0
    anchor = float(base) if base else float(np.median(tempi))
    folded = np.array(
        [min((t * f for f in METRIC_FOLDS), key=lambda v: abs(v - anchor)) for t in tempi]
    )
    centre = float(np.median(folded))
    spread = MAD_TO_SD * float(np.median(np.abs(folded - centre)))
    return spread / max(centre, 1e-6)


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


def chorus_heard(song: Song, heard: list[Word]) -> float | None:
    """Share of the chorus's lines a listener picks out at least half of, anywhere in the take:
    a song whose hook is never heard is not the song asked for. None when no section is a chorus."""
    lines = [
        line
        for section in song["sections"]
        if section.get("kind") in ("chorus", "hook")
        for line in section.get("lines") or []
    ]
    if not lines:
        return None
    got = {t for word in heard for t in _tokens(str(word.get("text", "")))}
    found = 0
    for line in dict.fromkeys(lines):
        wanted = {t for t in _tokens(line) if len(t) > SHORT_WORD}
        found += bool(wanted) and len(wanted & got) * 2 >= len(wanted)
    return found / len(dict.fromkeys(lines))


def _sound_readings(path: Path) -> list[Reading]:
    left, right, sr = media.decode_stereo(path)
    mono = (left + right) / 2
    mix = mix_balance(left, right, sr)
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
        at_least(
            "audio.groove_steadiness", groove_steadiness(mono, sr), "audio_groove_steadiness_min"
        ),
        at_most("audio.pitch_snapping", pitch_snapping(mono, sr), "audio_pitch_snapping_max"),
        at_least("audio.crest_factor", mix["crest_factor_db"], "audio_crest_factor_min"),
        at_least("audio.stereo_width", mix["stereo_width"], "audio_stereo_width_min"),
    ]


def _tempo_readings(path: Path, song: Song) -> list[Reading]:
    env = beats.onset_envelope(beats._pcm(path))
    fps = beats.SR / beats.HOP
    asked = float(song.get("bpm") or 0) or None
    out = [at_most("song.tempo_drift", tempo_drift(env, fps, asked), "song_tempo_drift_max")]
    if song.get("bpm"):
        detected = float(beats.beat_grid(path)["bpm"])
        miss = tempo_miss(detected, float(song["bpm"]))
        out.append(at_most("song.tempo", miss, "song_tempo_tolerance"))
    return out


def section_spans(song: Song) -> list[tuple[float, float]]:
    """Where each section was asked to sit, in seconds (plan.spans)."""
    return plan.spans(song)


INTRO_SEC = 15.0  # the opening a song without bars is read by, against its loudest stretch


def intro_rise(path: Path, song: Song) -> float | None:
    """How far below the song's loudest section its intro plays, in dB (0 when the intro is the
    loudest). A take asked for a soft start that opens at full level reads near 0. Without bars to
    place the sections, its first 15 s against its loudest 15 s. None without an intro first."""
    sections = song.get("sections") or []
    if not sections or str(sections[0].get("kind")) != "intro":
        return None
    pcm = beats._pcm(path)

    def level(a: float, b: float) -> float:
        part = pcm[int(a * beats.SR) : int(b * beats.SR)]
        return float(20 * np.log10(np.sqrt(np.mean(part**2)) + 1e-9)) if part.size else -120.0

    spans = section_spans(song)
    if not spans:
        end = pcm.size / beats.SR
        starts = np.arange(0.0, max(end - INTRO_SEC, 0.0) + 1e-9, INTRO_SEC / 3)
        spans = [(float(a), float(a) + INTRO_SEC) for a in starts]
    levels = [level(a, b) for a, b in spans]
    return round(levels[0] - max(levels), 2)


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
    rise = intro_rise(path, song)
    if rise is not None:
        readings.append(at_most("song.intro_rise", rise, "song_intro_below_loudest_db"))
    readings += _plan_readings(path, song)
    if heard is not None and not song.get("instrumental"):
        found = words_found(lyric_lines(song), heard)
        readings.append(at_least("song.words_found", found, "song_words_found_min"))
        chorus = chorus_heard(song, heard)
        if chorus is not None:
            readings.append(at_least("song.chorus_heard", chorus, "song_chorus_heard_min"))
    return summarise([asdict(r) for r in readings])


def _plan_readings(path: Path, song: Song) -> list[Reading]:
    """Whether the take kept its own plan: its energy arc against each section's planned energy
    (Spearman's rho) and its key against the key asked (1 the same, 0.5 the relative key)."""
    pcm = beats._pcm(path)
    out = []
    rho, _ = plan.energy_cards(plan.profile(pcm, song), song)
    if rho is not None:
        out.append(at_least("song.energy_follows_plan", rho, "song_energy_rho_min"))
    match, _ = plan.key_cards(pcm, song) if song.get("key") else (None, [])
    if match is not None:
        out.append(at_least("song.key_match", match, "song_key_match_min"))
    return out


def saved_heard(take: Path) -> list[Word] | None:
    """What was heard of a take, kept beside it: off its vocal stem when that was transcribed, as a
    transcriber hears far more of a voice without its band; else off the take."""
    for saved in (take.with_suffix(STEM_HEARD), take.with_suffix(MIX_HEARD)):
        if saved.exists():
            return list(json.loads(saved.read_text()))
    return None


def assessed(path: Path, song: Song, heard: list[Word] | None) -> tuple[dict[str, Any], bool]:
    """A take's readings as a take keeps them, and whether it passes every one."""
    report = measure(path, song, heard)
    misses = [r["id"] for r in report["readings"] if not r["ok"]]
    return {"score": score(report), "misses": misses, "readings": report["readings"]}, not misses


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
