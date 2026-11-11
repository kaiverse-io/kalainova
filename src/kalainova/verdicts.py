"""What a person said about a piece, and which readings predicted it.

A verdict is a person's words, written down. It is not an approval, and nothing here can publish
anything. ADR 0011 keeps a reading only if it separates good from bad on reviewed samples, and this
is how that gets checked: every reading against every verdict, with no opinion in between.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from typing import Any

from .jobfs import ContractError, Job

VERDICTS_FILE = "verdicts.jsonl"
CHOICES = ("accept", "fix", "reject")
GOOD = {"accept"}
ENOUGH_OF_EACH = 3  # with fewer than this on either side, any separation is luck
SEPARATES_AT = 0.8
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _known_take(job: Job, shot: str, take: int) -> None:
    entry = (_json(job.folder / "takes.json").get("shots") or {}).get(shot)
    if not entry or not any(t["n"] == take for t in entry["takes"]):
        raise ContractError(f"{job.id}: {shot} has no take {take} to give a verdict on")


def record(
    job: Job,
    verdict: str,
    *,
    reviewer: str,
    shot: str | None = None,
    note: str = "",
    take: int | None = None,
) -> dict[str, Any]:
    """Write down what a person said. It has to name them, because a verdict is theirs.

    A verdict on a shot may name one of its takes, so each model's result in a bench gets its own.
    """
    if verdict not in CHOICES:
        raise ContractError(f"a verdict is one of {CHOICES}, not {verdict!r}")
    if not reviewer.strip():
        raise ContractError("a verdict names the person who gave it")
    if take is not None:
        if not shot:
            raise ContractError("a verdict on a take names the shot it belongs to")
        _known_take(job, shot, take)
    entry = {
        "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "verdict": verdict,
        "reviewer": reviewer,
        **({"shot": shot} if shot else {}),
        **({"take": take} if take is not None else {}),
        **({"note": note} if note else {}),
    }
    with open(job.folder / VERDICTS_FILE, "a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def load(folder: Path) -> list[dict[str, Any]]:
    path = folder / VERDICTS_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    found = _NUMBER.match(str(value))
    return float(found.group()) if found else None


def _json(path: Path) -> dict[str, Any]:
    return dict(json.loads(path.read_text())) if path.exists() else {}


def _piece_points(folder: Path, verdict: str) -> dict[str, tuple[float, str]]:
    readings = (_json(folder / "qa.json").get("bar") or {}).get("readings") or []
    points = {}
    for reading in readings:
        value = _number(reading.get("value"))
        if value is not None:
            points[str(reading["id"])] = (value, verdict)
    return points


def _shot_points(
    folder: Path, shot: str, verdict: str, take: int | None = None
) -> dict[str, tuple[float, str]]:
    entry = (_json(folder / "takes.json").get("shots") or {}).get(shot)
    if not entry:
        return {}
    wanted = entry["chosen"] if take is None else take
    chosen: dict[str, Any] = next((t for t in entry["takes"] if t["n"] == wanted), {})
    points = {}
    for name, value in (chosen.get("readings") or {}).items():
        number = _number(value)
        if number is not None and name != "score":
            points[f"shot.{name}"] = (number, verdict)
    return points


def _gather(jobs_root: Path) -> dict[str, list[tuple[float, str]]]:
    gathered: dict[str, list[tuple[float, str]]] = {}
    for folder in sorted(p for p in jobs_root.iterdir() if p.is_dir()):
        for entry in load(folder):
            shot = entry.get("shot")
            found = (
                _shot_points(folder, shot, entry["verdict"], entry.get("take"))
                if shot
                else _piece_points(folder, entry["verdict"])
            )
            for signal, point in found.items():
                gathered.setdefault(signal, []).append(point)
    return gathered


def separation(good: list[float], bad: list[float]) -> float:
    """The chance a good sample reads higher than a bad one. 0.5 means the reading tells nothing."""
    if not good or not bad:
        return 0.5
    wins = sum((g > b) + 0.5 * (g == b) for g in good for b in bad)
    return wins / (len(good) * len(bad))


def _verdict_on(auc: float, enough: bool) -> str:
    if not enough:
        return "too few verdicts"
    if auc >= SEPARATES_AT:
        return "higher is better"
    if auc <= 1 - SEPARATES_AT:
        return "lower is better"
    return "does not separate: ADR 0011 says delete it"


def signals(jobs_root: Path) -> list[dict[str, Any]]:
    """Every reading against every verdict. The readings that tell you nothing say so."""
    rows = []
    for signal, points in sorted(_gather(jobs_root).items()):
        good = [v for v, verdict in points if verdict in GOOD]
        bad = [v for v, verdict in points if verdict not in GOOD]
        auc = separation(good, bad)
        enough = len(good) >= ENOUGH_OF_EACH and len(bad) >= ENOUGH_OF_EACH
        rows.append(
            {
                "signal": signal,
                "good": len(good),
                "bad": len(bad),
                "separation": round(auc, 3),
                "reads": _verdict_on(auc, enough),
            }
        )
    return rows
