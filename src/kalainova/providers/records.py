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

from .. import trace
from ..blobstore import sha256_file
from ..jobfs import Job
from . import base
from .contract import Receipt, Result

GENERATIONS = "generations.jsonl"
PRICED = ("price_source", "table_cost", "vendor_cost")  # how a charge was priced, kept beside it


def settle_at_vendor(p: base.Provider, res: Result, receipt: Receipt) -> None:
    """Settle at the higher of the price table and what the vendor says it billed (its billed units
    times the account's unit price), and keep both beside the charge. A vendor's unit price can be a
    base rate that a resolution multiplies, so neither figure alone is trusted until the vendor's
    billing record confirms it; the higher one keeps the cost cap safe."""
    meta = dict(res.meta or {})
    if receipt.vendor_cost is not None:
        meta.update(table_cost=round(res.cost, 6), vendor_cost=receipt.vendor_cost)
        meta.update(billed_units=receipt.billed_units)
        meta["price_source"] = "higher of the price table and vendor billed units x unit price"
        res.cost = max(res.cost, receipt.vendor_cost)
    elif not p.free:
        meta["price_source"] = "price table"
    res.meta = meta


def saved(job: Job, key: str, dst: Path, names: list[str]) -> tuple[base.Provider, Result] | None:
    """A recorded file, if it is still the same bytes from a provider this job still lists."""
    path = job.folder / GENERATIONS
    if not path.exists() or not dst.is_file():
        return None
    entries = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    entry = next((e for e in reversed(entries) if e["key"] == key), None)
    if not entry or entry["provider"] not in names or entry["sha256"] != sha256_file(dst):
        return None
    provider = base.get(entry["provider"])
    meta = dict(entry.get("meta") or {})
    seed = meta.get("seed")
    return provider, Result(
        path=dst,
        model=entry["model"],
        words=entry["words"],
        seed=int(seed) if isinstance(seed, int | float) else None,
        meta=meta,
    )


def audit(
    aid: str, model: str | None, meta: dict[str, Any] | None, receipt: Receipt
) -> dict[str, Any]:
    """What a ledger entry and a generation record carry so an auditor can join them to the trace
    row (attempt), to the vendor's bill (request_id), and to the part of the line (labels)."""
    billed = {k: v for k, v in (meta or {}).items() if k.startswith("billed_") or k in PRICED}
    rid = receipt.request_id
    return {**trace.labels(), "attempt": aid, "model": model, "request_id": rid, **billed}


def record(
    job: Job, key: str, provider: base.Provider, res: Result, dst: Path, aid: str, receipt: Receipt
) -> None:
    entry = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        **audit(aid, res.model, res.meta, receipt),
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
    receipt: Receipt,
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
            model=made or asked or provider.default_model(capability),
            model_version=model_version,
            started_at=started_at,
            elapsed_sec=time.monotonic() - started,
            outcome=outcome,
            estimated_cost=estimate or 0.0,
            settled_cost=settled,
            error_class=error_class,
            attempt=aid,
            request_id=receipt.request_id,
            error_detail=detail,
            units={k: v for k, v in (meta or {}).items() if k.startswith("billed_")},
        )
