"""STREAM: where a recurring line of pieces goes. One identity, one strategy, its kits, its limits.

A channel, a star's account, a client's account, and a series are all streams.

  streams/<id>/stream.json    identity, strategy, kit pins, generators, posting limit
  streams/<id>/canon.jsonl    append-only story facts, added by a human
  streams/<id>/schedule.json  dated slots; each still passes the human gate when it becomes a job
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from . import consistency, kitrules, kits
from .jobfs import ContractError, Job, validate

MAX_OPEN_SLOTS = 30
Stream = dict[str, Any]


def stream_dir(root: Path, stream_id: str) -> Path:
    return root / "streams" / stream_id


def load(root: Path, stream_id: str) -> Stream:
    path = stream_dir(root, stream_id) / "stream.json"
    if not path.exists():
        known = sorted(p.parent.name for p in (root / "streams").glob("*/stream.json"))
        raise ContractError(f"no stream {stream_id!r}; known: {', '.join(known) or 'none'}")
    data: Stream = json.loads(path.read_text())
    validate("stream", data, str(path))
    return data


def create(root: Path, data: Stream) -> Path:
    """Write a new stream after proving its kits resolve and its identity is its own."""
    stream_id = data["stream_id"]
    if not kitrules.NAME.match(stream_id):
        raise ContractError(f"stream id {stream_id!r}: use lowercase letters, digits, - and _")
    path = stream_dir(root, stream_id) / "stream.json"
    if path.exists():
        raise ContractError(f"stream {stream_id} exists")
    validate("stream", data, f"streams/{stream_id}/stream.json")
    for other in (root / "streams").glob("*/stream.json"):
        theirs = json.loads(other.read_text())
        if theirs.get("distribution_identity") == data["distribution_identity"]:
            raise ContractError(
                f"identity {data['distribution_identity']!r} belongs to stream "
                f"{theirs.get('stream_id')}; one identity, one stream"
            )
    consistency.resolve(root, data)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return path


# ------------------------------------------------------------------- canon
def canon_path(root: Path, stream_id: str) -> Path:
    return stream_dir(root, stream_id) / "canon.jsonl"


def canon_add(root: Path, stream_id: str, fact: str, *, by: str) -> dict[str, Any]:
    """A human adds a story fact. It is fiction, and nothing rewrites earlier lines."""
    load(root, stream_id)
    if not by.strip() or not fact.strip():
        raise ContractError("canon needs a fact and the human adding it")
    entry = {"fact": fact.strip(), "by": by, "at": dt.date.today().isoformat(), "fiction": True}
    with open(canon_path(root, stream_id), "a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def canon_facts(root: Path, stream_id: str) -> list[str]:
    path = canon_path(root, stream_id)
    if not path.exists():
        return []
    return [json.loads(line)["fact"] for line in path.read_text().splitlines() if line.strip()]


# ---------------------------------------------------------------- schedule
def schedule_path(root: Path, stream_id: str) -> Path:
    return stream_dir(root, stream_id) / "schedule.json"


def read_schedule(root: Path, stream_id: str) -> dict[str, Any]:
    path = schedule_path(root, stream_id)
    if not path.exists():
        return {"schema_version": "0.1", "stream_id": stream_id, "slots": []}
    data: dict[str, Any] = json.loads(path.read_text())
    validate("schedule", data, str(path))
    return data


def schedule_add(
    root: Path, stream_id: str, date: str, brief: str, *, cast: list[str] | None = None
) -> dict[str, Any]:
    """Add a dated slot. Nothing renders: a slot becomes a job only when someone requests it."""
    stream = load(root, stream_id)
    try:
        dt.date.fromisoformat(date)
    except ValueError as exc:
        raise ContractError(f"slot date {date!r} must be YYYY-MM-DD") from exc
    schedule = read_schedule(root, stream_id)
    slots = schedule["slots"]
    if sum(s["status"] == "open" for s in slots) >= MAX_OPEN_SLOTS:
        raise ContractError(f"{stream_id}: already {MAX_OPEN_SLOTS} open slots")
    limit = stream["max_per_day"]
    if sum(s["date"] == date for s in slots) >= limit:
        raise ContractError(f"{stream_id}: {date} already has {limit} slot(s), the daily limit")
    slot: dict[str, Any] = {"date": date, "brief": brief, "status": "open"}
    if cast:
        slot["cast"] = cast
    slots.append(slot)
    validate("schedule", schedule, f"streams/{stream_id}/schedule.json")
    schedule_path(root, stream_id).write_text(
        json.dumps(schedule, indent=2, ensure_ascii=False) + "\n"
    )
    return slot


def _next_job_id(root: Path, stream_id: str, date: str) -> str:
    stem = f"{stream_id}-{date.replace('-', '')}"
    number = 1
    while (root / "jobs" / f"{stem}-{number:02d}").exists():
        number += 1
    return f"{stem}-{number:02d}"


def _take_slot(root: Path, stream_id: str, date: str) -> tuple[str, list[str] | None]:
    schedule = read_schedule(root, stream_id)
    slot = next((s for s in schedule["slots"] if s["date"] == date and s["status"] == "open"), None)
    if slot is None:
        raise ContractError(f"{stream_id}: no open slot on {date}")
    return str(slot["brief"]), slot.get("cast")


def _mark_slot(root: Path, stream_id: str, date: str, job_id: str) -> None:
    schedule = read_schedule(root, stream_id)
    slot = next(s for s in schedule["slots"] if s["date"] == date and s["status"] == "open")
    slot.update(status="requested", job_id=job_id)
    schedule_path(root, stream_id).write_text(
        json.dumps(schedule, indent=2, ensure_ascii=False) + "\n"
    )


# ----------------------------------------------------------------- request
def _job_record(
    stream: Stream, job_id: str, brief: str, cast: list[str], fmt: dict[str, Any]
) -> dict[str, Any]:
    pins = stream.get("generators") or {}
    record: dict[str, Any] = {
        "schema_version": "0.1",
        "job_id": job_id,
        "strategy": stream["strategy"],
        "media": stream["media"],
        "rights": stream["rights"],
        "distribution_identity": stream["distribution_identity"],
        "status": "draft",
        "cost_cap": stream["cost_cap_per_job"],
        "stream": stream["stream_id"],
        "cast": cast,
        "brief": {"subject": brief},
        "providers": {cap: [pin["provider"]] for cap, pin in pins.items()},
    }
    if stream.get("skip_funded"):
        record["skip_funded"] = True
    profile = fmt.get("profile") or stream.get("profile")
    if profile:
        record["profile"] = profile
    if fmt.get("edit"):
        record["edit"] = fmt["edit"]
    return record


def request(
    root: Path,
    stream_id: str,
    brief: str = "",
    *,
    cast: list[str] | None = None,
    slot: str | None = None,
    amplify: str = "",
    duration: int | None = None,
) -> Job:
    """Turn 'this channel, this brief' into a locked job. The engine works out everything else, and
    refuses before any money is spent if the channel cannot keep what it promises consistent."""
    stream = load(root, stream_id)
    if slot:
        if brief:
            raise ContractError("a slot already carries its brief; pass one or the other")
        brief, slot_cast = _take_slot(root, stream_id, slot)
        cast = cast or slot_cast
    if not brief.strip():
        raise ContractError("a request needs a brief")
    if amplify and not stream.get("amplification_allowed"):
        raise ContractError(
            f"{stream_id}: mentioning another brand is off; the operator opens it on the stream"
        )
    resolved = consistency.resolve(root, stream)
    chosen = consistency.choose_cast(resolved, cast)
    consistency.preflight(resolved, stream, chosen)
    date = slot or dt.date.today().isoformat()
    job_id = _next_job_id(root, stream_id, date)
    record = _job_record(stream, job_id, brief, chosen, resolved.shared.get("format") or {})
    if amplify:
        record["brief"]["amplification"] = amplify
    if duration:
        record["brief"]["duration_sec"] = duration
    folder = root / "jobs" / job_id
    folder.mkdir(parents=True)
    job = Job(folder)
    job.write("job", record)
    job.write("kit_lock", consistency.build_lock(resolved, stream, job_id, chosen))
    if slot:
        _mark_slot(root, stream_id, slot, job_id)
    return job


def posted_on(root: Path, stream_id: str, date: str) -> int:
    """Posts this stream made on a date, across all of its jobs."""
    count = 0
    for log in (root / "jobs").glob("*/publish_log.json"):
        job = json.loads((log.parent / "job.json").read_text())
        if job.get("stream") != stream_id:
            continue
        for post in json.loads(log.read_text()).get("posts", []):
            if post.get("status") == "posted" and str(post.get("at", "")).startswith(date):
                count += 1
    return count


def show(root: Path, stream_id: str) -> str:
    """What this stream keeps fixed and how, read from the kits it pins."""
    stream = load(root, stream_id)
    resolved = consistency.resolve(root, stream)
    lines = [
        f"stream {stream_id}: {stream['strategy']} on {stream['distribution_identity']}, "
        f"up to {stream['max_per_day']} a day, cap {stream['cost_cap_per_job']} a job",
        f"accounts: {stream.get('accounts') or 'none'}",
        f"generators: {stream.get('generators') or 'studio defaults'}",
        f"cast: {', '.join(resolved.characters) or 'none'}",
        f"canon facts: {len(canon_facts(root, stream_id))}",
        "",
        *consistency.explain(resolved),
    ]
    missing = [p for k in resolved.kits.values() for p in kits.verify_files(root, k)]
    if missing:
        lines += ["", "PROBLEMS:", *missing]
    return "\n".join(lines)
