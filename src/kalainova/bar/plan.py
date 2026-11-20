"""Whether a take did what its own song file asked, section by section (ADR 0034).

A song file is written before the take, so it is the reference a take is held to: each
section's place (its bars at the song's tempo), its energy from 1 to 5 as the writer meant it,
whether it has words, and the key asked for. Nothing here judges taste or rewards one shape of
song: a take is read against its own plan, and a miss becomes a card that says what was asked,
what was measured, where, and how sure the measurement is.

  profile       each planned section's loudness, low end, brightness and onset density
  energy_cards  sections whose measured weight sits two or more levels off the planned energy
  voice_cards   a voice in a section planned without words, or none where words are planned
  key_cards     the key the take sounds in (chroma against Krumhansl-Kessler profiles), and how sure
  words_cards   sections whose planned words were mostly not heard where they belong
  pronounce_cards  each uncommon word the song says how to say, where it is sung and not heard

The research behind each: plan.md in the studio's review of 2026-11-20 (Solberg and Jensenius
2017 on build and drop; Van Balen et al. 2015 on hooks; Krumhansl and Kessler 1982 on key).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import numpy as np

from ..editor import beats

Song = dict[str, Any]
Card = dict[str, Any]
LOW_HZ, HIGH_HZ = 150.0, 4000.0  # the kick and bass; the hats and air
LEVELS = 5
VOICE_ABSENT_DB = -18.0  # a section's voice this far below the sung sections' median is silent
VOICE_PRESENT_DB = -12.0  # a planned-silent section with voice above this has someone singing
WORDS_HEARD_MIN = 0.5
KEY_SURE_GAP = 0.15  # the key asked fits this far below the best: the take is in another key
REPAIR = "repair this section by region edit, or retake"
BLEED = "listen: a stray vocal, or the separator's bleed"
TOKEN = re.compile(r"[a-z']+")
SHORT_WORD = 3
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLATS = {"Db": "C#", "Eb": "D#", "Gb": "F#", "Ab": "G#", "Bb": "A#"}
# Krumhansl and Kessler (1982): how well each pitch class fits a major and a minor key on C
MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def spans(song: Song) -> list[tuple[float, float]]:
    """Where each section was asked to sit, in seconds: its bars at the song's tempo. None of
    them when a section names no bars or the song no tempo."""
    sections, bpm = song.get("sections") or [], float(song.get("bpm") or 0)
    if not bpm or not sections or not all(s.get("bars") for s in sections):
        return []
    out, at = [], 0.0
    for section in sections:
        length = float(section["bars"]) * 4 * 60 / bpm
        out.append((at, at + length))
        at += length
    return out


def _at(seconds: float) -> str:
    minutes, rest = divmod(max(seconds, 0.0), 60)
    return f"{int(minutes)}:{int(rest):02d}"


def _db(power: np.ndarray) -> float:
    return float(10 * np.log10(np.mean(power) + 1e-12)) if power.size else -120.0


@dataclass
class _Frames:
    power: np.ndarray  # frames x bins
    freqs: np.ndarray
    onsets: np.ndarray  # per frame
    fps: float

    def window(self, start: float, end: float) -> slice:
        return slice(int(start * self.fps), max(int(end * self.fps), int(start * self.fps) + 1))


def _frames(pcm: np.ndarray) -> _Frames:
    win, hop = beats.WIN, beats.HOP
    if pcm.size < win:
        pcm = np.pad(pcm, (0, win - pcm.size))
    n = 1 + (pcm.size - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    spec = np.abs(np.fft.rfft(pcm[idx] * np.hanning(win), axis=1))
    freqs = np.fft.rfftfreq(win, 1 / beats.SR)
    log = np.log1p(spec)
    flux = np.concatenate([[0.0], np.maximum(np.diff(log, axis=0), 0).sum(axis=1)])
    return _Frames(power=spec**2, freqs=freqs, onsets=flux, fps=beats.SR / hop)


def profile(pcm: np.ndarray, song: Song) -> list[dict[str, Any]]:
    """Each planned section as measured: its level, its low end and its brightness in dB, and its
    onset density (spectral flux a second). Empty without bars to place the sections."""
    placed = spans(song)
    if not placed:
        return []
    frames = _frames(pcm)
    low, high = frames.freqs < LOW_HZ, frames.freqs > HIGH_HZ
    out = []
    for section, (start, end) in zip(song["sections"], placed, strict=True):
        part = frames.power[frames.window(start, end)]
        out.append(
            {
                "kind": str(section.get("kind")),
                "start_sec": round(start, 2),
                "end_sec": round(end, 2),
                "level_db": round(_db(part), 2),
                "low_db": round(_db(part[:, low]), 2),
                "high_db": round(_db(part[:, high]), 2),
                "onsets": round(float(frames.onsets[frames.window(start, end)].mean()), 3),
            }
        )
    return out


def _weights(measured: list[dict[str, Any]]) -> np.ndarray:
    """How much each section carries, from 1 to 5 within this take: its level, low end and onset
    density, each scaled across the take's sections, averaged."""
    cols = [
        np.array([m[k] for m in measured], dtype=float) for k in ("level_db", "low_db", "onsets")
    ]
    scaled = []
    for col in cols:
        spread = col.max() - col.min()
        scaled.append((col - col.min()) / spread if spread > 1e-9 else np.zeros_like(col))
    return 1 + (LEVELS - 1) * np.mean(scaled, axis=0)


def energy_cards(measured: list[dict[str, Any]], song: Song) -> tuple[float | None, list[Card]]:
    """How closely the take's section weights follow the planned energy (Spearman's rho), and a
    card for each section two or more levels off. None and no cards without a planned energy on
    every section."""
    planned = [s.get("energy") for s in song.get("sections") or []]
    if not measured or not all(isinstance(p, int | float) for p in planned):
        return None, []
    weights = _weights(measured)
    rho = _spearman(np.array(planned, dtype=float), weights)
    loudest = max(m["level_db"] for m in measured)
    lowest = max(m["low_db"] for m in measured)
    cards = []
    for section, m, p, w in zip(song["sections"], measured, planned, weights, strict=True):
        if abs(w - float(p)) >= 2:
            cards.append(
                {
                    "id": "plan.energy",
                    "at": _at(m["start_sec"]),
                    "section": m["kind"],
                    "planned": f"energy {p:g} of 5"
                    + (f": {section['style']}" if section.get("style") else ""),
                    "measured": f"carries like {w:.1f} of 5: level "
                    f"{m['level_db'] - loudest:+.1f} dB and low end {m['low_db'] - lowest:+.1f} dB "
                    "from the take's fullest section",
                    "fix": REPAIR,
                }
            )
    return rho, cards


def _spearman(a: np.ndarray, b: np.ndarray) -> float | None:
    if a.size < 3 or np.ptp(a) == 0 or np.ptp(b) == 0:
        return None
    ra, rb = (np.argsort(np.argsort(x, kind="stable"), kind="stable").astype(float) for x in (a, b))
    return round(float(np.corrcoef(ra, rb)[0, 1]), 3)


def voice_cards(stem: np.ndarray, song: Song) -> list[Card]:
    """A voice where the plan has no words, or none where it has them, read off the vocal stem
    against the median of its sung sections."""
    placed = spans(song)
    if not placed or stem.size == 0:
        return []
    frames = _frames(stem)
    levels = [_db(frames.power[frames.window(a, b)]) for a, b in placed]
    sung = [lv for s, lv in zip(song["sections"], levels, strict=True) if s.get("lines")]
    if not sung:
        return []
    median = float(np.median(sung))
    cards = []
    for section, (start, _), level in zip(song["sections"], placed, levels, strict=True):
        rel = level - median
        sung_here = bool(section.get("lines"))
        if sung_here and rel < VOICE_ABSENT_DB:
            said = ("sung", f"voice {rel:.0f} dB under the sung median", REPAIR)
        elif not sung_here and rel > VOICE_PRESENT_DB:
            said = ("no words", f"a voice {rel:.0f} dB from the sung median", BLEED)
        else:
            continue
        cards.append({"id": "plan.voice", "at": _at(start), "section": str(section["kind"]),
                      "planned": said[0], "measured": said[1], "fix": said[2]})  # fmt: skip
    return cards


def key_fits(pcm: np.ndarray) -> list[tuple[float, str]]:
    """Every key's fit to the take, best first (correlation of a log-magnitude chroma of 65 Hz to
    2 kHz with the Krumhansl-Kessler profiles)."""
    frames = _frames(pcm)
    band = (frames.freqs > 65) & (frames.freqs < 2000)
    midi = np.round(69 + 12 * np.log2(frames.freqs[band] / 440.0)).astype(int) % 12
    energy = np.log1p(np.sqrt(frames.power[:, band])).sum(axis=0)
    chroma = np.bincount(midi, weights=energy, minlength=12)
    fits = []
    for tonic in range(12):
        for mode, prof in (("major", MAJOR), ("minor", MINOR)):
            fits.append(
                (float(np.corrcoef(chroma, np.roll(prof, tonic))[0, 1]), f"{NAMES[tonic]} {mode}")
            )
    fits.sort(reverse=True)
    return [(round(f, 3), k) for f, k in fits]


def key_cards(pcm: np.ndarray, song: Song) -> tuple[float | None, list[Card]]:
    """Whether the take sounds in the key asked (key_match), and a card when it does not: sure
    when the key asked fits well below the best, else marked uncertain, since a full mix's chroma
    confuses keys that share notes."""
    asked = str(song.get("key") or "")
    fits = key_fits(pcm)
    match = key_match(asked, fits[0][1]) if asked else None
    if not match == 0.0:
        return match, []
    asked_fit = next((f for f, k in fits if key_match(asked, k) == 1.0), None)
    sure = asked_fit is not None and fits[0][0] - asked_fit >= KEY_SURE_GAP
    said = f"sounds in {fits[0][1]} (fit {fits[0][0]:.2f})" + (
        f"; {asked} fits {asked_fit:.2f}" if asked_fit is not None else ""
    )
    return match, [{"id": "plan.key", "at": "0:00", "section": "the whole song", "planned": asked,
                    "measured": said + ("" if sure else "; uncertain"),
                    "fix": "listen; a key the model did not follow needs a retake"}]  # fmt: skip


def pronounce_cards(song: Song, heard: list[dict[str, Any]]) -> list[Card]:
    """Each uncommon word the song file says how to pronounce, checked where it is sung: a section
    that sings it and in which it was not heard gets a card with what was heard instead."""
    placed = spans(song)
    said = {str(w).lower(): str(v) for w, v in (song.get("pronounce") or {}).items()}
    if not placed or not heard or not said:
        return []
    cards = []
    for section, (start, end) in zip(song["sections"], placed, strict=True):
        text = " ".join(section.get("lines") or []).lower()
        got = [
            str(w.get("text", "")) for w in heard if start <= float(w.get("start_sec", -1)) < end
        ]
        tokens = set(_tokens(got))
        for word, sound in said.items():
            if word not in text or _heard_word(word, sound, tokens):
                continue
            wanted = set(TOKEN.findall(text))
            instead = list(dict.fromkeys(t for t in _tokens(got) if t not in wanted))[:4]
            measured = "not heard here" + (
                f"; heard instead: {', '.join(instead)}" if instead else ""
            )
            cards.append({"id": "plan.pronounce", "at": _at(start),
                          "section": str(section["kind"]), "planned": f'"{word}", said "{sound}"',
                          "measured": measured, "fix": REPAIR})  # fmt: skip
    return cards


def _tokens(words: list[str]) -> list[str]:
    return [t for g in words for t in TOKEN.findall(g.lower())]


def _heard_word(word: str, sound: str, tokens: set[str]) -> bool:
    """A word counts as heard when a transcriber wrote it as written, or as it is said ("nour"
    heard as "Noor" is the word, said right)."""
    if set(TOKEN.findall(word)) <= tokens:
        return True
    said = "".join(TOKEN.findall(sound.lower()))
    return bool(said) and said in tokens


def _pitch_set(key: str) -> tuple[int, str] | None:
    found = re.match(r"^\s*([A-Ga-g])([#b]?)\s*(major|minor|maj|min|m)?\b", key)
    if not found:
        return None
    name = found.group(1).upper() + found.group(2)
    name = FLATS.get(name, name)
    mode = (
        "minor"
        if (found.group(3) or "major").startswith("m") and found.group(3) not in ("major", "maj")
        else "major"
    )
    return NAMES.index(name), mode


def key_match(asked: str, heard: str) -> float | None:
    """1 when the take is in the key asked, 0.5 when in its relative key (the same notes, another
    tonic), 0 otherwise; None when the key asked cannot be read."""
    a, h = _pitch_set(asked), _pitch_set(heard)
    if a is None or h is None:
        return None
    if a == h:
        return 1.0
    shift = 3 if a[1] == "minor" else -3  # A minor shares C major's notes
    return 0.5 if h[1] != a[1] and (a[0] + shift) % 12 == h[0] else 0.0


def words_cards(song: Song, heard: list[dict[str, Any]]) -> list[Card]:
    """Each sung section whose planned words were mostly not heard inside its own span: a target
    for repair. Words are matched as written (content words of four letters or more)."""
    placed = spans(song)
    if not placed or not heard:
        return []
    cards = []
    for section, (start, end) in zip(song["sections"], placed, strict=True):
        wanted = {t for line in section.get("lines") or [] for t in TOKEN.findall(line.lower())
                  if len(t) > SHORT_WORD}  # fmt: skip
        if not wanted:
            continue
        got = {t for w in heard if start <= float(w.get("start_sec", -1)) < end
               for t in TOKEN.findall(str(w.get("text", "")).lower())}  # fmt: skip
        share = len(wanted & got) / len(wanted)
        if share < WORDS_HEARD_MIN:
            missing = ", ".join(sorted(wanted - got)[:6])
            cards.append({"id": "plan.words", "at": _at(start), "section": str(section["kind"]),
                          "planned": "; ".join(section.get("lines") or [])[:120],
                          "measured": f"{share:.0%} of its words heard here; not heard: {missing}",
                          "fix": REPAIR})  # fmt: skip
    return cards
