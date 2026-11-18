"""Learned judges: models that score how a take strikes a listener or a viewer, as a number.

A reading checks what a brief asked for: the tempo, the length, the words. A judge is trained to
agree with people about quality, which no reading can say. Each is a command in its own
environment, named under `judges` in config/studio.yaml by the kind of file it reads, so the
engine imports no judge's code and ships no model. A judge is swapped, or a second added, in the
config alone. The command takes `--out FILE` and file paths after it, and writes
`{path: {score name: number}}` (providers/runners/ holds one script per tool).

A judge's score ranks takes and never blocks. None has been shown to agree with this studio's
own choices yet, and none is told what the brief asked for, so a take it likes can still miss
the brief. A judge that fails, or says nothing of a file, is reported and skipped, and the piece
goes on.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import config, opentools

TIMEOUT_SEC = 1800  # a model loads once per run, then scores every file


@dataclass(frozen=True)
class Judge:
    name: str
    command: tuple[str, ...]
    rank_by: str | None = None  # the score of this judge that ranks takes, when it is the first


def configured(kind: str) -> list[Judge]:
    """The judges set for a kind of file, such as "song", in the order the config lists them."""
    rows: list[dict[str, Any]] = list((config.studio().get("judges") or {}).get(kind) or [])
    return [
        Judge(
            name=str(row["name"]),
            command=tuple(str(Path(part).expanduser()) for part in row["command"]),
            rank_by=row.get("rank_by"),
        )
        for row in rows
        if row.get("command")
    ]


def _run(judge: Judge, wanted: list[str]) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        out_file = Path(tmp) / "scores.json"
        run = opentools.run([*judge.command, "--out", str(out_file), *wanted], timeout=TIMEOUT_SEC)
        if run.returncode != 0:
            raise ValueError(f"failed: {run.stderr.strip()[-300:]}")
        try:
            found = json.loads(out_file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"wrote no readable JSON: {exc}") from exc
    if not isinstance(found, dict):
        raise ValueError("wrote JSON that is not an object of files")
    return found


def score(kind: str, paths: list[Path]) -> tuple[dict[Path, dict[str, float]], list[str]]:
    """Every configured judge over every file, one run each: `{path: {"judge.score": n}}`, and
    what went wrong, which never stops the piece."""
    scores: dict[Path, dict[str, float]] = {p: {} for p in paths}
    notes: list[str] = []
    wanted = [str(p.resolve()) for p in paths]
    for judge in configured(kind):
        try:
            found = _run(judge, wanted)
        except ValueError as exc:
            notes.append(f"judge {judge.name} {exc}")
            continue
        for path, key in zip(paths, wanted, strict=True):
            row = found.get(key)
            if not isinstance(row, dict):
                notes.append(f"judge {judge.name} said nothing of {path.name}")
                continue
            for name, value in row.items():
                if isinstance(value, int | float):
                    scores[path][f"{judge.name}.{name}"] = round(float(value), 4)
    return scores, notes


def rank_key(kind: str) -> str | None:
    """The score that ranks takes: the first judge's `rank_by`, or none when no judge is set."""
    first = next(iter(configured(kind)), None)
    return f"{first.name}.{first.rank_by}" if first and first.rank_by else None


def rank_value(kind: str, judged: dict[str, float]) -> float | None:
    key = rank_key(kind)
    return judged.get(key) if key else None


def of_take(kind: str, path: Path) -> dict[str, Any]:
    """What a take's record keeps of its judges: every score, and the one that ranks it. Nothing
    when no judge is set; a judge that fails says so here and is left out."""
    if not configured(kind):
        return {}
    scores, notes = score(kind, [path])
    for note in notes:
        print(f"{path.name}: {note}", file=sys.stderr)
    return {"judged": scores[path], "rank": rank_value(kind, scores[path])}
