"""Where a song is sung: read from its vocal stem and from what was heard, so a singing short is
cut where the words are sung, and its lip-synced shots sit on singing.

The stem says when there is a voice; the transcript says which of the song's words a listener
picks out there. Pure over samples and words: no model, and no cost.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any

import numpy as np

from .. import media
from ..jobfs import ContractError, Job
from . import musiccuts as mc

FRAME_SEC = 0.05
SUNG_DB = -20.0  # a frame within this of the stem's loud singing has a voice in it
LOUD_PERCENTILE = 95  # the stem's loud singing, robust to a stray peak
SUNG_MIN = 0.5  # a shot sung this much of the way has a mouth worth syncing
CHORUS_WEIGHT = 2  # a chorus word heard counts this many times: a short wants the hook
SHORT_WORD = 2  # words this short or shorter ("a", "in") say nothing about which line it is
SINGS = "sings:"
INTRO_GUARD_SEC = 0.5  # an estimated first line starts this long after the sound does
LEAST_LINE_SEC = 0.8

Sung = tuple[np.ndarray, float]  # one flag a frame, and frames a second
Cue = dict[str, Any]


def voiced(stem: Path) -> Sung:
    """Which frames of a vocal stem carry a voice."""
    left, right, sr = media.decode_stereo(stem)
    mono = (left + right) / 2
    hop = max(int(sr * FRAME_SEC), 1)
    n = mono.size // hop
    if not n:
        return np.zeros(0, dtype=bool), 1 / FRAME_SEC
    rms = np.sqrt(np.mean(mono[: n * hop].reshape(n, hop) ** 2, axis=1))
    loud = float(np.percentile(rms, LOUD_PERCENTILE))
    return rms > loud * 10 ** (SUNG_DB / 20), 1 / FRAME_SEC


def share(sung: Sung, start: float, end: float) -> float:
    """How much of [start, end) has a voice, from 0 to 1."""
    flags, fps = sung
    part = flags[int(start * fps) : max(int(end * fps), int(start * fps) + 1)]
    return float(part.mean()) if part.size else 0.0


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9']+", text.lower()) if len(t) > SHORT_WORD}


def _weights(song: dict[str, Any]) -> dict[str, int]:
    """Each lyric word, weighted by whether it belongs to a chorus."""
    out: dict[str, int] = {}
    for section in song.get("sections") or []:
        weight = CHORUS_WEIGHT if section.get("kind") in ("chorus", "hook") else 1
        for line in section.get("lines") or []:
            for token in _tokens(line):
                out[token] = max(out.get(token, 0), weight)
    return out


def heard_score(song: dict[str, Any], heard: list[dict[str, Any]], a: float, b: float) -> int:
    """The song's own words heard sung inside [a, b], a chorus word counting double."""
    weights = _weights(song)
    return sum(
        weights.get(token, 0)
        for word in heard
        if a <= float(word.get("start_sec", -1)) < b
        for token in _tokens(str(word.get("text", "")))
    )


def best_window(
    found: mc.Analysis,
    length: float,
    song: dict[str, Any],
    heard: list[dict[str, Any]],
    sung: Sung,
) -> tuple[float, float]:
    """A singing short's stretch, on bar lines: where the most of the song's words are heard
    sung, the chorus counting double, then where the voice is on longest. It needs no energy
    peak, because what it looks for is the singing."""
    bars = found["bars"]
    if len(bars) < 2:
        raise ContractError("the track has no bars to cut an excerpt on")
    count = max(1, round(length / float(np.median(np.diff(bars)))))
    best: tuple[tuple[int, float], float, float] | None = None
    for first in range(max(len(bars) - count, 0) + 1):
        a = float(bars[first])
        b = float(bars[first + count]) if first + count < len(bars) else float(found["end"])
        key = (heard_score(song, heard, a, b), share(sung, a, b))
        if best is None or key > best[0]:
            best = (key, a, b)
    if best is None:
        raise ContractError("the track is shorter than the excerpt asked for")
    return best[1], best[2]


def sings(line: str) -> bool:
    """Whether a shot-list line is a singing shot."""
    return line.lower().startswith(SINGS)


def place(
    shot_list: list[str], kinds: list[str], spans: list[mc.Span], sung: Sung, offset: float = 0.0
) -> tuple[list[str], list[int]]:
    """One shot-list line for each shot. The list's singing lines go to the moving shots that are
    sung most of the way, the longest of them first, in the order they are listed; the other lines
    fill the rest, in order, repeated. Without a singing line, the list runs in order as written.
    Also returns the shots that sing."""
    expanded = [shot_list[n % len(shot_list)] for n in range(len(spans))]
    wanted = sum(sings(line) for line in expanded)
    singing = [line for line in shot_list if sings(line)]
    others = [line for line in shot_list if not sings(line)] or [
        line[len(SINGS) :].strip() for line in singing
    ]
    if not singing:
        return expanded, []
    sung_spans = [
        n
        for n, span in enumerate(spans)
        if kinds[n] == "video"
        and share(sung, span["start"] + offset, span["end"] + offset) >= SUNG_MIN
    ]
    by_length = sorted(sung_spans, key=lambda n: spans[n]["start"] - spans[n]["end"])
    chosen = sorted(by_length[:wanted])
    out, sing_at, rest_at = [], 0, 0
    for n in range(len(spans)):
        if n in chosen:
            out.append(singing[sing_at % len(singing)])
            sing_at += 1
        else:
            out.append(others[rest_at % len(others)])
            rest_at += 1
    return out, chosen


# ------------------------------------------------------------------ when each line is sung
def sounding_span(path: Path) -> tuple[float, float]:
    """Where the sound starts and stops, leaving out silence at either end."""
    left, right, sr = media.decode_stereo(path)
    level = np.abs((left + right) / 2)
    found = np.flatnonzero(level > media.SOUND_FLOOR)
    if not found.size:
        return 0.0, float(level.size / max(sr, 1))
    return float(found[0] / sr), float(found[-1] / sr)


def _estimated_cues(lines: list[str], start: float, end: float) -> list[Cue]:
    """No transcript: spread the lines through the track by how many words each has."""
    weights = [max(len(line.split()), 1) for line in lines]
    span = max(end - start - INTRO_GUARD_SEC, LEAST_LINE_SEC * len(lines))
    at = start + INTRO_GUARD_SEC
    cues = []
    for line, weight in zip(lines, weights, strict=True):
        length = span * weight / sum(weights)
        cues.append({"start_sec": round(at, 3), "end_sec": round(at + length, 3), "text": line})
        at += length
    return cues


def _tokens_by_line(lines: list[str]) -> tuple[list[str], list[int]]:
    tokens, owners = [], []
    for n, line in enumerate(lines):
        for token in re.findall(r"[a-z0-9']+", line.lower()):
            tokens.append(token)
            owners.append(n)
    return tokens, owners


def _matched_times(
    lines: list[str], heard: list[dict[str, Any]]
) -> dict[int, list[tuple[float, float]]]:
    """Each line's words, matched in order against what was heard."""
    tokens, owners = _tokens_by_line(lines)
    spoken = [re.sub(r"[^a-z0-9']", "", str(w.get("text", "")).lower()) for w in heard]
    matcher = difflib.SequenceMatcher(a=tokens, b=spoken, autojunk=False)
    times: dict[int, list[tuple[float, float]]] = {}
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            word = heard[block.b + k]
            spot = (float(word["start_sec"]), float(word["end_sec"]))
            times.setdefault(owners[block.a + k], []).append(spot)
    return times


def _fill_unheard(cues: list[Cue | None], lines: list[str], start: float, end: float) -> list[Cue]:
    """A line the transcript missed sits between its heard neighbours."""
    out: list[Cue] = []
    for n, cue in enumerate(cues):
        if cue:
            out.append(cue)
            continue
        before = out[-1]["end_sec"] if out else start
        after = next((c["start_sec"] for c in cues[n + 1 :] if c), end)
        out.append(
            {
                "start_sec": round(float(before), 3),
                "end_sec": round(float(max(after, before + LEAST_LINE_SEC)), 3),
                "text": lines[n],
            }
        )
    return out


def timed_lines(
    path: Path, song: dict[str, Any], heard: list[dict[str, Any]] | None
) -> tuple[list[Cue], str]:
    """Each lyric line with its time, and whether that time was heard or estimated."""
    lines = [line for section in song["sections"] for line in section.get("lines") or []]
    start, end = sounding_span(path)
    if not lines:
        return [], "none"
    if not heard:
        return _estimated_cues(lines, start, end), "estimated"
    times = _matched_times(lines, heard)
    if not times:
        return _estimated_cues(lines, start, end), "estimated"
    cues: list[Cue | None] = [
        {
            "start_sec": round(times[n][0][0], 3),
            "end_sec": round(times[n][-1][1], 3),
            "text": lines[n],
        }
        if n in times
        else None
        for n in range(len(lines))
    ]
    return _fill_unheard(cues, lines, start, end), "heard"


# ------------------------------------------------------------------ a sung take and its line
def sung_line(job: Job, beat: dict[str, Any], dst: Path) -> float:
    """A singing shot's line: the vocal stem from where the shot starts on the piece's clock, so
    the voice that moves the mouth is what is heard over it. Returns how much of it is sung."""
    stem = job.work / "vocals.wav"
    if not stem.is_file():
        raise ContractError(f"{job.id}: {beat['id']} sings, and the job has no vocal stem")
    start, end = float(beat["sings"]["start_sec"]), float(beat["sings"]["end_sec"])
    media.run(["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", str(stem), str(dst)])
    return share(voiced(stem), start, end)


def offset_of(readings: dict[str, Any]) -> float:
    """How late a sung take's lips run behind its line, in seconds, as its lip judge measured it
    (`<judge>.offset_sec`): negative when they run early. Nothing measured is no offset."""
    found = [v for k, v in (readings.get("judged") or {}).items() if k.endswith(".offset_sec")]
    return float(found[0]) if found else 0.0


def slip(clip: Path, late: float, fps: float = 25.0) -> float:
    """Line a sung clip's picture up with its line, as an editor slips picture against sound: lips
    that run late start that far into the clip, and lips that run early wait on the first frame.
    The clip keeps its length, its last or first frame held, and nothing in it is redrawn. Returns
    the seconds slipped; under half a frame is left alone."""
    if abs(late) < 0.5 / fps:
        return 0.0
    out = clip.with_suffix(".slipped.mp4")
    length = media.duration(clip)
    hold = (
        f"tpad=stop_mode=clone:stop_duration={late:.3f}"
        if late > 0
        else (f"tpad=start_mode=clone:start_duration={-late:.3f}")
    )
    head = ["-ss", f"{late:.3f}"] if late > 0 else []
    media.run([*head, "-i", str(clip), "-vf", hold, "-t", f"{length:.3f}", "-an", "-c:v", "libx264",
               "-crf", "10", "-pix_fmt", "yuv420p", str(out)])  # fmt: skip
    out.replace(clip)
    return round(late, 3)
