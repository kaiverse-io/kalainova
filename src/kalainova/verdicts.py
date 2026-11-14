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

from .blobstore import sha256_file
from .jobfs import ContractError, Job

VERDICTS_FILE = "verdicts.jsonl"
CHOICES = ("accept", "fix", "reject")
GOOD = {"accept"}
ENOUGH_OF_EACH = 3  # with fewer than this on either side, any separation is luck
SEPARATES_AT = 0.8
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def _known_take(job: Job, shot: str | None, take: int) -> None:
    shots = _json(job.folder / "takes.json").get("shots") or {}
    if shot:
        entry = shots.get(shot)
        if not entry or not any(t["n"] == take for t in entry.get("takes", [])):
            raise ContractError(f"{job.id}: {shot} has no take {take} to give a verdict on")
    else:
        found = any(any(t["n"] == take for t in entry.get("takes", [])) for entry in shots.values())
        if not found:
            raise ContractError(f"{job.id}: has no take {take} to give a verdict on")


def _check_record_args(
    job: Job,
    verdict: str,
    reviewer: str,
    shot: str | None,
    take: int | None,
    preferred: int | None,
    over: int | None,
    animatic: bool,
) -> None:
    if verdict not in CHOICES:
        raise ContractError(f"a verdict is one of {CHOICES}, not {verdict!r}")
    if not reviewer.strip():
        raise ContractError("a verdict names the person who gave it")
    if (preferred is not None and over is None) or (over is not None and preferred is None):
        raise ContractError("a preference needs both --preferred and --over")
    if preferred is not None and over is not None:
        if preferred == over:
            raise ContractError("a take cannot be preferred over itself")
        _known_take(job, shot, preferred)
        _known_take(job, shot, over)
    if take is not None:
        if not shot:
            raise ContractError("a verdict on a take names the shot it belongs to")
        _known_take(job, shot, take)
    if animatic and (shot or take is not None or preferred is not None):
        raise ContractError("a verdict on the animatic is on the whole rough cut, not one shot")
    if animatic and not job.has("animatic"):
        raise ContractError(f"{job.id}: no animatic to give a verdict on; run `kalainova animatic`")


def record(
    job: Job,
    verdict: str,
    *,
    reviewer: str,
    shot: str | None = None,
    note: str = "",
    take: int | None = None,
    preferred: int | None = None,
    over: int | None = None,
    animatic: bool = False,
) -> dict[str, Any]:
    """Write down what a person said. It has to name them, because a verdict is theirs.

    A verdict on a shot may name one of its takes, so each model's result in a bench gets its own.
    A preference names two takes of one shot or track: preferred over another.
    A verdict on the animatic is on the rough cut as it stands; the job records which cut it was.
    """
    _check_record_args(job, verdict, reviewer, shot, take, preferred, over, animatic)
    entry = {
        "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "verdict": verdict,
        "reviewer": reviewer,
        **({"stage": "animatic"} if animatic else {}),
        **({"shot": shot} if shot else {}),
        **({"take": take} if take is not None else {}),
        **({"preferred": preferred, "over": over} if preferred is not None else {}),
        **({"note": note} if note else {}),
    }
    with open(job.folder / VERDICTS_FILE, "a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    if animatic:
        _note_animatic(job, entry)
    return entry


def _note_animatic(job: Job, entry: dict[str, Any]) -> None:
    """The job's own field for it: a person watched this cut, and said this."""
    data = job.job
    animatic_rec = job.read("animatic")
    stills = {}
    for shot in animatic_rec.get("shots", []):
        rel = shot.get("still")
        if rel and (job.work / rel).is_file():
            stills[shot["beat_id"]] = sha256_file(job.work / rel)
    data["animatic_reviewed"] = {
        "verdict": entry["verdict"],
        "reviewer": entry["reviewer"],
        "at": entry["at"],
        "animatic_sha256": animatic_rec["sha256"],
        **({"stills": stills} if stills else {}),
    }
    job.write("job", data)


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
    wanted = take if take is not None else entry.get("chosen")
    if wanted is None:
        return {}
    chosen: dict[str, Any] = next((t for t in entry["takes"] if t["n"] == wanted), {})
    points = {}
    for name, value in (chosen.get("readings") or {}).items():
        number = _number(value)
        if number is not None and name != "score":
            points[f"shot.{name}"] = (number, verdict)
    return points


def _source_points(folder: Path, shot: str, verdict: str) -> dict[str, tuple[float, str]]:
    """What the edit's own source clip for this shot reads, so a shot verdict meets its picture.

    It is a different reading from the piece's `source.shot_motion`, which is only the weakest shot:
    pairing both under one name would let a piece verdict and a shot verdict contradict each other.
    """
    from . import bar, media

    job = Job(folder)
    if not (job.has("edit_manifest") and job.has("asset_manifest")):
        return {}
    try:
        moved = bar.sources.generated_shot_motion(
            job.work,
            _json(job.path("edit_manifest")),
            _json(job.path("asset_manifest")),
            only=f"{shot}.video",
        )
    except (media.MediaError, OSError, KeyError, ValueError):
        return {}  # the media is gone or unreadable: leave the sample out rather than guess
    return {"shot.source_motion": (moved[f"{shot}.video"], verdict)} if moved else {}


def samples(jobs_root: Path) -> list[dict[str, Any]]:
    """Every reading paired with every verdict it can be held against, one row each."""
    rows: list[dict[str, Any]] = []
    for folder in sorted(p for p in jobs_root.iterdir() if p.is_dir()):
        for entry in load(folder):
            if entry.get("stage") == "animatic" or entry.get("preferred") is not None:
                # Neither rough-cut verdicts nor preferences between takes are binary samples.
                continue
            shot = entry.get("shot")
            if shot:
                found = _shot_points(folder, shot, entry["verdict"], entry.get("take"))
                found.update(_source_points(folder, shot, entry["verdict"]))
            else:
                found = _piece_points(folder, entry["verdict"])
            for signal, (value, verdict) in found.items():
                rows.append(
                    {
                        "job": folder.name,
                        "shot": shot or "",
                        "reading": signal,
                        "value": value,
                        "verdict": verdict,
                    }
                )
    return rows


def _gather(jobs_root: Path) -> dict[str, list[tuple[float, str]]]:
    gathered: dict[str, list[tuple[float, str]]] = {}
    for row in samples(jobs_root):
        gathered.setdefault(row["reading"], []).append((row["value"], row["verdict"]))
    return gathered


def separation(good: list[float], bad: list[float]) -> float:
    """The chance a good sample reads higher than a bad one. 0.5 means the reading tells nothing."""
    if not good or not bad:
        return 0.5
    wins = sum((g > b) + 0.5 * (g == b) for g in good for b in bad)
    return wins / (len(good) * len(bad))


NOT_ENOUGH = "not enough yet"


def _verdict_on(auc: float, enough: bool) -> str:
    if not enough:
        return NOT_ENOUGH
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


def _pref_lines(all_entries: list[tuple[str, dict[str, Any]]]) -> list[str]:
    lines = []
    for job_name, entry in all_entries:
        detail = []
        if entry.get("preferred") is not None:
            detail.append(f"preferred {entry['preferred']} over {entry['over']}")
        elif entry.get("take") is not None:
            detail.append(f"take {entry['take']}")
        if entry.get("note"):
            detail.append(f"note: {entry['note']}")
        if detail:
            shot_str = f" {entry['shot']}" if entry.get("shot") else ""
            lines.append(f"{job_name}{shot_str}: {entry['verdict']} ({', '.join(detail)})")
    return lines


def _table_lines(jobs_root: Path, rows: list[dict[str, Any]]) -> list[str]:
    lines = [f"{'job':<20} {'shot':<8} {'reading':<28} {'value':>9}  verdict"]
    lines += [
        f"{r['job']:<20} {r['shot'] or '-':<8} {r['reading']:<28} "
        f"{r['value']:>9.4g}  {r['verdict']}"
        for r in rows
    ]
    lines += ["", f"{'reading':<28} accept  not  separation  says"]
    for s in signals(jobs_root):
        shown = "" if s["reads"] == NOT_ENOUGH else str(s["separation"])
        lines.append(f"{s['signal']:<28} {s['good']:>6}  {s['bad']:>3}  {shown:>10}  {s['reads']}")
    return lines


def review_set(jobs_root: Path) -> str:
    """The set as one table, then what each reading can honestly say about it."""
    all_entries = []
    if jobs_root.is_dir():
        for folder in sorted(p for p in jobs_root.iterdir() if p.is_dir()):
            for entry in load(folder):
                all_entries.append((folder.name, entry))
    if not all_entries:
        return "no verdicts yet, so nothing can be said"
    lines: list[str] = []
    prefs = _pref_lines(all_entries)
    if prefs:
        lines.extend(prefs)
        lines.append("")
    rows = samples(jobs_root)
    if rows:
        lines.extend(_table_lines(jobs_root, rows))
    elif not prefs:
        return "no verdicts yet, so nothing can be said"
    return "\n".join(lines).strip()
