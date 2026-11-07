"""What an editor decides before a cut: which take, in what order, at what length, and what to fix.

Pure functions over the footage's readings, so each decision is proved without any media.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

Fields = dict[str, Any]
Shot = dict[str, Any]

# Beats per shot. An edit that cuts every N beats is a metronome, so each pace repeats a phrase.
BEAT_PHRASE = {
    "fast": [2, 2, 4, 2, 2, 6],
    "medium": [4, 4, 2, 2, 4, 8],
    "cinematic": [8, 8, 4, 12, 8],
}


MIN_QUALITY = 0.45


MAX_ENLARGE = 2.0  # past this, a source reads as soft on any good screen


SIMILAR_MIN_CORR = 0.9  # shots this alike read as the same shot twice


# Pauses in speech: leave short ones, shorten long ones, and never leave a sliver between two cuts.
MIN_PAUSE_TO_CUT_SEC = 0.9


PAUSE_KEPT_SEC = 0.3


MIN_SPEECH_SEC = 1.5


# ------------------------------------------------------------------ helpers
def defects(shot: Shot) -> list[str]:
    """Reasons an editor would reject this take outright, whatever its average score."""
    sc = shot["scores"]
    out: list[str] = []
    # absolute jitter (px/frame² at 160 px analysis width): steady < 1, handheld ~2, shaky > 3
    if shot["kind"] == "video" and (
        shot.get("jitter_px", 0) > 3.0 or (sc["shake"] > 0.7 and shot.get("jitter_px", 9) > 1.5)
    ):
        out.append("shaky")
    if shot["kind"] == "video" and sc["sharpness"] < 0.15:
        out.append("soft focus")
    if sc["exposure"] < 0.35:
        out.append("badly exposed")
    return out


def matches(shot: Shot, sources: Fields, needle: str) -> bool:
    needle = needle.lower().strip()
    if not needle:
        return False
    name = sources[shot["source"]]["name"].lower()
    return needle == shot["id"] or needle == shot["source"] or needle in name


def gamma(shot: Shot) -> float:
    """A small exposure nudge for a shot that is truly off. Night stays night."""
    lum = shot["series"]["lum"]
    level = sum(lum) / len(lum) if lum else 0.46
    if 0.15 <= level <= 0.75:
        return 1.0
    level = min(max(level, 0.05), 0.95)
    # A gamma above 1 brightens, so the exponent landing on mid-grey is log(level) / log(mid-grey).
    return round(min(max(math.log(level) / math.log(0.46), 0.85), 1.25), 3)


def beats_for(pace: str, index: int) -> int:
    phrase = BEAT_PHRASE[pace]
    return phrase[index % len(phrase)]


def _looks_like(a: list[float], b: list[float]) -> bool:
    x, y = np.array(a, np.float64), np.array(b, np.float64)
    if x.size != y.size or x.std() == 0 or y.std() == 0:
        return False
    return float(np.corrcoef(x, y)[0, 1]) >= SIMILAR_MIN_CORR


def next_moment(
    pool: list[Fields],
    used: list[list[float]],
    last_source: str | None,
    *,
    usage: dict[str, int] | None = None,
    need: float = 0.0,
) -> Fields | None:
    """The next moment unlike anything used. None means the footage has run out of new shots.

    It leans to the source used least, so two clips never just trade turns, and to a shot long
    enough for the length the rhythm wants, so the rhythm survives contact with the footage.
    """
    fresh = [m for m in pool if not any(_looks_like(m["shot"].get("sig", []), sig) for sig in used)]
    if not fresh:
        return None
    counts = usage or {}

    def rank(m: Fields) -> tuple[bool, bool, int]:
        shot = m["shot"]
        span = shot.get("out_sec", 0) - shot.get("in_sec", 0)
        return (span < need, shot["source"] == last_source, counts.get(shot["source"], 0))

    return min(fresh, key=rank)


def speech_keeps(silences: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    """What to keep of a take. Speech is never cut, and each long pause keeps a natural breath."""
    keep: list[tuple[float, float]] = []
    start = 0.0
    for a, b in silences:
        if b - a < MIN_PAUSE_TO_CUT_SEC:
            continue
        end = a + PAUSE_KEPT_SEC / 2
        if end - start >= MIN_SPEECH_SEC:
            keep.append((round(start, 3), round(end, 3)))
            start = b - PAUSE_KEPT_SEC / 2
    keep.append((round(start, 3), round(duration, 3)))
    return keep


def _story_order(shots: list[Shot]) -> list[Shot]:
    """The strongest moving shot as the hook, the rest in capture order, a calm wide to close."""
    rest = sorted(shots, key=lambda x: (x["source"], x["in_sec"]))
    if not rest:
        return []
    hook = max(rest, key=lambda x: x["quality"] + 0.25 * x["scores"]["motion"])
    rest = [x for x in rest if x is not hook]
    if len(rest) <= 2:
        return [hook, *rest]
    closer = max(rest, key=lambda x: x["quality"] - 0.3 * x["scores"]["motion"])
    return [hook, *[x for x in rest if x is not closer], closer]


def _in_order(shots: list[Shot], name: str) -> list[Shot]:
    if name == "chronological":
        return sorted(shots, key=lambda x: (x["source"], x["in_sec"]))
    if name == "best_first":
        return sorted(shots, key=lambda x: -x["quality"])
    return _story_order(shots)


def order(shots: list[Shot], s: Fields, sources: Fields) -> list[Shot]:
    """The shots in the order asked for, with any named first or last shot moved there."""
    ordered = _in_order(shots, s["order"])
    for key, at_end in (("start_with", False), ("end_with", True)):
        hit = next((x for x in ordered if s[key] and matches(x, sources, s[key])), None)
        if hit:
            ordered.remove(hit)
            ordered.insert(len(ordered) if at_end else 0, hit)
    return ordered


def too_small(cuts: list[Fields], sources: Fields, prof: Fields) -> list[str]:
    """Sources this edit has to enlarge past what still looks sharp, named for the operator."""
    found: set[str] = set()
    for cut in cuts:
        src = sources[cut["source"]]
        fit = max(
            prof["width"] / max(src.get("width", 1), 1),
            prof["height"] / max(src.get("height", 1), 1),
        )
        if fit > MAX_ENLARGE:
            found.add(src["name"])
    return sorted(found)
