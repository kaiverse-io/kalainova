"""What a person signs before money leaves: the paid calls one stage will make (ADR 0022).

A stage package comes from a rehearsal of the job as it is now (rehearse.py, whose report the
command line hands to `build`): nothing is sent and nothing is spent. It keeps the paid calls of
one stage, `stills` (what the animatic pays for) or `motion` (what the full run pays for once the
stills exist). A call that writes a file is a
*request*. It is named by the router's content key, the provider and the model it goes to, the most
it may cost, and the digest of each vendor payload it sends (providers/payloads.py). A paid call
that writes no file, such as a judge reading a still, is an *allowance*: so many calls of one
capability on one provider and model, each at most so much.

An allowance package is written from the command line for paid work no rehearsal covers (a look
sheet's stills, research, a provider check). It names one job, or every job in the studio (`*`).

A package is canonical JSON. Its bytes are what the person reads (`lines`) and what they sign
(`kalainova sign`). It names its studio, its job, a nonce and when it expires. The router lets a
paid call out only when a valid signature covers it, at or under the signed price, once
(gates.py).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

from .jobfs import ContractError, Job

KIND = "kalainova-package"
VERSION = 1
STAGES = ("stills", "motion")
FOLDER = "packages"
STAGE_LIFETIME = dt.timedelta(hours=24)
MOST_DAYS = 30
SPENT = "spent.jsonl"


def canonical(data: dict[str, Any]) -> bytes:
    """The one byte form of a package: what is read, signed, and checked."""
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, indent=1)
    return (text + "\n").encode()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def folder(root: Path, job_id: str) -> Path:
    """Where a job's packages live; a studio-wide allowance lives in the studio's own folder."""
    return root / FOLDER if job_id == "*" else root / "jobs" / job_id / FOLDER


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _stamp(at: dt.datetime) -> str:
    return at.isoformat(timespec="seconds")


def _request(call: dict[str, Any]) -> dict[str, Any]:
    return {
        "key": call["key"],
        "capability": call["capability"],
        "provider": call["provider"],
        "model": call.get("routed") or "",
        "max_usd": round(float(call.get("estimate") or 0.0), 6),
        "note": call.get("note", ""),
        "asked": call.get("asked") or {},
        "sent": [
            {
                "model": r["model"],
                "digest": r["digest"],
                "payload": r.get("sealed", {}),
                "schema": r.get("schema", "not checked"),
            }
            for r in call.get("requests", [])
        ],
    }


def _allowances(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Paid calls that write no file, counted by capability, provider and model."""
    found: dict[tuple[str, str, str], dict[str, Any]] = {}
    for call in calls:
        at = (call["capability"], call["provider"], call.get("routed") or "")
        entry = found.setdefault(
            at,
            {"capability": at[0], "provider": at[1], "model": at[2], "calls": 0,
             "max_usd_each": 0.0, "why": call.get("note", "")},
        )  # fmt: skip
        entry["calls"] += 1
        entry["max_usd_each"] = max(entry["max_usd_each"], round(float(call["estimate"]), 6))
    return list(found.values())


def _write(data: dict[str, Any], where: Path) -> Path:
    where.mkdir(parents=True, exist_ok=True)
    path = where / f"{data['stage']}-{data['nonce']}.json"
    path.write_bytes(canonical(data))
    return path


def _head(root: Path, job_id: str, stage: str, lifetime: dt.timedelta) -> dict[str, Any]:
    now = _now()
    return {
        "kind": KIND,
        "version": VERSION,
        "studio": str(root.resolve()),
        "job_id": job_id,
        "stage": stage,
        "nonce": secrets.token_hex(8),
        "built_at": _stamp(now),
        "expires_at": _stamp(now + lifetime),
    }


def build(job: Job, stage: str, report: dict[str, Any]) -> Path:
    """The package for one stage, from a rehearsal of the job as it is now. Refuses what cannot be
    signed: a rehearsal that stopped, a call with no price, moving shots keyed by stand-ins."""
    if stage not in STAGES:
        raise ContractError(f"{job.id}: a stage package is for {' or '.join(STAGES)}, not {stage}")
    if report["stopped"]:
        raise ContractError(
            f"{job.id}: the rehearsal stopped, so there is nothing to sign: {report['stopped']}"
        )
    paid = [c for c in report["calls"] if c.get("provider") and c.get("n")]
    if stage == "motion" and any(c.get("phase") == "stills" and c.get("key") for c in paid):
        raise ContractError(
            f"{job.id}: some stills are not made yet, so the moving shots would be keyed by "
            "stand-ins; sign and run the stills package first"
        )
    calls = [c for c in paid if c.get("phase") == stage]
    if not calls:
        raise ContractError(f"{job.id}: the {stage} stage makes no paid call, so needs no package")
    unpriced = [c for c in calls if not c.get("estimate")]
    if unpriced:
        raise ContractError(
            f"{job.id}: {len(unpriced)} paid call(s) have no price, so no ceiling can be signed"
        )
    data = _head(job.studio, job.id, stage, STAGE_LIFETIME)
    data["requests"] = [_request(c) for c in calls if c.get("key")]
    data["allowances"] = _allowances([c for c in calls if not c.get("key")])
    data["total_max_usd"] = round(sum(float(c["estimate"]) for c in calls), 6)
    data["cost_cap"] = job.job.get("cost_cap")
    data["already_committed"] = round(job.committed(), 6)
    if job.has("animatic"):
        data["animatic"] = (job.read("animatic") or {}).get("sha256")
    return _write(data, job.folder / FOLDER)


def allow(
    root: Path,
    job_id: str,
    *,
    capability: str,
    provider: str,
    model: str,
    calls: int,
    each: float,
    why: str,
    days: float = 1.0,
) -> Path:
    """An allowance package: up to `calls` calls of one capability, provider and model, each at
    most `each` dollars, for `days`. `model` is the model the router sends it to; `*` is any."""
    if calls < 1 or each <= 0:
        raise ContractError("an allowance names at least one call and a price above zero")
    if not 0 < days <= MOST_DAYS:
        raise ContractError(f"an allowance lasts at most {MOST_DAYS} days")
    if not why.strip():
        raise ContractError("say what the allowance is for (--why)")
    if job_id != "*" and not (root / "jobs" / job_id / "job.json").is_file():
        raise ContractError(f"no job {job_id} in {root}")
    data = _head(root, job_id, "allowance", dt.timedelta(days=days))
    data["requests"] = []
    data["allowances"] = [
        {"capability": capability, "provider": provider, "model": model, "calls": calls,
         "max_usd_each": round(each, 6), "why": why},
    ]  # fmt: skip
    data["total_max_usd"] = round(calls * each, 6)
    return _write(data, folder(root, job_id))


def load(path: Path) -> dict[str, Any]:
    """A package, refused unless it is one this engine wrote, in its one byte form."""
    raw = path.read_bytes()
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ContractError(f"{path.name} is not a package: {exc}") from exc
    if not isinstance(data, dict) or data.get("kind") != KIND or data.get("version") != VERSION:
        raise ContractError(f"{path.name} is not a version {VERSION} package")
    if canonical(data) != raw:
        raise ContractError(f"{path.name} is not in its canonical form, so it was edited by hand")
    return data


def expired(data: dict[str, Any], now: dt.datetime | None = None) -> bool:
    return dt.datetime.fromisoformat(data["expires_at"]) <= (now or _now())


def lines(path: Path) -> list[str]:
    """The package as the person signing it reads it: every call, its ceiling, the total."""
    data = load(path)
    who = "every job in the studio" if data["job_id"] == "*" else data["job_id"]
    out = [
        f"{data['stage']} package for {who}",
        f"  studio {data['studio']}",
        f"  sha256 {digest(path)}",
        f"  built {data['built_at']}, expires {data['expires_at']}",
    ]
    if data.get("cost_cap") is not None:
        out.append(
            f"  job cap ${float(data['cost_cap']):.2f}, already committed "
            f"${float(data.get('already_committed') or 0):.2f}"
        )
    for i, r in enumerate(data["requests"], 1):
        said = {s["schema"] if isinstance(s["schema"], str) else "REFUSED" for s in r["sent"]}
        out.append(
            f"{i:>3} {r['capability']:<6} {r['provider']} {r['model'] or '(default)'}  up to "
            f"${r['max_usd']:.3f}  {r['note']}  schema {', '.join(sorted(said)) or 'not sent'}"
        )
        for s in r["sent"]:
            fields = ", ".join(sorted(s["payload"]))
            out.append(f"      to {s['model']}: {fields}")
    for a in data["allowances"]:
        model = a["model"] or "(default)"
        out.append(
            f"  up to {a['calls']} x {a['capability']} on {a['provider']} {model}"
            f" at most ${a['max_usd_each']:.3f} each: {a['why']}"
        )
    out.append(f"total at most ${data['total_max_usd']:.2f}")
    return out
