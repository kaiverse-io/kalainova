"""Job lifecycle commands: new, make, stage, clean, status, review, comic, story, bar, host.

Also covers: providers, intake, approve, publish, and measure.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import (
    assets,
    edit,
    genres,
    plan,
    qa,
    qachecks,
    render,
    resources,
    trace,
)
from .jobfs import ContractError, home
from .jobfs import open_job as _real_open_job


def open_job(ref: str | Path) -> Any:
    cli = sys.modules.get("kalainova.__main__")
    if cli is not None and getattr(cli, "open_job", None) is not None:
        target = cli.open_job
        if target is not open_job and callable(target):
            return target(ref)
    return _real_open_job(ref)


def _new(a: argparse.Namespace) -> int:
    from . import fingerprint

    dst = home() / "jobs" / a.id
    if dst.exists():
        print(f"{dst} exists", file=sys.stderr)
        return 1
    shutil.copytree(resources.path("jobs", "_template"), dst)
    (dst / "README.md").unlink(missing_ok=True)
    data = json.loads((dst / "job.json").read_text())
    data.update(
        {
            "job_id": a.id,
            "strategy": a.strategy,
            "status": "draft",
            "distribution_identity": a.identity,
            "media": a.media.split(","),
            "rights": a.rights,
            "cost_cap": a.cost_cap,
            "brief": {
                "subject": a.subject,
                "audience": a.audience or "",
                "outcome": a.outcome or "",
                "duration_sec": a.duration,
            },
            "fingerprint": fingerprint.fingerprint(),
        }
    )
    if a.genre:
        genres.apply(data["brief"], a.genre)
    (dst / "job.json").write_text(json.dumps(data, indent=2) + "\n")
    print(dst)
    return 0


STAGES = {
    "plan": lambda j, f: plan.run(j, force=f),
    "assets": lambda j, f: assets.run(j, force=f),
    "edit": lambda j, f: edit.run(j, force=f),
    "compile": lambda j, f: render.compile_plan(j),
    "render": lambda j, f: render.execute(j, cache=not f),
    "qa": lambda j, f: qa.run(j),
}


def _make(a: argparse.Namespace) -> int:
    job = open_job(a.job)
    order = ["plan", "assets", "edit", "compile", "render", "qa"]
    for st in order[order.index(a.from_stage) :]:
        trace.relabel(stage=st)
        t0 = time.time()
        STAGES[st](job, a.force)  # type: ignore[no-untyped-call]  # untyped stages module
        print(f"  {st:<8} ok  {time.time() - t0:5.1f}s")
        if st == "render":
            job.set_status("rendered")
    report = job.read("qa")
    for c in report["checks"]:
        if c["status"] != "pass":
            print(f"  [{c['status']}] {c['id']}: {c['detail']}")
    print(f"{qachecks.headline(report)}  ->  {job.artifact()}")
    _print_bar(report)
    print(f"spent {job.spent():.4f} of cap {job.job.get('cost_cap')}")
    print(f'record verdict: kalainova verdict {job.id} accept|fix|reject --reviewer NAME --note ""')
    return 0 if report["passed"] else 2


def _clean(a: argparse.Namespace) -> int:
    """Free the picture chain's lossless intermediates. Rendering again makes them again."""
    from .render import cache as render_cache

    job = open_job(a.job)
    if not job.has("render_plan"):
        print(f"{job.id}: not rendered, nothing to clean")
        return 0
    files, freed = render_cache.clean(job.work, job.read("render_plan"), dry_run=a.dry_run)
    action = "would free" if a.dry_run else "freed"
    print(f"{job.id}: {len(files)} files, {action} {freed / 1e9:.2f} GB")
    if files and not a.dry_run:
        print(
            "  the final, its records, every asset and take stay; "
            "`make <job> --from render` remakes these"
        )
    return 0


def _print_bar(report: dict[str, Any]) -> None:
    if report.get("bar"):
        from . import bar

        print(f"studio bar: {bar.summary_line(report['bar'])}")


def _document(a: argparse.Namespace) -> int:
    from . import comic, story, writers

    job = open_job(a.job)
    writers.ensure(job, a.cmd)
    final = (comic if a.cmd == "comic" else story).run(job)
    report = qa.run(job)
    for c in report["checks"]:
        if c["status"] != "pass":
            print(f"  [{c['status']}] {c['id']}: {c['detail']}")
    print(f"{qachecks.headline(report)}  ->  {final}")
    return 0 if report["passed"] else 2


def _bar(a: argparse.Namespace) -> int:
    """The studio bar for any file or job, so any piece can be held to the same numbers."""
    from . import bar, media

    target = Path(a.target)
    if target.is_file():
        try:
            report = bar.measure(target)
        except media.MediaError as exc:
            raise ContractError(f"the studio bar cannot read it: {exc}") from exc
    else:
        job = open_job(a.target)
        report = bar.measure_job(job.work, job.read("edit_manifest"), job.read("asset_manifest"))
    for r in report["readings"]:
        mark = "ok  " if r["ok"] else "MISS"
        print(f"{mark} {r['id']:<30} {str(r['value'])[:26]:<28} {r['limit']}")
    print(f"studio bar: {bar.summary_line(report)}")
    kit = getattr(a, "kit", None)
    if kit:
        print(_identity_line(target, kit))
    return 0 if report["passed"] else 2


def _identity_line(picture: Path, kit: str) -> str:
    """A picture face by face, or a video frame by frame, against a frozen kit's faces."""
    from . import kits
    from .bar import identity

    kit_id, _, ver = kit.partition("@")
    version = int(ver) if ver else max(kits.versions(home(), kit_id), default=0)
    refs = [
        kits.blob_path(home(), e) for e in kits.load(home(), kit_id, version)["identity"]["refs"]
    ]
    return identity.kit_line(picture, refs, f"{kit_id}@{version}")


def _cmd_review(a: argparse.Namespace) -> int:
    from . import reviewpage

    print(reviewpage.cli(a.jobs, a.blind, a.rank, a.reviewer, judge=a.judge, shot=a.shot))
    return 0


def _cmd_stage(a: argparse.Namespace) -> int:
    out = STAGES[a.stage](open_job(a.job), a.force)  # type: ignore[no-untyped-call]  # untyped stages module
    print(out if not isinstance(out, dict) else "ok")
    return 0


def _cmd_intake(a: argparse.Namespace) -> int:
    from . import intake

    job = open_job(a.job)
    print(intake.run(job, Path(a.file), json.loads(Path(a.record).read_text())))
    return 0


def _cmd_approve(a: argparse.Namespace) -> int:
    from . import publish as pub

    r = pub.approve(
        open_job(a.job),
        a.reviewer,
        platforms=a.platforms.split(","),
        notes=a.notes,
        privacy=a.privacy,
    )
    print(json.dumps(r, indent=2))
    return 0


def _cmd_publish(a: argparse.Namespace) -> int:
    from . import publish as pub

    print(
        json.dumps(
            pub.publish(open_job(a.job), a.platform, dry_run=not a.live, publish_at=a.at),
            indent=2,
        )
    )
    return 0


def _cmd_measure(a: argparse.Namespace) -> int:
    from . import publish as pub

    print(json.dumps(pub.measure(open_job(a.job), force=a.force), indent=2))
    return 0


def _cmd_status(a: argparse.Namespace) -> int:
    job = open_job(a.job)
    from . import preproduction
    from .jobfs import CONTRACT_FILES

    gate = preproduction.waiting_gate(job)
    line = f"{job.id}: status={job.job['status']} spent={job.spent():.4f}"
    if gate:
        line += f" gate={gate}"
    print(line)
    if gate:
        print(f"  waiting at gate: {gate}")
    for k, v in CONTRACT_FILES.items():
        print(f"  {'x' if job.has(k) else ' '} {v}")
    return 0


def _cmd_host(a: argparse.Namespace) -> int:
    from . import host

    return host.cli()


def _cmd_providers(a: argparse.Namespace) -> int:
    from .providers import base, check

    if a.check:
        return check.cli(a.check, a.job, a.capability, a.spend)

    for name in base.names():
        pr = base.get(name)
        status = "ready" if pr.available() else "needs " + ", ".join(pr.missing_env())
        caps = ", ".join(pr.capabilities)
        print(f"{name:<11} {status:<26} {caps}")
    return 0


_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "new": _new,
    "make": _make,
    "bar": _bar,
    "clean": _clean,
    "review": _cmd_review,
    "comic": _document,
    "story": _document,
    "stage": _cmd_stage,
    "intake": _cmd_intake,
    "approve": _cmd_approve,
    "publish": _cmd_publish,
    "measure": _cmd_measure,
    "status": _cmd_status,
    "host": _cmd_host,
    "providers": _cmd_providers,
}


def add_parsers(sub: Any) -> None:
    n = sub.add_parser("new")
    n.add_argument("id")
    n.add_argument("--strategy", default="generated")
    n.add_argument("--identity", required=True)
    n.add_argument("--subject", required=True)
    n.add_argument("--audience")
    n.add_argument("--outcome")
    n.add_argument("--media", default="video,audio,text")
    n.add_argument("--rights", default="owned")
    n.add_argument("--duration", type=int, default=35)
    n.add_argument("--cost-cap", type=float, default=5.0)
    n.add_argument("--genre", help="a song's genre profile, from genres in the studio config")

    m = sub.add_parser("make")
    m.add_argument("job")
    m.add_argument("--force", action="store_true")
    m.add_argument("--from", dest="from_stage", default="plan", choices=list(STAGES))

    s = sub.add_parser("stage")
    s.add_argument("job")
    s.add_argument("stage", choices=list(STAGES))
    s.add_argument("--force", action="store_true")

    ap = sub.add_parser("approve")
    ap.add_argument("job")
    ap.add_argument("--reviewer", required=True)
    ap.add_argument("--platforms", required=True)
    ap.add_argument("--notes", default="")
    ap.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])

    pb = sub.add_parser("publish")
    pb.add_argument("job")
    pb.add_argument("platform")
    pb.add_argument("--live", action="store_true")
    pb.add_argument("--at", default=None, help="UTC time to go public; platforms that can hold it")

    ms = sub.add_parser("measure")
    ms.add_argument("job")
    ms.add_argument(
        "--force", action="store_true", help="snapshot before 48h; does not set views_48h"
    )

    sub.add_parser("status").add_argument("job")

    cl = sub.add_parser("clean", help="delete rebuildable render intermediates")
    cl.add_argument("job")
    cl.add_argument("--dry-run", action="store_true")

    rv = sub.add_parser("review", help="a page of every take; --blind hears song jobs blind")
    rv.add_argument("jobs", nargs="+")
    rv.add_argument("--blind", action="store_true")
    rv.add_argument("--rank", help="a blind set's letters, best first, such as C,A,B; tie with =")
    rv.add_argument("--reviewer", default="")
    rv.add_argument("--judge", action="store_true", help="score song takes with config's judges")
    rv.add_argument("--shot", default="song", help="with --blind: song, or master for its options")

    sub.add_parser("comic", help="lay out and letter a comic from comic_script.json").add_argument(
        "job"
    )
    sub.add_parser("story", help="typeset a book and an EPUB from story.json").add_argument("job")

    bar_cmd = sub.add_parser("bar", help="hold a job or any file to the studio bar")
    bar_cmd.add_argument("target")
    bar_cmd.add_argument("--kit", help="KIT or KIT@VERSION: compare the faces in a picture with it")

    sub.add_parser("host", help="check host system support and prerequisite capabilities")

    pv = sub.add_parser("providers", help="what is ready; --check makes one real, paid call each")
    pv.add_argument("--check", metavar="PROVIDER", help="prove an adapter against the live service")
    pv.add_argument(
        "--job", help="with --check: a job with a cost_cap, so the ledger holds the spend"
    )
    pv.add_argument("--capability", help="with --check: one capability only")
    pv.add_argument("--spend", action="store_true", help="with --check: yes, make the paid calls")

    it = sub.add_parser("intake")
    it.add_argument("job")
    it.add_argument("file")
    it.add_argument("--record", required=True)


def dispatch(a: argparse.Namespace) -> int | None:
    handler = _HANDLERS.get(a.cmd)
    return handler(a) if handler is not None else None
