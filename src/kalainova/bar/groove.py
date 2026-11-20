"""The groove a take was asked for, read off its instrumental: where the kick is, whether a build
rises, and how syncopated the drums are (issue #131, first slice). A take is held to its own song
file, as in `plan` (ADR 0034); none of this judges taste, and nothing here blocks.

  kick_cards     a steady kick where a section keeps it out (its `avoid`, or energy 1), or from its
                 first bar where its note holds it back ("kick enters late")
  build_cards    a section the plan steps up from (energy two or more levels lower than the next)
                 that is a build (a pre-chorus, or a note that says it builds or rises) and does
                 not rise into the next: level, brightness and onset density across eight windows,
                 against a straight ramp
  measures       when the kick enters, and a syncopation index per section and for the song

The evidence: a build is read best as a plain rise (Biliousis and Dahl, SMC 2026: a linear ramp
predicted listeners' felt tension better than a Gestalt model); break routines are liked over
flat tracks (Solberg and Jensenius 2017); medium syncopation gives the most urge to move, an
inverted U (Witek et al. 2014), measured with Longuet-Higgins and Lee's metrical weights. The
syncopation index ranks nothing until it has been calibrated on a person's verdicts (#133).
"""

from __future__ import annotations

import re
from typing import Any

import numpy as np

from ..editor import beats
from .plan import HIGH_HZ, LOW_HZ, REPAIR, Card, Song, _at, _db, _frames, spans

LAG = beats.WIN / beats.SR  # a frame's window reaches an onset this long after the frame starts
KICK_AT = 0.5  # a beat holds a kick when its low-band onset reaches this share of the loud ones
STEADY = 0.75  # a kick on this share of a section's beats is a steady kick
BUILD_STEP = 2  # the next section's energy this much higher: the plan steps up into it
WINDOWS = 8
BUILDS = re.compile(r"\b(build|builds|building|rise|rises|rising|swell|swells|lift|lifts)\b", re.I)
KEPT_OUT = re.compile(r"\b(kick|drums?)\b", re.I)
LATE = re.compile(r"\b(kick|drums?)\s+(enters?|comes?\s+in|drops?\s+in|arrives?)\s+late", re.I)
# Longuet-Higgins and Lee (1984): each sixteenth of a 4/4 bar by its place in the metre
WEIGHTS = np.array([0, -4, -3, -4, -2, -4, -3, -4, -1, -4, -3, -4, -2, -4, -3, -4])
SLOTS = len(WEIGHTS)


def _kick_flux(pcm: np.ndarray) -> tuple[np.ndarray, float]:
    frames = _frames(pcm)
    low = np.log1p(frames.power[:, frames.freqs < LOW_HZ].sum(axis=1))
    # the first frame rises from silence, so a kick on the very first beat is heard
    return np.concatenate([low[:1], np.maximum(np.diff(low), 0)]), frames.fps


def _struck(flux: np.ndarray, fps: float, times: np.ndarray) -> np.ndarray:
    """How hard the band strikes at each time: the peak within a frame either side. An onset
    shows in the frame whose window first reaches it, so a frame is timed at its window's end."""
    at = np.maximum(np.round((times - LAG) * fps).astype(int), 0)
    return np.array([flux[max(i - 1, 0) : i + 2].max() if i < len(flux) else 0.0 for i in at])


def _beats(flux: np.ndarray, fps: float, bpm: float) -> np.ndarray:
    """Each beat's time, at the phase where the low band strikes hardest on the beat."""
    period = 60.0 / bpm
    n = int((len(flux) / fps + LAG) / period)
    if not n:
        return np.zeros(0)
    shifts = np.arange(0, period, 1 / fps)
    strength = [float(_struck(flux, fps, s + period * np.arange(n)).mean()) for s in shifts]
    return float(shifts[int(np.argmax(strength))]) + period * np.arange(n)


def _kicked(pcm: np.ndarray, bpm: float) -> tuple[np.ndarray, np.ndarray]:
    flux, fps = _kick_flux(pcm)
    beat = _beats(flux, fps, bpm)
    if not beat.size:
        return beat, np.zeros(0, dtype=bool)
    strength = _struck(flux, fps, beat)
    loud = float(np.percentile(strength, 90))
    return beat, strength >= KICK_AT * loud if loud > 0 else np.zeros(beat.size, dtype=bool)


def kick_enters(pcm: np.ndarray, bpm: float) -> float | None:
    """When a steady kick starts: the first struck beat of four with a kick on three of them."""
    beat, hit = _kicked(pcm, bpm)
    for b in range(hit.size - 3):
        if hit[b] and hit[b : b + 4].sum() >= 3:
            return round(float(beat[b]), 2)
    return None


def _kick_asked(section: dict[str, Any]) -> str | None:
    """What a section asks of the kick: kept out (its `avoid`, or energy 1, "nearly nothing"), or
    held back until later in it (its note: "kick enters late")."""
    kept = KEPT_OUT.search(str(section.get("avoid") or ""))
    if kept:
        return f"keeps out the {kept.group(0).lower()}"
    if section.get("energy") == 1:
        return "energy 1 of 5: nearly nothing, no steady kick"
    late = LATE.search(str(section.get("style") or ""))
    return f"the {late.group(1).lower()} {late.group(2).lower()} late" if late else None


def kick_cards(pcm: np.ndarray, song: Song) -> list[Card]:
    """A steady kick where a section keeps it out, or from the first bar where it holds it back."""
    placed, bpm = spans(song), float(song.get("bpm") or 0)
    if not placed:
        return []
    beat, hit = _kicked(pcm, bpm)
    cards = []
    for section, (start, end) in zip(song["sections"], placed, strict=True):
        asked = _kick_asked(section)
        inside = (beat >= start) & (beat < end)
        if not asked or not inside.any():
            continue
        share, opening = float(hit[inside].mean()), hit[inside][:4]
        if asked.endswith("late"):
            if opening.sum() < 3:
                continue
            said = f"a kick from its first bar, on {share:.0%} of its beats"
        elif share >= STEADY:
            said = f"a kick on {share:.0%} of its beats"
        else:
            continue
        cards.append({"id": "plan.kick", "at": _at(start), "section": str(section["kind"]),
                      "planned": asked, "measured": said, "fix": REPAIR})  # fmt: skip
    return cards


def _rise(pcm: np.ndarray, start: float, end: float) -> float | None:
    """How closely level, brightness and onsets across the span follow a straight rise
    (correlation with a ramp, from -1 to 1)."""
    frames = _frames(pcm)
    edges = np.linspace(start, end, WINDOWS + 1)
    high = frames.freqs > HIGH_HZ
    cols = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        part = frames.power[frames.window(float(a), float(b))]
        flux = frames.onsets[frames.window(float(a), float(b))]
        cols.append((_db(part), _db(part[:, high]), float(flux.mean()) if flux.size else 0.0))
    data = np.array(cols).T
    spread = data.std(axis=1, keepdims=True)
    if not np.all(spread > 1e-9):
        return None
    trend = ((data - data.mean(axis=1, keepdims=True)) / spread).mean(axis=0)
    return round(float(np.corrcoef(trend, np.arange(WINDOWS))[0, 1]), 3)


def _is_build(section: dict[str, Any], after: dict[str, Any]) -> bool:
    this, nxt = section.get("energy"), after.get("energy")
    if not isinstance(this, int | float) or not isinstance(nxt, int | float):
        return False
    builds = section.get("kind") == "pre-chorus" or bool(BUILDS.search(str(section.get("style"))))
    return nxt - this >= BUILD_STEP and builds


def build_cards(pcm: np.ndarray, song: Song) -> list[Card]:
    """A build the plan asks for that does not rise into the section it steps up to."""
    placed = spans(song)
    sections = song.get("sections") or []
    cards = []
    for i, (section, (start, end)) in enumerate(zip(sections, placed, strict=False)):
        if i + 1 >= len(sections) or not _is_build(section, sections[i + 1]):
            continue
        rise = _rise(pcm, start, end)
        if rise is not None and rise <= 0:
            after = sections[i + 1]
            cards.append({"id": "plan.build", "at": _at(start), "section": str(section["kind"]),
                          "planned": f"builds into the {after.get('kind')} (energy "
                          f"{section['energy']:g} to {after['energy']:g})",
                          "measured": f"level, brightness and onsets do not rise across it "
                          f"(against a ramp {rise:+.2f})", "fix": REPAIR})  # fmt: skip
    return cards


def syncopation(onsets: np.ndarray, next_downbeat: bool = True) -> float:
    """Longuet-Higgins and Lee's syncopation of one bar of sixteenths (True where struck): for
    each note, the strongest rest before the next note, where that rest is stronger than the note.
    The next bar's downbeat is the last place a note can land; it is a rest only when unstruck."""
    struck = [i for i in range(SLOTS) if onsets[i]]
    total = 0
    for n, i in enumerate(struck):
        nxt = struck[n + 1] if n + 1 < len(struck) else SLOTS
        rests = [int(WEIGHTS[j]) for j in range(i + 1, min(nxt, SLOTS)) if not onsets[j]]
        if nxt == SLOTS and not next_downbeat:
            rests.append(0)  # the downbeat that follows, left empty
        strongest = max(rests, default=None)
        if strongest is not None and strongest > WEIGHTS[i]:
            total += int(strongest - WEIGHTS[i])
    return float(total)


def _bar_onsets(pcm: np.ndarray, bpm: float, phase: float) -> list[tuple[float, np.ndarray]]:
    frames = _frames(pcm)
    flux = frames.onsets
    slot = 60.0 / bpm / 4
    bars = int((len(flux) / frames.fps - phase) / (slot * SLOTS))
    out = []
    for b in range(bars):
        start = phase + b * slot * SLOTS
        strength = _struck(flux, frames.fps, start + slot * np.arange(SLOTS))
        top = strength.max()
        if top > 0:
            out.append((start, strength >= 0.5 * top))
    return out


def measures(pcm: np.ndarray, song: Song) -> dict[str, Any]:
    """When the kick enters, and the syncopation per bar averaged per section and over the song.
    Readings to rank by once calibrated, never a limit."""
    bpm = float(song.get("bpm") or 0)
    if not bpm:
        return {}
    beat, _ = _kicked(pcm, bpm)
    bars = _bar_onsets(pcm, bpm, float(beat[0]) if beat.size else 0.0)
    found: dict[str, Any] = {"kick_enters_sec": kick_enters(pcm, bpm)}
    each = [
        (t, syncopation(o, bool(bars[n + 1][1][0]) if n + 1 < len(bars) else True))
        for n, (t, o) in enumerate(bars)
    ]
    if each:
        found["syncopation"] = round(float(np.median([v for _, v in each])), 2)
    per = []
    for section, (start, end) in zip(song.get("sections") or [], spans(song), strict=False):
        inside = [v for t, v in each if start <= t < end]
        if inside:
            per.append({"section": str(section.get("kind")), "at": _at(start),
                        "syncopation": round(float(np.mean(inside)), 2)})  # fmt: skip
    if per:
        found["sections"] = per
    return found
