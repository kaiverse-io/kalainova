"""Observability telemetry for engine router calls.

Appends rows to trace.jsonl in the job folder recording elapsed time, outcome,
cost, and provider metadata. Writing never fails a job.

Each row names where the call came from, so a fault or a cost maps to one part of the line:
the run (one engine command, `run_id`), the stage and the shot (set with `labelled` by whoever runs
them), the capability, and the attempt. The attempt id also stands on the ledger entry and the
generation record of the same call, and `request_id` is the vendor's own id for it, which is what
its bill lists. `engine` is the commit that ran the call, marked +dirty for uncommitted code.
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from typing import Any

from . import fingerprint
from .jobfs import Job

TRACE_FILE = "trace.jsonl"
OUTCOMES = ("ok", "refused", "timeout", "error")

logger = logging.getLogger(__name__)
RUN_ID = uuid.uuid4().hex[:12]  # one engine command, and every call it makes
_labels: ContextVar[dict[str, str]] = ContextVar("trace_labels", default={})  # noqa: B039


@contextmanager
def labelled(**labels: str) -> Iterator[None]:
    """Name the part of the line the calls inside come from: a stage, a shot."""
    token = _labels.set({**_labels.get(), **{k: v for k, v in labels.items() if v}})
    try:
        yield
    finally:
        _labels.reset(token)


def relabel(**labels: str) -> None:
    """Change labels for the rest of the enclosing `scoped` call, as a loop moves shot to shot."""
    now = {**_labels.get(), **labels}
    _labels.set({k: v for k, v in now.items() if v})


def scoped[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Run `fn` with its own labels: whatever it relabels is undone when it returns."""

    @wraps(fn)
    def inner(*args: P.args, **kwargs: P.kwargs) -> R:
        with labelled():
            return fn(*args, **kwargs)

    return inner


def labels() -> dict[str, str]:
    """The labels in force here: what a ledger entry or a generation record carries too."""
    return {"run_id": RUN_ID, **_labels.get()}


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
    attempt: str = "",
    request_id: str | None = None,
    error_detail: str = "",
) -> dict[str, Any] | None:
    """Write one call's telemetry row to trace.jsonl. Never raises."""
    if outcome not in OUTCOMES:
        outcome = "error"
    here = labels()
    row = {
        "run_id": run_id or here["run_id"],
        "stage": stage or here.get("stage", ""),
        "shot": here.get("shot", ""),
        "attempt": attempt,
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
        "request_id": request_id,
        "error_detail": error_detail[:500],
        "engine": fingerprint.code_stamp(),
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
