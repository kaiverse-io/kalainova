"""CLI for making and judging a piece shot by shot.

kalainova shotplan <job>                         what is wrong with the plan, before any spend
kalainova takes <job>                            every take of every shot, and how each read
kalainova take <job> <shot> <n>                  a person's choice of take
kalainova retake <job> <shot> ["what was wrong"]  another attempt at one shot
kalainova bench <job> <shot> --models a,b [--takes N]  one shot on several models, side by side
kalainova sheet <job>                            first and last frame of every shot
kalainova filmstrip <file> <start> <end>         frames over a waveform
kalainova cutcheck <job>                         a click or a flash at any cut
kalainova export <job> [--to fcpxml|otio|edl]    the cut for an editing system
kalainova song <job>                             lyrics to takes to a master
kalainova song-video <job> <new id>              a job that cuts a video to the song
kalainova research <job> "question" [--query q]  sources, snapshots, checked findings
kalainova research <job> --check                 hold written findings to their sources
kalainova clips <job> [--count 3] [--open]       short pieces from a long recording
kalainova dub <job> <language> <new id>          the piece in another language
kalainova verdict <job> accept|fix|reject --reviewer NAME [--shot ID [--take N]] [--note TEXT]
kalainova signals                                which readings predict a person's verdict
kalainova provenance <job>                       how it was made, for whoever answers for it
kalainova ledger <job> [--invoice AMOUNT]        estimated against what a vendor billed
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import (
    config,
    nle,
    provenance,
    qa,
    research,
    shotmake,
    shots,
    takes,
    timeline,
    verdicts,
)
from .jobfs import ContractError, Job, home, open_job


def add_parsers(sub: Any) -> None:
    _shot_parsers(sub)
    _look_parsers(sub)
    _make_parsers(sub)
    _record_parsers(sub)


def _shot_parsers(sub: Any) -> None:
    sub.add_parser("shotplan").add_argument("job")
    sub.add_parser("takes").add_argument("job")
    take = sub.add_parser("take")
    take.add_argument("job")
    take.add_argument("shot")
    take.add_argument("n", type=int)
    retake = sub.add_parser("retake")
    retake.add_argument("job")
    retake.add_argument("shot")
    retake.add_argument("note", nargs="?", default="")
    bench = sub.add_parser("bench")
    bench.add_argument("job")
    bench.add_argument("shot")
    bench.add_argument("--models", required=True, help="two or more video models, comma separated")
    bench.add_argument("--takes", type=int, default=1, help="takes of each model (default 1)")


def _look_parsers(sub: Any) -> None:
    sub.add_parser("sheet").add_argument("job")
    strip = sub.add_parser("filmstrip")
    strip.add_argument("file")
    strip.add_argument("start", type=float)
    strip.add_argument("end", type=float)
    strip.add_argument("--frames", type=int, default=8)
    strip.add_argument("--out", default="")
    sub.add_parser("cutcheck").add_argument("job")
    export = sub.add_parser("export")
    export.add_argument("job")
    export.add_argument("--to", default="fcpxml", choices=nle.FORMATS)


def _make_parsers(sub: Any) -> None:
    sub.add_parser("song").add_argument("job")
    video = sub.add_parser("song-video")
    video.add_argument("job")
    video.add_argument("new_id")
    video.add_argument("--profile", default="landscape")
    video.add_argument("--stills", action="store_true")
    found = sub.add_parser("research")
    found.add_argument("job")
    found.add_argument("question", nargs="?", default="")
    found.add_argument("--query", action="append", default=[])
    found.add_argument("--check", action="store_true")
    clips = sub.add_parser("clips")
    clips.add_argument("job")
    clips.add_argument("--count", type=int, default=3)
    clips.add_argument("--open", action="store_true")
    dub = sub.add_parser("dub")
    dub.add_argument("job")
    dub.add_argument("language")
    dub.add_argument("new_id")
    dub.add_argument("--voice")


def _record_parsers(sub: Any) -> None:
    verdict = sub.add_parser("verdict")
    verdict.add_argument("job")
    verdict.add_argument("verdict", choices=verdicts.CHOICES)
    verdict.add_argument("--reviewer", required=True)
    verdict.add_argument("--shot")
    verdict.add_argument("--take", type=int, help="one take of the shot, such as a bench take")
    verdict.add_argument("--note", default="")
    sub.add_parser("signals")
    sub.add_parser("provenance").add_argument("job")
    ledger = sub.add_parser("ledger")
    ledger.add_argument("job")
    ledger.add_argument("--invoice", type=float)


def _shotplan(a: argparse.Namespace) -> int:
    job = open_job(a.job)
    data = job.job
    brief = data.get("brief") or {}
    found = shots.review(
        job.read("script_packet"),
        budget=shots.video_budget(data),
        allow_stills=bool(brief.get("allow_stills")),
        wants_video="video" in data.get("media", []),
        limit=shots.word_limit(config.preference("video", data)),
    )
    for problem in found:
        print(f"[{problem['status']}] {problem['id']}: {problem['detail']}")
    print(f"{len(found)} things to look at" if found else "nothing the plan check can see")
    return 1 if any(p["status"] == "fail" for p in found) else 0


def _takes(a: argparse.Namespace) -> int:
    for shot, entry in takes.load(open_job(a.job))["shots"].items():
        print(f"{shot}: uses take {entry['chosen']}, chosen by {entry['chosen_by']}")
        for take in entry["takes"]:
            mark = "*" if take["n"] == entry["chosen"] else " "
            state = "ok  " if take["ok"] else "MISS"
            readings = {k: v for k, v in (take.get("readings") or {}).items() if k != "readings"}
            print(f" {mark} {take['n']:>2} {state} seed {take['seed']:<11} {readings}")
    return 0


def _bench(a: argparse.Namespace) -> int:
    from . import bench

    job = open_job(a.job)
    found = bench.run(job, a.shot, bench.parse_models(a.models), a.takes)
    print(found["sheet"] or "no take was made")
    for take in found["takes"]:
        print(f"judge it: kalainova verdict {job.id} accept|fix|reject --reviewer NAME "
              f"--shot {a.shot} --take {take['n']}")  # fmt: skip
    return 0 if found["takes"] and not found["failed"] else 1


def _take(a: argparse.Namespace) -> int:
    job = open_job(a.job)
    takes.choose(job, a.shot, a.n)
    if job.has("asset_manifest") and any(
        x["id"] == f"{a.shot}.video" for x in job.read("asset_manifest")["assets"]
    ):
        shotmake.apply_chosen(job, a.shot)
    print(f"{a.shot} uses take {a.n}. Render with: kalainova make {job.id} --from edit")
    return 0


def _retake(a: argparse.Namespace) -> int:
    job = open_job(a.job)
    take = shotmake.retake(job, a.shot, a.note)
    print(f"{a.shot}: take {take['n']} is in use. Render with: kalainova make {job.id} --from edit")
    return 0


def _sheet(a: argparse.Namespace) -> int:
    job = open_job(a.job)
    em = job.read("edit_manifest")
    dst = job.work / "shots.jpg"
    made = timeline.shot_sheet(job.artifact(), em.get("cuts", []), em["duration_sec"], dst)
    print(made or "no picture to read")
    return 0 if made else 1


def _filmstrip(a: argparse.Namespace) -> int:
    source = Path(a.file)
    dst = Path(a.out) if a.out else source.with_suffix(f".{a.start:g}-{a.end:g}.jpg")
    print(timeline.filmstrip(source, a.start, a.end, dst, frames=a.frames))
    return 0


def _cutcheck(a: argparse.Namespace) -> int:
    job = open_job(a.job)
    report = timeline.cut_report(job.artifact(), job.read("edit_manifest").get("cuts", []))
    (job.work / "cutcheck.json").write_text(json.dumps(report, indent=2) + "\n")
    flagged = [c for c in report if c["flagged"]]
    for cut in flagged:
        problem = "flash" if cut["flash"] else f"click {cut['click_ratio']}"
        print(f"{cut['at_sec']:>8.2f}s  {problem}")
    print(f"{len(report)} cuts, {len(flagged)} with a click or a flash")
    return 2 if flagged else 0


def _export(a: argparse.Namespace) -> int:
    print(nle.export(open_job(a.job), a.to))
    return 0


def _print_qa(job: Job, final: Path) -> int:
    report = qa.run(job)
    for check in report["checks"]:
        if check["status"] != "pass":
            print(f"  [{check['status']}] {check['id']}: {check['detail']}")
    print(f"QA {'PASSED' if report['passed'] else 'FAILED'}  ->  {final}")
    return 0 if report["passed"] else 2


def _song(a: argparse.Namespace) -> int:
    from . import songs

    job = open_job(a.job)
    return _print_qa(job, songs.run(job))


def _song_video(a: argparse.Namespace) -> int:
    from . import songs

    folder = songs.video_job(open_job(a.job), a.new_id, profile=a.profile, still_only=a.stills)
    print(f"{folder}\nMake it with: kalainova make {a.new_id} --from assets")
    return 0


def _research(a: argparse.Namespace) -> int:
    job = open_job(a.job)
    if a.check:
        failed = research.verify(job)
        for line in failed:
            print(f"  [fail] {line}")
        print(f"{len(job.read('research')['findings']) - len(failed)} findings check out")
        return 2 if failed else 0
    if not a.question:
        raise ContractError("research needs a question, or --check")
    data = research.run(job, a.question, a.query)
    verified = sum(1 for f in data["findings"] if f.get("verified"))
    print(f"{len(data['sources'])} sources, {verified} checked findings: {job.path('research')}")
    return 0


def _clips(a: argparse.Namespace) -> int:
    from .editor import clips

    job = open_job(a.job)
    footage = json.loads((job.folder / "footage.json").read_text())
    source = job.work / next(s["path"] for s in footage["sources"] if s["kind"] == "video")
    found = clips.find(job, source, count=a.count)
    for n, clip in enumerate(found):
        print(f"{n}: {clip['start_sec']:.1f}-{clip['end_sec']:.1f}s  {clip.get('title', '')}")
    if a.open:
        for n, clip in enumerate(found):
            print(clips.open_job(job, source, clip, f"{job.id}-clip-{n:02d}").folder)
    return 0 if found else 1


def _dub(a: argparse.Namespace) -> int:
    from . import dub

    child = dub.run(open_job(a.job), a.language, a.new_id, voice=a.voice)
    return _print_qa(child, child.artifact())


def _verdict(a: argparse.Namespace) -> int:
    entry = verdicts.record(
        open_job(a.job), a.verdict, reviewer=a.reviewer, shot=a.shot, note=a.note, take=a.take
    )
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


def _provenance(a: argparse.Namespace) -> int:
    print(provenance.write(open_job(a.job)))
    return 0


def _ledger(a: argparse.Namespace) -> int:
    job = open_job(a.job)
    summary = provenance.report(job)["ledger"]
    print(json.dumps(summary, indent=2))
    if a.invoice is None:
        return 0
    gap = round(a.invoice - summary["total_estimated"], 4)
    with open(job.folder / "invoices.jsonl", "a") as fh:
        fh.write(json.dumps({"invoice": a.invoice, "estimated": summary["total_estimated"]}) + "\n")
    print(f"invoice {a.invoice}, estimated {summary['total_estimated']}, gap {gap}")
    return 0


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "shotplan": _shotplan,
    "takes": _takes,
    "bench": _bench,
    "take": _take,
    "retake": _retake,
    "sheet": _sheet,
    "filmstrip": _filmstrip,
    "cutcheck": _cutcheck,
    "export": _export,
    "song": _song,
    "song-video": _song_video,
    "research": _research,
    "clips": _clips,
    "dub": _dub,
    "verdict": _verdict,
    "signals": _signals,
    "provenance": _provenance,
    "ledger": _ledger,
}


def dispatch(a: argparse.Namespace) -> int | None:
    command = COMMANDS.get(a.cmd)
    return command(a) if command else None
