"""Commands for what must be true before money leaves (ADR 0022).

kalainova stop --by NAME [--why TEXT]           stop every paid call in this studio
kalainova resume --by NAME                      lift the stop
kalainova limits [--daily N --monthly N --by NAME]   the studio's spend limits, or set them unsigned
kalainova package <job> stills|motion           rehearse, and write what that stage pays for
kalainova package <job|*> allowance --capability C --provider P [--model M] --calls N --each USD
                  --why TEXT [--days N]          calls no rehearsal covers, counted and capped
kalainova packages <job>                        each package a job can spend under, and its state
kalainova sign <file> --key PATH                a person reads the file and signs it, at a terminal

An agent prepares limits and packages and never signs them: `sign` needs a terminal and the typed
start of the file's hash, and the key it signs with is the person's, behind their passphrase,
touch or Touch ID.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import gates, packages, signatures
from .jobfs import ContractError, home, open_job

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
    sg = sub.add_parser("sign", help="a person signs a package or the limits, at a terminal")
    sg.add_argument("file")
    sg.add_argument("--key", default=os.environ.get("KALAINOVA_SIGNING_KEY", ""),
                    help="the signing key (a public key, when an agent such as Secretive holds "
                         "it); default $KALAINOVA_SIGNING_KEY")  # fmt: skip


def _spend(a: argparse.Namespace, root: Path) -> int:
    """The kill switch: stop every paid call in this studio, or lift the stop."""
    if a.cmd == "stop":
        print(f"spend stopped: {gates.stop(root, a.by, a.why)}")
    else:
        gates.resume(root, a.by)
        print("spend resumed; every paid call still needs its own gates")
    return 0


def _limits(a: argparse.Namespace, root: Path) -> int:
    if a.daily is not None or a.monthly is not None:
        if a.daily is None or a.monthly is None:
            raise ContractError("set both --daily and --monthly")
        path = gates.write_limits(root, a.daily, a.monthly, a.by)
        print(f"limits written, unsigned: {path}")
        print(f"nothing paid runs on them until a person signs: kalainova sign {path}")
        return 0
    day, month = gates.spend(root)
    print(f"committed today ${day:.2f}, this month ${month:.2f} (UTC)")
    limits, who = gates.signed_limits(root)
    print(f"limits ${limits['daily_usd']:.2f} a day, ${limits['monthly_usd']:.2f} a month, "
          f"signed by {who}")  # fmt: skip
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
        from . import rehearse  # the rehearsal reaches every stage; only this command needs it

        job = open_job(a.job)
        path = packages.build(job, a.stage, rehearse.run(job))
    for line in packages.lines(path):
        print(line)
    print(path)
    print(f"a person reads it and signs it: kalainova sign {path}")
    return 0


def _namespace(path: Path) -> str:
    kind = json.loads(path.read_text()).get("kind")
    if kind == packages.KIND:
        return signatures.PACKAGE
    if kind == gates.LIMITS_KIND:
        return signatures.LIMITS
    raise ContractError(f"{path.name} is neither a package nor the studio's limits")


def _shown(path: Path, namespace: str) -> list[str]:
    if namespace == signatures.PACKAGE:
        return packages.lines(path)
    data = json.loads(path.read_text())
    return [
        f"spend limits for {data['studio']}",
        f"  sha256 {packages.digest(path)}",
        f"  ${data['daily_usd']:.2f} a day, ${data['monthly_usd']:.2f} a month (UTC), "
        f"set by {data['by']} at {data['set_at']}",
    ]


def _sign(a: argparse.Namespace, root: Path) -> int:
    """Show the person exactly what they sign, and have them confirm it at a terminal."""
    path = Path(a.file).resolve()
    if not a.key:
        raise ContractError("name the signing key: --key PATH, or $KALAINOVA_SIGNING_KEY")
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ContractError("signing is a person's act: run kalainova sign at a terminal")
    namespace = _namespace(path)
    for line in _shown(path, namespace):
        print(line)
    want = packages.digest(path)[:CONFIRM_CHARS]
    typed = input(f"to sign this, type the first {CONFIRM_CHARS} characters of its sha256: ")
    if typed.strip().lower() != want:
        print("not signed")
        return 1
    sig = signatures.sign(path, Path(a.key).expanduser(), namespace)
    print(f"signed: {sig}, by {signatures.signer(path, namespace)}")
    return 0


def dispatch(a: argparse.Namespace) -> int | None:
    """Run a command from this module, or None if it belongs to another."""
    handler = {"stop": _spend, "resume": _spend, "limits": _limits, "package": _package,
               "sign": _sign}.get(a.cmd)  # fmt: skip
    if handler is not None:
        return handler(a, home())
    if a.cmd == "packages":
        job_id = a.job if a.job == "*" else open_job(a.job).id
        for line in gates.listing(home(), job_id):
            print(line)
        return 0
    return None
