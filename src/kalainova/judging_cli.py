"""CLI for testing models on a shot and for holding the engine's judgement to a person's.

kalainova bench <job> <shot> --models a,b [--takes N] [--again]  one shot on several models
kalainova bench-report <job> <shot> [--only 5,7,10] [--again]  the labelled side by side, the
                                                 table, and the engine's pick, at no cost
kalainova verdict <job> accept|fix|reject --reviewer NAME [--shot ID [--take N]|--animatic]
                  [--preferred N --over M | --best N --among a,b,c] [--aspect lips]
kalainova signals                                which readings predict a person's verdict
kalainova agreement                              which readings, and the engine's picks, follow
                                                 a person's preferences, aspect by aspect
kalainova review-set                             every verdict beside its readings
kalainova judges                                 which judges are ready on this machine, and why
                                                 the others are not
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from typing import Any

from . import benchreport, verdicts
from .bar import judges
from .jobfs import ContractError, Job, home, open_job


def add_parsers(sub: Any) -> None:
    bench = sub.add_parser("bench")
    report = sub.add_parser("bench-report")
    for p in (bench, report):
        p.add_argument("job")
        p.add_argument("shot")
        p.add_argument(
            "--again",
            action="store_true",
            help="bench: a row already made; bench-report: judge every take afresh",
        )
    bench.add_argument("--models", required=True)
    bench.add_argument("--takes", type=int, default=1)
    report.add_argument("--only", help="the takes to show, in this order: 5,7,10")
    verdict = sub.add_parser("verdict")
    verdict.add_argument("job")
    verdict.add_argument("verdict", choices=verdicts.CHOICES)
    verdict.add_argument("--reviewer", required=True)
    verdict.add_argument("--shot")
    verdict.add_argument("--take", type=int)
    verdict.add_argument("--preferred", type=int)
    verdict.add_argument("--over", type=int)
    verdict.add_argument("--best", type=int, help="the best of --among, preferred over each other")
    verdict.add_argument("--among", help="the takes --best was chosen from: 0,4,5,7")
    verdict.add_argument("--aspect", default="", help="what the preference is about: lips, eyes...")
    verdict.add_argument("--animatic", action="store_true")
    verdict.add_argument("--note", default="")
    sub.add_parser("signals")
    sub.add_parser("agreement")
    sub.add_parser("review-set")
    sub.add_parser("judges")


def _numbers(text: str | None) -> list[int] | None:
    if not text:
        return None
    try:
        return [int(n) for n in text.split(",") if n.strip()]
    except ValueError as exc:
        raise ContractError(f"take numbers are written 5,7,10, not {text!r}") from exc


def _bench(a: argparse.Namespace) -> int:
    from . import bench

    job = open_job(a.job)
    found = bench.run(job, a.shot, bench.parse_models(a.models), a.takes, again=a.again)
    print(found["sheet"] or "no take was made")
    report = found.get("report")
    if report:
        print(job.work / "bench" / f"{a.shot}.report.md")
    return 0 if found["takes"] and not found["failed"] else 1


def _bench_report(a: argparse.Namespace) -> int:
    job = open_job(a.job)
    report = benchreport.write(job, a.shot, _numbers(a.only), again=a.again)
    print(f"watch them: {report['video']}")
    print(job.work / "bench" / f"{a.shot}.report.md")
    print(f"{report['status']}: {report['reason']}")
    return 0


def _verdict(a: argparse.Namespace) -> int:
    job = open_job(a.job)
    kw = {"reviewer": a.reviewer, "shot": a.shot, "note": a.note, "aspect": a.aspect}
    if a.best is not None:
        among = _numbers(a.among)
        if not among or a.preferred is not None:
            raise ContractError("--best names one of --among, and is not used with --preferred")
        entries = verdicts.best_of(job, a.best, among, **kw)
    else:
        entries = [
            verdicts.record(
                job,
                a.verdict,
                take=a.take,
                preferred=a.preferred,
                over=a.over,
                animatic=a.animatic,
                **kw,
            )
        ]
    for entry in entries:
        print(json.dumps(entry, ensure_ascii=False))
    return 0


def _signals(a: argparse.Namespace) -> int:
    rows = verdicts.signals(home() / "jobs")
    for row in rows:
        print(
            f"{row['signal']:<32} good {row['good']:>2}  bad {row['bad']:>2}  "
            f"{row['separation']:>5}  {row['reads']}"
        )
    print(f"{len(rows)} readings" if rows else "no verdicts yet, so nothing can be said")
    return 0


def engine_agreement(root: Any) -> dict[str, list[int]]:
    """For each aspect: of a person's preferences between two bench takes, how many the engine's
    ranking put the same way round, and how many it ranked at all."""
    tally: dict[str, list[int]] = {}
    places: dict[tuple[str, str], dict[int, int]] = {}
    for row in verdicts.preferences(root):
        key = (row["job"], row["shot"])
        if key not in places:
            job = Job(root / row["job"])
            line = benchreport.line_of(job, row["shot"])
            ranking, close = benchreport.rules("sing" if line else "video")
            found = benchreport.rank(benchreport.benched(job, row["shot"]), ranking, close)
            places[key] = {r["n"]: i for i, r in enumerate(found["order"])}
        seen = places[key]
        won, lost = row["won"]["n"], row["lost"]["n"]
        if won in seen and lost in seen:
            counts = tally.setdefault(row["aspect"], [0, 0])
            counts[0] += seen[won] < seen[lost]
            counts[1] += 1
    return tally


def _agreement(a: argparse.Namespace) -> int:
    root = home() / "jobs"
    rows = verdicts.agreement(root)
    print(f"{'aspect':<10} {'reading':<34} pairs  higher won  says")
    for r in rows:
        print(
            f"{r['aspect']:<10} {r['reading']:<34} {r['pairs']:>5}  "
            f"{r['higher_won']:>10}  {r['says']}"
        )
    for aspect, (same, ranked) in sorted(engine_agreement(root).items()):
        print(
            f"{aspect:<10} {'the engine pick':<34} {ranked:>5}  {same / ranked:>10.3f}  "
            f"{verdicts.NOT_ENOUGH if ranked < verdicts.PAIRS_ENOUGH else ''}"
        )
    if not rows:
        print("no reading differs between preferred takes yet, so nothing can be said of one")
    return 0


def _review_set(a: argparse.Namespace) -> int:
    print(verdicts.review_set(home() / "jobs"))
    return 0


def _judges(a: argparse.Namespace) -> int:
    for line in judges_on_this_machine():
        print(line)
    return 0


def judges_on_this_machine() -> list[str]:
    """One line per judge in the config: ready, or what this machine lacks."""
    lines = []
    for kind in judges.KINDS:
        found = judges.configured(kind)
        if not found:
            lines.append(f"{kind}: none configured")
        for judge in found:
            lacks = judges.missing(judge)
            lines.append(f"{kind} {judge.name}: " + ("ready" if not lacks else "; ".join(lacks)))
    return lines


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "bench": _bench,
    "bench-report": _bench_report,
    "verdict": _verdict,
    "signals": _signals,
    "agreement": _agreement,
    "review-set": _review_set,
    "judges": _judges,
}


def dispatch(a: argparse.Namespace) -> int | None:
    command = COMMANDS.get(a.cmd)
    return command(a) if command else None
