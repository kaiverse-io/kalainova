"""What one model call leaves behind, so it can be audited and reused.

Three records in the job folder, joined by the attempt id the router gives each call: the trace row
(`trace.jsonl`, every attempt), the ledger entry (`ledger.json`, every charge, written by
`Job.charge` with `audit` as its detail), and the generation record (`generations.jsonl`, every
kept file, which `saved` reads back so a restart reuses a paid file instead of paying again).
"""

from __future__ import annotations

import json
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .. import config, trace
from ..blobstore import sha256_file
from ..jobfs import Job
from . import base

GENERATIONS = "generations.jsonl"


def saved(
    job: Job, key: str, dst: Path, names: list[str]
) -> tuple[base.Provider, base.Result] | None:
    """A recorded file, if it is still the same bytes from a provider this job still lists."""
    path = job.folder / GENERATIONS
    if not path.exists() or not dst.is_file():
        return None
    entries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    entry = next((e for e in reversed(entries) if e["key"] == key), None)
    if not entry or entry["provider"] not in names or entry["sha256"] != sha256_file(dst):
        return None
    provider = base.get(entry["provider"])
    return provider, base.Result(
        path=dst, model=entry["model"], words=entry["words"], meta=entry["meta"]
    )


def audit(
    p: base.Provider, aid: str, model: str | None, meta: dict[str, Any] | None = None
) -> dict[str, Any]:
    """What a ledger entry and a generation record carry so an auditor can join them to the trace
    row (attempt), to the vendor's bill (request_id), and to the part of the line (labels)."""
    billed = {k: v for k, v in (meta or {}).items() if k.startswith("billed_")}
    rid = getattr(p, "request_id", None)
    return {**trace.labels(), "attempt": aid, "model": model, "request_id": rid, **billed}


def record(
    job: Job, key: str, provider: base.Provider, res: base.Result, dst: Path, aid: str
) -> None:
    entry = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        **audit(provider, aid, res.model, res.meta),
        "key": key,
        "provider": provider.name,
        "model": res.model,
        "file": dst.name,
        "sha256": sha256_file(dst),
        "cost": round(res.cost, 6),
        "words": res.words,
        "meta": res.meta,
    }
    with job.locked():
        with open(job.folder / GENERATIONS, "a") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def trace_attempt(
    job: Job,
    capability: str,
    provider: base.Provider,
    started_at: str,
    started: float,
    asked: str | None,
    aid: str,
    *,
    outcome: str,
    estimate: float | None,
    settled: float = 0.0,
    made: str | None = None,
    model_version: str | None = None,
    error_class: str | None = None,
    detail: str = "",
    meta: dict[str, Any] | None = None,
) -> None:
    """Telemetry is best-effort and must not change the provider call's result. The model is the
    one the adapter says it used, else the one asked for, else the provider's default."""
    with suppress(Exception):
        trace.record(
            job,
            capability=capability,
            provider=provider.name,
            model=made or asked or config.model_for(provider.name, capability),
            model_version=model_version,
            started_at=started_at,
            elapsed_sec=time.monotonic() - started,
            outcome=outcome,
            estimated_cost=estimate or 0.0,
            settled_cost=settled,
            error_class=error_class,
            attempt=aid,
            request_id=getattr(provider, "request_id", None),
            error_detail=detail,
            units={k: v for k, v in (meta or {}).items() if k.startswith("billed_")},
        )
