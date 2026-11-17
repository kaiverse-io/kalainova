"""What must be true before money leaves: the gates every paid call passes (ADR 0022).

The router asks here before it reserves a paid call, and a gate that fails or cannot be read
refuses; it never falls back to letting the call through. Free providers and rehearsals pass, since
they spend nothing. In order:

- **The kill switch.** While `<studio>/STOP` exists, every paid call refuses. `kalainova stop` and
  `kalainova resume` write and remove it, and both are logged in `<studio>/gates.log.jsonl`.
- **The studio's limits.** `<studio>/limits.json`, set by a named person at a terminal
  (`kalainova limits`), says what the whole studio may spend in a UTC day and a UTC month. Every
  job's dated ledger lines count, open reservations included. With no limits, nothing paid runs.
- **A signed-off package.** A paid call goes out only when a package a person signed off covers
  it (packages.py): a request by its content key, provider, model and payload digests, or an
  allowance by capability, provider and model. Its estimate must be at or under the ceiling, and
  each request is spent once: `<studio>/packages/spent.jsonl` records it. A call that fails with
  nothing billed gives its entry back; one that may have been billed does not.

`admit` takes all of it and the job's reservation as one step under a studio-wide lock, so parallel
jobs cannot pass the limits together. None of it can be turned off by a brief, a flag or the
environment. It is there to stop mistakes: a call nobody looked at, a vague or wrong input, a
second run of the same request, a loop. It is not a lock against an agent that sets out to get
round it (ADR 0022).
"""

from __future__ import annotations

import datetime as dt
import fcntl
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import packages
from .jobfs import ContractError, Job

STOP = "STOP"
LOG = "gates.log.jsonl"
LIMITS = "limits.json"
LIMITS_KIND = "kalainova-limits"
SPEND_LOCK = ".spend.lock"
EPSILON = 1e-6  # a dollar figure rounded to six places


def studio(job: Job) -> Path:
    """The studio a job belongs to: jobs/<id> sits under it, beside kits and streams."""
    return job.studio


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _log(root: Path, event: dict[str, Any]) -> None:
    row = {"at": _now().isoformat(timespec="seconds"), **event}
    with open(root / LOG, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


# ------------------------------------------------------------------ the kill switch
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


# ------------------------------------------------------------------ the studio's limits
def write_limits(root: Path, daily: float, monthly: float, by: str) -> Path:
    """The studio's daily and monthly limits, set by a named person."""
    if not by.strip():
        raise ContractError("say who is setting the limits (--by)")
    if not 0 < daily <= monthly:
        raise ContractError("a daily limit is above zero and at most the monthly one")
    data = {
        "kind": LIMITS_KIND,
        "version": 1,
        "studio": str(root.resolve()),
        "daily_usd": round(daily, 2),
        "monthly_usd": round(monthly, 2),
        "set_at": _now().isoformat(timespec="seconds"),
        "by": by,
    }
    path = root / LIMITS
    path.write_bytes(packages.canonical(data))
    _log(root, {"event": "limits", "by": by, "daily_usd": daily, "monthly_usd": monthly})
    return path


def limits(root: Path) -> dict[str, Any]:
    """The studio's limits; raises unless a person set them for this studio."""
    path = root / LIMITS
    if not path.is_file():
        raise ContractError(
            f"{root} has no spend limits, so nothing paid runs; a person sets them: "
            "`kalainova limits --daily N --monthly N --by NAME`"
        )
    raw = path.read_bytes()
    data = json.loads(raw)
    if data.get("kind") != LIMITS_KIND or packages.canonical(data) != raw:
        raise ContractError(f"{path} is not a limits file this engine wrote, or was edited by hand")
    if data.get("studio") != str(root.resolve()):
        raise ContractError(f"{path} names another studio ({data.get('studio')})")
    return dict(data)


def spend(root: Path, now: dt.datetime | None = None) -> tuple[float, float]:
    """What the studio has committed today and this month (UTC), across every job's ledger.
    A line with no date predates dated ledgers, and counts in neither."""
    now = now or _now()
    day = month = 0.0
    for ledger in sorted((root / "jobs").glob("*/ledger.json")):
        try:
            entries = json.loads(ledger.read_text())
        except (OSError, ValueError) as exc:
            raise ContractError(f"{ledger} cannot be read, so the limits cannot be held") from exc
        for entry in entries:
            at = entry.get("at")
            if not at:
                continue
            when = dt.datetime.fromisoformat(at)
            cost = float(entry.get("cost") or 0.0)
            if (when.year, when.month) == (now.year, now.month):
                month += cost
                if when.date() == now.date():
                    day += cost
    return round(day, 6), round(month, 6)


def _within_limits(root: Path, job: Job, estimate: float) -> None:
    most_of = limits(root)
    day, month = spend(root)
    for span, held, most in (("today", day, most_of["daily_usd"]),
                             ("this month", month, most_of["monthly_usd"])):  # fmt: skip
        if held + estimate > float(most) + EPSILON:
            raise ContractError(
                f"{job.id}: the studio has committed ${held:.2f} {span} of its ${float(most):.2f} "
                f"limit, and this call is estimated at ${estimate:.2f}; nothing was called"
            )


# ------------------------------------------------------------------ signed-off packages
@dataclass(frozen=True)
class Call:
    """One paid call, as the router asks for it."""

    job: Job
    provider: str
    capability: str
    key: str  # the router's content key; "" for a call that writes no file
    model: str  # the model the router sends it to: the pin, or the provider's default
    estimate: float
    attempt: str


@dataclass(frozen=True)
class Allowed:
    """The signed entry a call is spent against."""

    package: str  # the package's file, from the studio
    entry: str  # "request N" or "allowance N"
    signer: str  # who signed it off
    signed: tuple[str, ...] | None  # the payload digests signed off; None for an allowance


@contextmanager
def _studio_locked(root: Path) -> Iterator[None]:
    """One writer at a time to the studio's spend, across threads and processes."""
    with open(root / SPEND_LOCK, "w") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        yield


def _spent_path(root: Path) -> Path:
    return packages.folder(root, "*") / packages.SPENT


def _rows(root: Path) -> list[dict[str, Any]]:
    path = _spent_path(root)
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _uses(rows: list[dict[str, Any]], package: str, entry: str) -> int:
    returned = {r["returned"] for r in rows if "returned" in r}
    return sum(
        1
        for r in rows
        if r.get("package") == package and r.get("entry") == entry
        and r.get("attempt") not in returned
    )  # fmt: skip


def _append(root: Path, row: dict[str, Any]) -> None:
    path = _spent_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    stamped = {"at": _now().isoformat(timespec="seconds"), **row}
    with open(path, "a") as fh:
        fh.write(json.dumps(stamped, sort_keys=True) + "\n")


def _candidates(root: Path, job: Job) -> Iterator[tuple[Path, dict[str, Any] | None, str]]:
    """Each package this job could spend under, loaded, or None with why it cannot be."""
    for where in (packages.folder(root, job.id), packages.folder(root, "*")):
        for path in _packages_in(where):
            try:
                data = packages.load(path)
            except (ContractError, OSError) as exc:
                yield path, None, str(exc)
                continue
            if data["studio"] != str(root.resolve()):
                yield path, None, f"{path.name} belongs to another studio"
            elif data["job_id"] not in (job.id, "*"):
                yield path, None, f"{path.name} is for job {data['job_id']}"
            elif packages.expired(data):
                yield path, None, f"{path.name} expired at {data['expires_at']}"
            else:
                yield path, data, ""


def _entry(
    data: dict[str, Any], call: Call, rows: list[dict[str, Any]], name: str
) -> tuple[str, tuple[str, ...] | None, str]:
    """The entry of one package that covers the call, or ("", None, why not)."""
    why = ""
    for i, r in enumerate(data["requests"], 1):
        if (r["key"], r["provider"], r["model"]) != (call.key, call.provider, call.model):
            continue
        if call.estimate > r["max_usd"] + EPSILON:
            why = (
                f"{name} signed {r['capability']} at most ${r['max_usd']:.3f}, and it is now "
                f"estimated at ${call.estimate:.3f}"
            )
        elif _uses(rows, name, f"request {i}"):
            why = f"{name} request {i} was spent already"
        else:
            return f"request {i}", tuple(s["digest"] for s in r["sent"]), ""
    for i, a in enumerate(data["allowances"], 1):
        if (a["capability"], a["provider"]) != (call.capability, call.provider):
            continue
        if a["model"] not in ("*", call.model):
            continue
        if call.estimate > a["max_usd_each"] + EPSILON:
            why = f"{name} allows {a['capability']} at most ${a['max_usd_each']:.3f} a call"
        elif _uses(rows, name, f"allowance {i}") >= a["calls"]:
            why = f"{name} allowance {i} is used up ({a['calls']} calls)"
        else:
            return f"allowance {i}", None, ""
    return "", None, why


def _cover(root: Path, call: Call) -> Allowed:
    """The signed-off entry that covers this call, or a refusal that says what is missing."""
    rows = _rows(root)
    reasons: list[str] = []
    found: list[tuple[str, str, tuple[str, ...] | None, Path]] = []
    for path, data, why in _candidates(root, call.job):
        if data is None:
            reasons.append(why)
            continue
        name = str(path.relative_to(root))
        entry, signed, why = _entry(data, call, rows, name)
        if entry:
            found.append((name, entry, signed, path))
        elif why:
            reasons.append(why)
    found.sort(key=lambda f: f[2] is None)  # an exact request before an allowance
    for name, entry, signed, path in found:
        try:
            who = packages.signed_off_by(path, packages.load(path))
        except ContractError as exc:
            reasons.append(str(exc))
            continue
        return Allowed(package=name, entry=entry, signer=who, signed=signed)
    model = f" {call.model}" if call.model else ""
    raise ContractError(
        f"{call.job.id}: no signed-off package covers {call.capability} on {call.provider}{model} "
        f"at ${call.estimate:.3f}{'; ' + '; '.join(reasons) if reasons else ''}. Nothing was "
        "called. Build a package (kalainova package), and a person signs it off"
    )


def admit(call: Call, reserve: Callable[[], str | None]) -> tuple[Allowed, str | None]:
    """Let one paid call out: within the studio's limits, covered by a signed-off package entry not
    yet spent, and its estimate reserved on the job's ledger, all as one step."""
    root = studio(call.job)
    with _studio_locked(root):
        _within_limits(root, call.job, call.estimate)
        allowed = _cover(root, call)
        _append(root, {"package": allowed.package, "entry": allowed.entry, "job": call.job.id,
                       "attempt": call.attempt, "usd": round(call.estimate, 6),
                       "signer": allowed.signer})  # fmt: skip
        try:
            reservation = reserve()
        except BaseException:
            _append(root, {"returned": call.attempt, "why": "not reserved"})
            raise
    return allowed, reservation


def give_back(job: Job, attempt: str, why: str) -> None:
    """A call that failed with nothing billed returns its entry, so the same request may run
    again."""
    root = studio(job)
    with _studio_locked(root):
        _append(root, {"returned": attempt, "why": why})


def package_state(root: Path, path: Path, data: dict[str, Any]) -> str:
    """Where one package stands: its verdict, signed off or not, expired, and how much is used."""
    try:
        state = f"{packages.verdict(data)}, signed off by {packages.signed_off_by(path, data)}"
    except ContractError as exc:
        state = f"NOT USABLE: {exc}"
    if packages.expired(data):
        state += f", expired {data['expires_at']}"
    rows, name = _rows(root), str(path.relative_to(root))
    used = sum(_uses(rows, name, f"request {i}") for i in range(1, len(data["requests"]) + 1))
    allowed = sum(
        _uses(rows, name, f"allowance {i}") for i in range(1, len(data["allowances"]) + 1)
    )
    return f"{state}; {used} of {len(data['requests'])} requests spent, {allowed} allowance calls"


def _packages_in(where: Path) -> list[Path]:
    """The packages in a folder, without their sign-offs."""
    if not where.is_dir():
        return []
    return sorted(p for p in where.glob("*.json") if not p.name.endswith(".signoff.json"))


def listing(root: Path, job_id: str) -> list[str]:
    """Each package a job can spend under, and where it stands."""
    out = []
    for where in (packages.folder(root, job_id), packages.folder(root, "*")):
        for path in _packages_in(where):
            try:
                data = packages.load(path)
            except ContractError as exc:
                out.append(f"{path.name}: {exc}")
                continue
            state = package_state(root, path, data)
            out.append(f"{path.name}: {data['stage']}, up to ${data['total_max_usd']:.2f}, {state}")
    return out or [f"{job_id}: no packages; build one with kalainova package"]
