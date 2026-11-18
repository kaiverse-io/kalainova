"""The learned judges a take is read by, beside its plain readings (bar/judges.py, ADR 0024).

Two kinds apply to moving takes. A sung take is judged on how its lips follow its line
(`judges.lipsync`), with that line laid on its picture, so what is scored is the vocal the piece
plays over it. A take with a character in it is judged on how the person moves
(`judges.performance`): head, eyes, and body apart from the background, so a still person in a
moving frame does not read as a moving one. Each kind is set in config; with none set, nothing is
judged. A judge ranks; it never blocks a take.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import media
from .bar import judges
from .providers import rehearsal

Fields = dict[str, Any]
Assess = Callable[[Path], tuple[Fields, bool]]


def merged(readings: Fields, found: Fields) -> Fields:
    """One take's readings with a judge kind's scores added under `judged`. The first kind to
    rank a take keeps its rank."""
    if not found:
        return readings
    judged = {**(readings.get("judged") or {}), **(found.get("judged") or {})}
    out = {**readings, "judged": judged}
    if out.get("rank") is None and found.get("rank") is not None:
        out["rank"] = found["rank"]
    return out


def _on(kind: str) -> bool:
    return bool(judges.configured(kind)) and rehearsal.active() is None  # a stand-in has no face


def lips(path: Path, line: Path) -> Fields:
    """How the lips follow the line, with the line laid on the picture first."""
    if not _on("lipsync"):
        return {}
    heard = path.with_suffix(".sync.mp4")
    media.run(
        [
            "-i",
            str(path),
            "-i",
            str(line),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:v",
            "copy",
            "-shortest",
            str(heard),
        ]
    )
    return judges.of_take("lipsync", heard)


def performance(path: Path) -> Fields:
    """How the person on camera moves: head, eyes, and body apart from the background."""
    return judges.of_take("performance", path) if _on("performance") else {}


def judged(path: Path, *, line: Path | None = None, on_camera: bool = False) -> Fields:
    """Every judge that applies to a take, as one `judged` set (empty when none applies)."""
    found: Fields = lips(path, line) if line else {}
    return merged(found, performance(path)) if on_camera else found


def judged_sung(assess: Assess, line: Path) -> Assess:
    """`assess`, and the lip judges over the take with its line laid on it."""
    if not _on("lipsync"):
        return assess

    def read(path: Path) -> tuple[Fields, bool]:
        readings, ok = assess(path)
        return merged(readings, lips(path, line)), ok

    return read


def judged_on_camera(assess: Assess, beat: Fields) -> Assess:
    """`assess`, and the performance judges when a character is in the shot."""
    if not beat.get("cast") or not _on("performance"):
        return assess

    def read(path: Path) -> tuple[Fields, bool]:
        readings, ok = assess(path)
        return merged(readings, performance(path)), ok

    return read
