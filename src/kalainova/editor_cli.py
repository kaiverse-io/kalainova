"""Commands for the editing arm: ingest, edit, revise, shots, stock, and reel."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import qachecks, render
from .jobfs import home, open_job


def _render_edit(job: Any) -> int:
    from . import qa
    from .editor import direct

    t0 = time.time()
    info = direct.run(job)
    print(
        f"  direct   ok  {time.time() - t0:5.1f}s  {info['cuts']} cuts, {info['duration_sec']}s"
        + (f", {info['bpm']} bpm" if info.get("bpm") else "")
    )
    if info.get("note"):
        print(f"  note     {info['note']}")
    s = info["settings"]
    print(
        f"  settings {s['format']} · {s['pace']} · grade {s['grade']} · order {s['order']}"
        + (f" · title '{s['title']}'" if s["title"] else "")
        + (f" · drop {s['drop']}" if s["drop"] else "")
    )
    t0 = time.time()
    render.compile_plan(job)
    print(f"  {'compile':<8} ok  {time.time() - t0:5.1f}s")

    t0 = time.time()
    render.execute(job, cache=True)
    print(f"  {'render':<8} ok  {time.time() - t0:5.1f}s")
    job.set_status("rendered")

    t0 = time.time()
    report = qa.run(job)
    print(f"  {'qa':<8} ok  {time.time() - t0:5.1f}s")

    for c in report["checks"]:
        if c["status"] != "pass":
            print(f"  [{c['status']}] {c['id']}: {c['detail']}")
    print(f"{qachecks.headline(report)}  ->  {job.artifact()}")
    if report.get("bar"):
        from . import bar

        print(f"studio bar: {bar.summary_line(report['bar'])}")
    return 0 if report["passed"] else 2


def _cmd_ingest(a: argparse.Namespace) -> int:
    from .editor import analyze

    files = []
    for item in a.inputs:
        pth = Path(item)
        files += sorted(x for x in pth.rglob("*") if x.is_file()) if pth.is_dir() else [pth]
    fo = analyze.ingest(open_job(a.job), files)
    print(f"{len(fo['sources'])} sources, {len(fo['shots'])} shots")
    return 0


def _cmd_edit(a: argparse.Namespace) -> int:
    from .editor import direct

    job = open_job(a.job)
    if a.note:
        direct.add_note(job, a.note)
    return _render_edit(job)


def _cmd_shots(a: argparse.Namespace) -> int:
    job = open_job(a.job)
    fo = json.loads((job.folder / "footage.json").read_text())
    names = {x["id"]: x["name"] for x in fo["sources"]}
    for sh in sorted(fo["shots"], key=lambda x: -x["quality"]):
        sc = sh["scores"]
        q, shp, exp = sh["quality"], sc["sharpness"], sc["exposure"]
        col, mot, shk = sc["colorfulness"], sc["motion"], sc["shake"]
        print(
            f"{sh['id']:<9} q={q:.2f}  sharp={shp:.2f} exp={exp:.2f} "
            f"color={col:.2f} motion={mot:.2f} shake={shk:.2f}  {names[sh['source']]}"
        )
    return 0


def _cmd_stock(a: argparse.Namespace) -> int:
    from . import stock as stock_mod
    from .editor import analyze, direct

    if a.cmd == "reel":
        jdir = home() / "jobs" / a.id
        if not jdir.exists():
            jdir.mkdir(parents=True)
            brief = {"subject": a.subject}
            (jdir / "job.json").write_text(
                json.dumps(
                    {
                        "schema_version": "0.1",
                        "job_id": a.id,
                        "strategy": "owned-derivative",
                        "media": ["video", "audio"],
                        "rights": "licensed",
                        "distribution_identity": a.identity,
                        "status": "draft",
                        "cost_cap": 5,
                        "brief": brief,
                    },
                    indent=2,
                )
                + "\n"
            )
        job = open_job(jdir)
    else:
        job = open_job(a.job)
    paths = stock_mod.fetch(job, a.subject, count=a.count)
    print(f"  stock    {len(paths)} clips  ({stock_mod.credits(job)[:120]}...)")
    fo = analyze.ingest(job, paths)
    print(f"  ingest   {len(fo['shots'])} shots")
    if a.cmd == "stock":
        return 0
    if a.note:
        direct.add_note(job, a.note)
    return _render_edit(job)


_HANDLERS: dict[str, Callable[[argparse.Namespace], int]] = {
    "ingest": _cmd_ingest,
    "edit": _cmd_edit,
    "revise": _cmd_edit,
    "shots": _cmd_shots,
    "stock": _cmd_stock,
    "reel": _cmd_stock,
}


def add_parsers(sub: Any) -> None:
    ig = sub.add_parser("ingest")
    ig.add_argument("job")
    ig.add_argument("inputs", nargs="+")
    for name in ("edit", "revise"):
        e = sub.add_parser(name)
        e.add_argument("job")
        e.add_argument("note", nargs="?", default="")
    sub.add_parser("shots").add_argument("job")
    st = sub.add_parser("stock")
    st.add_argument("job")
    st.add_argument("subject")
    st.add_argument("--count", type=int, default=10)
    rl = sub.add_parser("reel")
    rl.add_argument("id")
    rl.add_argument("subject")
    rl.add_argument("note", nargs="?", default="")
    rl.add_argument("--identity", default="stock-reels")
    rl.add_argument("--count", type=int, default=10)


def dispatch(a: argparse.Namespace) -> int | None:
    handler = _HANDLERS.get(a.cmd)
    return handler(a) if handler is not None else None
