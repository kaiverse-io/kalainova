"""Observability telemetry for engine router calls.

Appends rows to trace.jsonl in the job folder recording elapsed time, outcome,
cost, and provider metadata. Writing never fails a job.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .jobfs import Job

TRACE_FILE = "trace.jsonl"
OUTCOMES = ("ok", "refused", "timeout", "error")

logger = logging.getLogger(__name__)


def record(
    job: Job,
    *,
    capability: str,
    provider: str,
    model: str,
    started_at: str,
    elapsed_sec: float,
    outcome: str,
    stage: str = "",
    run_id: str = "",
    model_version: str | None = None,
    error_class: str | None = None,
    retries: int = 0,
    estimated_cost: float = 0.0,
    settled_cost: float = 0.0,
    units: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Write one call's telemetry row to trace.jsonl. Never raises."""
    if outcome not in OUTCOMES:
        outcome = "error"
    row = {
        "run_id": run_id or job.id,
        "stage": stage,
        "capability": capability,
        "provider": provider,
        "model": model,
        "model_version": model_version,
        "started_at": started_at,
        "elapsed_sec": round(max(0.0, float(elapsed_sec)), 3),
        "outcome": outcome,
        "error_class": error_class,
        "retries": int(retries),
        "estimated_cost": round(max(0.0, float(estimated_cost)), 4),
        "settled_cost": round(max(0.0, float(settled_cost)), 4),
        "units": units or {},
    }
    try:
        path = job.folder / TRACE_FILE
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        return row
    except Exception as exc:
        logger.warning("%s: failed to write trace row: %s", job.id, exc)
        return None


def load(job: Job) -> list[dict[str, Any]]:
    """Load trace rows for a job."""
    path = job.folder / TRACE_FILE
    if not path.is_file():
        return []
    try:
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except Exception as exc:
        logger.warning("%s: failed to read trace: %s", job.id, exc)
        return []
