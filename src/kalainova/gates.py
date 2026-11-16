"""What must be true before money leaves: the gates every paid call passes (ADR 0022).

The router asks here before it reserves a paid call, and a failed or unreadable gate refuses: it
never falls back to letting the call through. Free providers and rehearsals pass, since they spend
nothing.

Built so far:

- **The kill switch.** While `<studio>/STOP` exists, every paid call refuses. `kalainova stop` and
  `kalainova resume` write and remove it, and both are logged in `<studio>/gates.log.jsonl`.

To come, in this order: studio-wide daily and monthly limits, signed packages (a paid request must
be covered by a person's hardware-backed signature over its exact content), and a spend broker
that alone holds the vendor key.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from .jobfs import ContractError, Job

STOP = "STOP"
LOG = "gates.log.jsonl"


def studio(job: Job) -> Path:
    """The studio a job belongs to: jobs/<id> sits under it, beside kits and streams."""
    return job.folder.parents[1]


def _log(root: Path, event: dict[str, Any]) -> None:
    row = {"at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), **event}
    with open(root / LOG, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def stop(root: Path, by: str, why: str = "") -> Path:
    """Stop every paid call in this studio until someone resumes it."""
    if not by.strip():
        raise ContractError("say who is stopping spend (--by)")
    path = root / STOP
    path.write_text(json.dumps({"by": by, "why": why}) + "\n")
    _log(root, {"event": "stop", "by": by, "why": why})
    return path


def resume(root: Path, by: str) -> None:
    if not by.strip():
        raise ContractError("say who is resuming spend (--by)")
    (root / STOP).unlink(missing_ok=True)
    _log(root, {"event": "resume", "by": by})


def refuse_paid(job: Job, provider: str, capability: str) -> None:
    """Raise unless a paid call may go out now. Called by the router before it reserves."""
    path = studio(job) / STOP
    if path.exists():
        try:
            said = json.loads(path.read_text())
        except ValueError:
            said = {}
        who = f" by {said['by']}" if said.get("by") else ""
        why = f": {said['why']}" if said.get("why") else ""
        raise ContractError(
            f"{job.id}: spend is stopped in this studio{who}{why}; {provider} {capability} was "
            "not called. `kalainova resume --by NAME` lifts it"
        )
