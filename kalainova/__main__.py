"""kalainova CLI.

  python3 -m kalainova new <id> --strategy generated --identity <label> --subject "..." [--media video,audio,text]
  python3 -m kalainova make <job>          plan -> assets -> edit -> render -> qa (idempotent; --force redoes)
  python3 -m kalainova stage <job> <stage>  run one stage: plan|assets|edit|compile|render|qa
  python3 -m kalainova approve <job> --reviewer <name> --platforms youtube,instagram
  python3 -m kalainova publish <job> <platform> [--live]
  python3 -m kalainova measure <job>
  python3 -m kalainova status <job>
  python3 -m kalainova providers

Editing arm (your own footage):
  python3 -m kalainova ingest <job> <files or folders...>   split into shots, score every shot
  python3 -m kalainova edit <job> "30s reel, warm, fast cuts, title: ..."   direct -> render -> qa
  python3 -m kalainova revise <job> "opening slower, drop 03_blurry, cooler"  re-edit from a comment
  python3 -m kalainova shots <job>                       list shots with scores (ids for notes)

Stock (free-license footage, needs PEXELS_API_KEY and/or PIXABAY_API_KEY and network):
  python3 -m kalainova stock <job> "Cape Town" [--count 10]          fetch, credit, ingest
  python3 -m kalainova reel <id> "Cape Town" "20s reel, cinematic, warm, title: Cape Town"   new job -> stock -> edit
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time

from . import assets, edit, plan, qa, render
from .jobfs import REPO, ContractError, open_job


def _new(a) -> int:
    dst = REPO / "jobs" / a.id
    if dst.exists():
        print(f"{dst} exists", file=sys.stderr)
        return 1
    shutil.copytree(REPO / "jobs" / "_template", dst)
    (dst / "README.md").unlink(missing_ok=True)
    data = json.loads((dst / "job.json").read_text())
    data.update({
        "job_id": a.id, "strategy": a.strategy, "status": "draft", "distribution_identity": a.identity,
        "media": a.media.split(","), "rights": a.rights, "cost_cap": a.cost_cap,
        "brief": {"subject": a.subject, "audience": a.audience or "", "outcome": a.outcome or "",
                  "duration_sec": a.duration},
    })
    (dst / "job.json").write_text(json.dumps(data, indent=2) + "\n")
    print(dst)
    return 0


STAGES = {
    "plan": lambda j, f: plan.run(j, force=f),
    "assets": lambda j, f: assets.run(j, force=f),
    "edit": lambda j, f: edit.run(j, force=f),
    "compile": lambda j, f: render.compile_plan(j),
    "render": lambda j, f: render.execute(j),
    "qa": lambda j, f: qa.run(j),
}


def _make(a) -> int:
    job = open_job(a.job)
    order = ["plan", "assets", "edit", "compile", "render", "qa"]
    for st in order[order.index(a.from_stage):]:
        t0 = time.time()
        STAGES[st](job, a.force)
        print(f"  {st:<8} ok  {time.time() - t0:5.1f}s")
        if st == "render":
            job.set_status("rendered")
    report = job.read("qa")
    for c in report["checks"]:
        if c["status"] != "pass":
            print(f"  [{c['status']}] {c['id']}: {c['detail']}")
    print(f"QA {'PASSED' if report['passed'] else 'FAILED'}  ->  {job.work / 'final.mp4'}")
    print(f"spent {job.spent():.4f} of cap {job.job.get('cost_cap')}")
    return 0 if report["passed"] else 2


def _render_edit(job) -> int:
    from .editor import direct
    t0 = time.time()
    info = direct.run(job)
    print(f"  direct   ok  {time.time() - t0:5.1f}s  {info['cuts']} cuts, {info['duration_sec']}s"
          + (f", {info['bpm']} bpm" if info.get("bpm") else ""))
    if info.get("note"):
        print(f"  note     {info['note']}")
    s = info["settings"]
    print(f"  settings {s['format']} · {s['pace']} · grade {s['grade']} · order {s['order']}"
          + (f" · title '{s['title']}'" if s["title"] else "") + (f" · drop {s['drop']}" if s["drop"] else ""))
    for st in ("compile", "render", "qa"):
        t0 = time.time()
        STAGES[st](job, True)
        print(f"  {st:<8} ok  {time.time() - t0:5.1f}s")
        if st == "render":
            job.set_status("rendered")
    report = job.read("qa")
    for c in report["checks"]:
        if c["status"] != "pass":
            print(f"  [{c['status']}] {c['id']}: {c['detail']}")
    print(f"QA {'PASSED' if report['passed'] else 'FAILED'}  ->  {job.work / 'final.mp4'}")
    return 0 if report["passed"] else 2


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kalainova")
    sub = p.add_subparsers(dest="cmd", required=True)
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
    ms = sub.add_parser("measure")
    ms.add_argument("job")
    ms.add_argument("--force", action="store_true", help="snapshot before 48h; does not set views_48h")
    sub.add_parser("status").add_argument("job")
    sub.add_parser("providers")
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
    a = p.parse_args(argv)

    try:
        if a.cmd == "new":
            return _new(a)
        if a.cmd == "make":
            return _make(a)
        if a.cmd == "stage":
            out = STAGES[a.stage](open_job(a.job), a.force)
            print(out if not isinstance(out, dict) else "ok")
            return 0
        if a.cmd == "ingest":
            from pathlib import Path
            from .editor import analyze
            files = []
            for item in a.inputs:
                pth = Path(item)
                files += sorted(x for x in pth.rglob("*") if x.is_file()) if pth.is_dir() else [pth]
            fo = analyze.ingest(open_job(a.job), files)
            print(f"{len(fo['sources'])} sources, {len(fo['shots'])} shots")
            return 0
        if a.cmd in ("edit", "revise"):
            from .editor import direct
            job = open_job(a.job)
            if a.note:
                direct.add_note(job, a.note)
            return _render_edit(job)
        if a.cmd in ("stock", "reel"):
            from .editor import analyze, direct
            from . import stock as stock_mod
            if a.cmd == "reel":
                jdir = REPO / "jobs" / a.id
                if not jdir.exists():
                    jdir.mkdir(parents=True)
                    (jdir / "job.json").write_text(json.dumps({
                        "schema_version": "0.1", "job_id": a.id, "strategy": "owned-derivative", "media": ["video", "audio"],
                        "rights": "licensed", "distribution_identity": a.identity, "status": "draft", "cost_cap": 5,
                        "brief": {"subject": a.subject}}, indent=2) + "\n")
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
        if a.cmd == "shots":
            import json as _j
            job = open_job(a.job)
            fo = _j.loads((job.folder / "footage.json").read_text())
            names = {x["id"]: x["name"] for x in fo["sources"]}
            for sh in sorted(fo["shots"], key=lambda x: -x["quality"]):
                sc = sh["scores"]
                print(f"{sh['id']:<9} q={sh['quality']:.2f}  sharp={sc['sharpness']:.2f} exp={sc['exposure']:.2f} "
                      f"color={sc['colorfulness']:.2f} motion={sc['motion']:.2f} shake={sc['shake']:.2f}  {names[sh['source']]}")
            return 0
        from . import publish as pub
        if a.cmd == "approve":
            r = pub.approve(open_job(a.job), a.reviewer, platforms=a.platforms.split(","), notes=a.notes, privacy=a.privacy)
            print(json.dumps(r, indent=2))
            return 0
        if a.cmd == "publish":
            print(json.dumps(pub.publish(open_job(a.job), a.platform, dry_run=not a.live), indent=2))
            return 0
        if a.cmd == "measure":
            print(json.dumps(pub.measure(open_job(a.job), force=a.force), indent=2))
            return 0
        if a.cmd == "status":
            job = open_job(a.job)
            from .jobfs import CONTRACT_FILES
            print(f"{job.id}: status={job.job['status']} spent={job.spent():.4f}")
            for k, v in CONTRACT_FILES.items():
                print(f"  {'x' if job.has(k) else ' '} {v}")
            return 0
        if a.cmd == "providers":
            from .providers import base
            for name in base.names():
                pr = base.get(name)
                print(f"{name:<11} {'ready' if pr.available() else 'needs ' + str(pr.env_key):<26} {', '.join(pr.capabilities)}")
            return 0
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
