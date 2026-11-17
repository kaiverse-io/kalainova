"""Commands for what must be true before money leaves (ADR 0022).

kalainova stop --by NAME [--why TEXT]           stop every paid call in this studio
kalainova resume --by NAME                      lift the stop
kalainova limits [--daily N --monthly N --by NAME]   the studio's spend limits; a person sets them
kalainova package <job> stills|motion           rehearse, check readiness, write what it pays for
kalainova package <job|*> allowance --capability C --provider P [--model M] --calls N --each USD
                  --why TEXT [--days N]          calls no rehearsal covers, counted and capped
kalainova packages <job>                        each package a job can spend under, and its state
kalainova sign-off <package> --by NAME          a person reads it, answers each risk, signs off

An agent builds packages and never signs them off, and never sets the limits: both need a person at
a terminal. A sign-off asks for a reason for each risk the package holds and for the start of the
package's hash, so it is made by someone who read those exact bytes.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from . import gates, packages
from .jobfs import ContractError, home, open_job
from .providers import balances

CONFIRM_CHARS = 8


def add_parsers(sub: Any) -> None:
    halt = sub.add_parser("stop", help="stop every paid call in this studio until resumed")
    halt.add_argument("--by", required=True)
    halt.add_argument("--why", default="")
    sub.add_parser("resume", help="lift a stop").add_argument("--by", required=True)
    lim = sub.add_parser("limits", help="the studio's daily and monthly spend limits")
    lim.add_argument("--daily", type=float)
    lim.add_argument("--monthly", type=float)
    lim.add_argument("--by", default="")
    pk = sub.add_parser("package", help="what a stage will pay for, for a person to sign")
    pk.add_argument("job", help="a job, or * for an allowance any job in the studio may use")
    pk.add_argument("stage", choices=[*packages.STAGES, "allowance"])
    pk.add_argument("--capability", help="allowance: the capability, such as image or llm")
    pk.add_argument("--provider", help="allowance: the provider")
    pk.add_argument("--model", default="*", help="allowance: the model the router sends it to")
    pk.add_argument("--calls", type=int, default=0, help="allowance: how many calls")
    pk.add_argument("--each", type=float, default=0.0, help="allowance: most dollars a call")
    pk.add_argument("--why", default="", help="allowance: what it is for")
    pk.add_argument("--days", type=float, default=1.0, help="allowance: how long it lasts")
    sub.add_parser("packages", help="each package a job can spend under").add_argument("job")
    so = sub.add_parser("sign-off", help="a person reads a package and signs it off")
    so.add_argument("package")
    so.add_argument("--by", required=True, help="the person signing off")


def _spend(a: argparse.Namespace, root: Path) -> int:
    """The kill switch: stop every paid call in this studio, or lift the stop."""
    if a.cmd == "stop":
        print(f"spend stopped: {gates.stop(root, a.by, a.why)}")
    else:
        gates.resume(root, a.by)
        print("spend resumed; every paid call still needs its own gates")
    return 0


def _at_a_terminal(what: str) -> None:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ContractError(f"{what} is a person's decision: run it at a terminal")


def _limits(a: argparse.Namespace, root: Path) -> int:
    if a.daily is not None or a.monthly is not None:
        if a.daily is None or a.monthly is None:
            raise ContractError("set both --daily and --monthly")
        _at_a_terminal("setting the studio's limits")
        print(f"limits set: {gates.write_limits(root, a.daily, a.monthly, a.by)}")
        return 0
    day, month = gates.spend(root)
    print(f"committed today ${day:.2f}, this month ${month:.2f} (UTC)")
    most = gates.limits(root)
    print(f"limits ${most['daily_usd']:.2f} a day, ${most['monthly_usd']:.2f} a month, "
          f"set by {most['by']} at {most['set_at']}")  # fmt: skip
    return 0


def _package(a: argparse.Namespace, root: Path) -> int:
    if a.stage == "allowance":
        if not (a.capability and a.provider):
            raise ContractError("an allowance names --capability and --provider")
        job_id = a.job if a.job == "*" else open_job(a.job).id
        path = packages.allow(
            root, job_id, capability=a.capability, provider=a.provider, model=a.model,
            calls=a.calls, each=a.each, why=a.why, days=a.days,
        )  # fmt: skip
    else:
        from . import readiness, rehearse  # they reach every stage; only this command needs them

        job = open_job(a.job)
        path = packages.build(job, a.stage, rehearse.run(job), readiness.review)
    for line in packages.lines(path):
        print(line)
    print(path)
    if packages.verdict(packages.load(path)) == "blocked":
        print("blocked: fix each BLOCK, then build the package again")
        return 1
    print(f"a person reads it and signs it off: kalainova sign-off {path} --by NAME")
    return 0


def _sign_off(a: argparse.Namespace, root: Path) -> int:
    """Show the person the package, have them answer each risk, and confirm its hash."""
    path = Path(a.package).resolve()
    _at_a_terminal("signing off a package")
    data = packages.load(path)
    for line in packages.lines(path):
        print(line)
    for provider, most in packages.needs(data).items():
        left = balances.of(provider, fresh=True)
        known = f"${left:.2f}" if left is not None else "not readable"
        print(f"  {provider} balance now: {known}; this package may spend up to ${most:.2f}")
    if packages.verdict(data) == "blocked":
        print("blocked: it cannot be signed off; fix each BLOCK and build it again")
        return 1
    accepted: dict[str, str] = {}
    for f in data.get("readiness") or []:
        reason = input(f"accept {f['id']}? say why, or press enter to stop: ").strip()
        if not reason:
            print("not signed off")
            return 1
        accepted[f["id"]] = reason
    want = packages.digest(path)[:CONFIRM_CHARS]
    typed = input(f"to sign it off, type the first {CONFIRM_CHARS} characters of its sha256: ")
    if typed.strip().lower() != want:
        print("not signed off")
        return 1
    print(f"signed off: {packages.sign_off(path, a.by, accepted)}")
    return 0


def dispatch(a: argparse.Namespace) -> int | None:
    """Run a command from this module, or None if it belongs to another."""
    handler = {"stop": _spend, "resume": _spend, "limits": _limits, "package": _package,
               "sign-off": _sign_off}.get(a.cmd)  # fmt: skip
    if handler is not None:
        return handler(a, home())
    if a.cmd == "packages":
        job_id = a.job if a.job == "*" else open_job(a.job).id
        for line in gates.listing(home(), job_id):
            print(line)
        return 0
    return None
