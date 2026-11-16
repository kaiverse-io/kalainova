"""A dry run of a job's paid stage, so the operator sees every request and its price before a cent.

The job is copied to a throwaway folder that sees the same kits and streams, and its assets stage
runs there with a rehearsal open (providers/rehearsal.py): the stills, then the moving shots. Each
request a rented model would be sent is written down with its fields, which files it would upload,
the router's estimate and the adapter's price. Stand-in files of the asked-for shape let the line go
on. Nothing is sent, nothing is spent, no key is needed, and the real job is not touched except
for the report, written to its work folder as rehearsal.json.

The animatic gate is passed in the copy, because the rehearsal has to reach the video requests.
The report says so: the real run still waits there for a person's verdict.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import assets, preproduction, takes
from .jobfs import ContractError, Job
from .providers import fal, rehearsal

REPORT = "rehearsal.json"
Check = Callable[[str, dict[str, Any]], list[str]]
SKIP = ("jobs", "out")  # the studio's other folders are seen through links, read only


def _copy(job: Job, under: Path) -> Job:
    root = job.folder.parents[1]
    (under / "jobs").mkdir()
    for entry in root.iterdir():
        if entry.name not in SKIP and not entry.name.startswith("."):
            (under / entry.name).symlink_to(entry.resolve())
    folder = under / "jobs" / f"{job.id}-rehearsal"
    shutil.copytree(job.folder, folder, ignore=shutil.ignore_patterns(".lock"))
    data = json.loads((folder / "job.json").read_text())
    data["job_id"] = folder.name
    (folder / "job.json").write_text(json.dumps(data, indent=2) + "\n")
    copy = Job(folder)
    if job.work.is_dir():
        shutil.copytree(job.work, copy.work, dirs_exist_ok=True)
    return copy


def _gate(job: Job) -> str:
    if not preproduction.gate_active(job):
        return "this job has no animatic gate"
    said = (job.job.get("animatic_reviewed") or {}).get("verdict")
    if said == "accept":
        return "the animatic is accepted"
    return "passed in the rehearsal only; the real run makes no video until you accept the animatic"


def _shots(copy: Job) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for shot, entry in takes.load(copy)["shots"].items():
        found[shot] = [
            {
                "n": t["n"],
                "model": t.get("model"),
                "start_frame_sent": (t.get("meta") or {}).get("start_frame_sent"),
                "end_frame_sent": (t.get("meta") or {}).get("end_frame_sent"),
            }
            for t in entry["takes"]
        ]
    return found


def _checked(calls: list[dict[str, Any]], check: Check | None) -> list[str]:
    """Each fal request against the model's live schema, so a field fal would refuse stops the
    rehearsal instead of the paid run. The verdict is kept on the request."""
    found: list[str] = []
    for call in calls:
        for req in call.get("requests", []):
            if check is None or call.get("provider") != "fal":
                continue
            said = check(req["model"], req.get("payload") or {})
            req["schema"] = said or "ok"
            found += [f"request {call['n']}: {s}" for s in said]
    return found


def run(job: Job, check: Check | None = fal.schema_problems) -> dict[str, Any]:
    """Rehearse the job's stills and moving shots; write what would be sent and what it costs.
    `check` reads each model's published schema, which is free and needs no key."""
    stopped = ""
    with tempfile.TemporaryDirectory(prefix="kalainova-rehearsal-") as tmp:
        copy = _copy(job, Path(tmp))
        try:
            with rehearsal.opened() as dry:
                try:
                    assets.run(copy, animatic=True)
                    assets.run(copy, force=copy.has("asset_manifest"))
                except ContractError as exc:
                    stopped = str(exc).replace(copy.id, job.id)
                calls, shots = dry.report(), _shots(copy)
        finally:
            shutil.rmtree(copy.work, ignore_errors=True)
    refused = _checked(calls, check)
    if refused and not stopped:
        stopped = "fal would refuse: " + "; ".join(refused)
    cap = job.job.get("cost_cap")
    total = round(sum(c.get("estimate", 0.0) for c in calls), 6)
    report = {
        "job_id": job.id,
        "calls": calls,
        "shots": shots,
        "estimate_total": total,
        "priced_by_adapter": round(sum(c.get("cost", 0.0) for c in calls), 6),
        "cost_cap": cap,
        "already_committed": round(job.committed(), 6),
        "animatic_gate": _gate(job),
        "stopped": stopped,
    }
    (job.work / REPORT).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    return report


def lines(report: dict[str, Any]) -> list[str]:
    """The report as the operator reads it: one line per paid request, then the sum and the cap."""
    out = []
    for call in report["calls"]:
        for req in call["requests"]:
            fields = ", ".join(sorted(req.get("payload") or {}))
            schema = req.get("schema")
            said = "" if schema is None else "  schema ok" if schema == "ok" else "  SCHEMA REFUSES"
            out.append(
                f"{call['n']:>3} {call['capability']:<6} {req['model']}  "
                f"${call.get('estimate', 0):.3f}  {call.get('note', '')}  fields: {fields}{said}"
            )
    for shot, made in report["shots"].items():
        for take in made:
            out.append(
                f"    {shot} take {take['n']}: start frame "
                f"{'sent' if take['start_frame_sent'] else 'NOT sent'}, end frame "
                f"{'sent' if take['end_frame_sent'] else 'not sent'}"
            )
    cap, done = report["cost_cap"], report["already_committed"]
    left = f", ${float(cap) - done:.2f} left under the ${float(cap):.2f} cap" if cap else ""
    out.append(f"would spend about ${report['estimate_total']:.2f}{left}; nothing was sent")
    out.append(f"animatic gate: {report['animatic_gate']}")
    if report["stopped"]:
        out.append(f"the run would stop: {report['stopped']}")
    return out
