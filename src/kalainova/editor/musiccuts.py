"""Cuts that come from the music: bars, phrases, and the one place the energy jumps.

Pure arithmetic on a beat grid and the onset envelope `beats.py` already computes. Nothing here
reaches a model. When the track gives no steady pulse or no clear rise in energy, the functions
say so and stop: a cut point guessed from nothing is worse than none.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..jobfs import ContractError
from . import beats as beat_tools

Span = dict[str, Any]
Analysis = dict[str, Any]  # beats, bars (times), energy per bar, rise (bar, lift) or None, notes
LAG_FRAMES = round(beat_tools.WIN / 2 / beat_tools.HOP)  # an envelope frame is stamped at its start
BAR_BEATS = 4  # a bar is four beats unless a caller says otherwise
MIN_PULSE = 3.0  # onset energy on the beats over its average elsewhere; below, the grid is a guess
MIN_LIFT = 0.3  # a rise must lift the next two bars this far above the last two; ESTIMATE
# both are ESTIMATE until reviewed tracks tune them
ANGLES = ("wide", "close", "medium")
ON_BEAT_SEC = 0.08  # a cut this near a beat reads as on it
HIGH_PHRASE_BARS, LOW_PHRASE_BARS = 4, 8
WINDOW_DROP_AT = 0.4  # where in an excerpt the rise sits: some build-up first, then the payoff


def analyse(path: Path, length: float, bar_beats: int = BAR_BEATS) -> Analysis:
    grid = beat_tools.beat_grid(path, length)
    beats = [float(b) for b in grid["beats"]]
    env = beat_tools.onset_envelope(beat_tools._pcm(path))
    fps = beat_tools.SR / beat_tools.HOP
    env = np.concatenate([np.zeros(LAG_FRAMES), env])  # frame n now stamps time n/fps
    notes: list[str] = []
    strength = _pulse_strength(env, beats, fps)
    pulse = strength >= MIN_PULSE and len(beats) >= bar_beats * 2
    if not pulse:
        notes.append(
            f"no steady pulse found (strength {strength:.1f}, needs {MIN_PULSE});"
            " cut points would be guesses"
        )
    offset = _downbeat(beats, env, fps, bar_beats)
    bars = beats[offset::bar_beats]
    edges = [*bars, length]
    energy = [
        float(env[int(a * fps) : max(int(b * fps), int(a * fps) + 1)].sum())
        for a, b in zip(edges, edges[1:], strict=False)
    ]
    rise = _biggest_rise(energy)
    if not rise:
        notes.append("no clear energy peak found; no cut is placed on a drop")
    return {
        "bpm": grid["bpm"],
        "strength": round(strength, 2),
        "beats": beats,
        "bars": bars,
        "end": length,
        "energy": energy,
        "rise": rise,
        "pulse": pulse,
        "notes": notes,
    }


def _pulse_strength(env: np.ndarray, beats: list[float], fps: float) -> float:
    """How much stronger the onsets are on the grid than everywhere else, give or take a frame."""
    if not beats or env.max() <= 0:
        return 0.0
    near = np.convolve(env, np.array([0.25, 0.5, 0.25]), mode="same")  # good to about a frame
    ticks = [min(int(b * fps), env.size - 1) for b in beats]
    return float(near[ticks].mean() / (near.mean() + 1e-9))


def _downbeat(beats: list[float], env: np.ndarray, fps: float, per_bar: int) -> int:
    """Which beat opens a bar: the one whose every-fourth ticks carry the most onset energy."""
    scores = []
    for off in range(per_bar):
        ticks = [min(int(b * fps), env.size - 1) for b in beats[off::per_bar]]
        scores.append(float(env[ticks].sum()) if ticks else 0.0)
    return int(np.argmax(scores)) if scores else 0


def _biggest_rise(energy: list[float]) -> tuple[int, float] | None:
    if len(energy) < 4:
        return None
    best: tuple[int, float] | None = None
    for i in range(1, len(energy)):
        before = float(np.mean(energy[max(0, i - 2) : i]))
        after = float(np.mean(energy[i : i + 2]))
        lift = (after - before) / (before + 1e-9)
        if lift >= MIN_LIFT and (best is None or lift > best[1]):
            best = (i, round(lift, 3))
    return best


def refuse_if_unclear(found: Analysis, why: str, *, need_peak: bool = False) -> None:
    """Say what the detector could not find instead of cutting on a guess. A short's excerpt needs
    a peak; a cut on phrases needs only a steady pulse."""
    if not found["pulse"] or (need_peak and not found["rise"]):
        raise ContractError(f"{why}: {found['notes'][0]}")


def window(found: Analysis, length: float, start: float | None = None) -> tuple[float, float]:
    """A stretch on bar lines: the strongest by default, or from a given start. Within a bar of
    the length asked for. The strongest is placed so the biggest rise lands part-way in."""
    bars = found["bars"]
    if len(bars) < 2:
        raise ContractError("the track has no bars to cut an excerpt on")
    bar = float(np.median(np.diff(bars)))
    count = max(1, round(length / bar))
    if start is None:
        refuse_if_unclear(found, "the strongest stretch cannot be chosen", need_peak=True)
        first = max(0, found["rise"][0] - round(WINDOW_DROP_AT * count))
    else:
        first = int(np.argmin([abs(b - start) for b in bars]))
    first = min(first, max(len(bars) - count, 0))
    last = first + count
    return float(bars[first]), float(bars[last] if last < len(bars) else found["end"])


def phrase_boundaries(found: Analysis, phrase_bars: int | None = None) -> list[int]:
    """Bar numbers where a phrase starts: every 8 bars, every 4 where the energy is high."""
    energy, bars = found["energy"], found["bars"]
    mean = float(np.mean(energy)) if energy else 0.0
    out, i = [], 0
    while i < len(bars):
        out.append(i)
        i += phrase_bars or (HIGH_PHRASE_BARS if energy[i] >= mean else LOW_PHRASE_BARS)
    return out


def section_boundaries(sections: list[dict[str, Any]]) -> list[int]:
    """Bar numbers where a section of the song contract starts, from the bars each one names."""
    out, at = [], 0
    for section in sections:
        if section.get("bars"):
            out.append(at)
            at += int(section["bars"])
    return out


def music_spans(
    found: Analysis, length: float, song: dict[str, Any], phrase_bars: int | None = None
) -> list[Span]:
    """Shots from structure: phrase starts, section starts, and the biggest rise."""
    bars = found["bars"]
    sections = section_boundaries(song.get("sections") or [])
    marks = set(phrase_boundaries(found, phrase_bars)) | set(sections)
    if found["rise"]:
        marks.add(found["rise"][0])
    times = [0.0, *[bars[i] for i in sorted(marks) if 0 < i < len(bars)], length]
    drop = bars[found["rise"][0]] if found["rise"] else None
    return [
        {
            "start": a,
            "end": b,
            "text": "",
            "section": _section_at(sections, bars, a),
            "strong": drop is not None and abs(a - drop) < 1e-6,
        }
        for a, b in zip(times, times[1:], strict=False)
        if b - a > 0.2
    ]


def _section_at(starts: list[int], bars: list[float], at: float) -> int | None:
    done = [n for n, s in enumerate(starts) if s < len(bars) and bars[s] <= at + 1e-6]
    return done[-1] if done else None


def split_for_ceiling(spans: list[Span], found: Analysis, ceiling: float | None) -> list[Span]:
    """Cut a long shot into whole bars (whole beats where one bar is too long), each from another
    angle, so a character is never held past the ceiling: cutaways, not a long take."""
    if not ceiling:
        return spans
    beats = found["beats"]
    beat = float(np.median(np.diff(beats))) if len(beats) > 1 else ceiling
    bar = beat * BAR_BEATS
    whole = bar if bar <= ceiling else beat
    unit = whole * max(1, int(ceiling // whole))
    out: list[Span] = []
    for span in spans:
        at = span["start"]
        while at < span["end"] - 1e-6:
            end = min(at + unit, span["end"])
            if span["end"] - end < beat * 0.5:
                end = span["end"]
            out.append(
                {
                    **span,
                    "start": round(at, 3),
                    "end": round(end, 3),
                    "angle": ANGLES[len(out) % len(ANGLES)],
                    "strong": span["strong"] and at == span["start"],
                }
            )
            at = end
    return out


def clip_to_window(spans: list[Span], a: float, b: float) -> list[Span]:
    out = [
        {**s, "start": round(max(s["start"], a) - a, 3), "end": round(min(s["end"], b) - a, 3)}
        for s in spans
        if s["end"] > a + 0.2 and s["start"] < b - 0.2
    ]
    return [s for s in out if s["end"] - s["start"] > 0.2]


def cut_offsets(cuts: list[float], beats: list[float]) -> list[dict[str, float]]:
    """Each cut and its distance from the nearest beat, in seconds."""
    return [
        {"at": round(c, 3), "off_sec": round(min((abs(b - c) for b in beats), default=0.0), 3)}
        for c in cuts
    ]


def share_on_beat(cuts: list[float], beats: list[float], tol: float = ON_BEAT_SEC) -> float:
    """The share of cuts within tol of a beat: 1.0 for cuts made on the grid."""
    rows = cut_offsets(cuts, beats)
    return round(sum(r["off_sec"] <= tol for r in rows) / len(rows), 3) if rows else 1.0
