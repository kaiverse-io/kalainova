"""CLI for testing models on a shot and for holding the engine's judgement to a person's.

kalainova bench <job> <shot> --models a,b [--takes N] [--again]  one shot on several models
kalainova bench-report <job> <shot> [--only 5,7,10] [--again]  the labelled side by side, the
                                                 table, and the engine's pick, at no cost
kalainova verdict <job> accept|fix|reject --reviewer NAME [--shot ID [--take N]|--animatic]
                  [--preferred N --over M | --best N --among a,b,c] [--aspect lips]
kalainova song-check <job> [--take N]            a song take against its own plan, as cards
kalainova song-add <job> <audio> --by LABEL      a song made elsewhere, as a take
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
from pathlib import Path
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
    report.add_argument(
        "--reveal", action="store_true", help="show the readings and pick before a verdict"
    )
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
    verdict.add_argument("--reason", default="", choices=("", *verdicts.REASONS),
                         help="what the verdict is about, as one label")  # fmt: skip
    check = sub.add_parser("song-check", help="a song take against its own plan, as cards")
    check.add_argument("job", nargs="?", help="a job; leave out to read a file with --file")
    check.add_argument("--take", type=int, help="the take to read; the chosen one by default")
    check.add_argument("--file", help="a song audio file from anywhere, made by any tool")
    check.add_argument("--song", help="the song file (json) the audio was made from; with --file")
    add = sub.add_parser("song-add", help="a song made elsewhere, as a take read like any other")
    add.add_argument("job")
    add.add_argument("audio")
    add.add_argument("--by", required=True, help="what made it, as one label")
    sub.add_parser("signals")
    sub.add_parser("agreement")
    sub.add_parser("review-set")
    sub.add_parser("judges")


def _print_cards(cards: list[dict[str, Any]]) -> None:
    for card in cards:
        print(f"{card['at']:>5}  {card['section']}: planned {card['planned']}")
        print(f"       measured {card['measured']}\n       fix: {card['fix']}")


def _resolve_song_take(job: Job, take_num: int | None) -> dict[str, Any]:
    from . import takes

    entry = takes.load(job)["shots"].get("song") or {}
    chosen = takes.chosen(job, "song")
    take = (
        next((t for t in entry.get("takes", []) if t["n"] == take_num), None)
        if take_num is not None
        else chosen
    )
    if take is None:
        label = str(take_num) if take_num is not None else "chosen"
        raise ContractError(f"{job.id}: no song take {label}")
    return take


def _build_song_cards(
    job: Job, take: dict[str, Any], path: Path, song: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from . import takes
    from .bar import groove, plan
    from .bar import song as musicbar
    from .editor import beats

    pcm = beats._pcm(path)
    heard = musicbar.saved_heard(path) or []
    chosen = takes.chosen(job, "song")
    own = bool(chosen and take["n"] == chosen["n"])
    cards = plan.energy_cards(plan.profile(pcm, song), song)[1] + plan.key_cards(pcm, song)[1]
    stem = job.work / "vocals.wav"  # the stems are of the chosen take's master
    if own and stem.exists():
        cards += plan.voice_cards(beats._pcm(stem), song)
    cards += plan.pronounce_cards(song, heard) + plan.words_cards(song, heard)
    bed = job.work / "instrumental.wav"  # the groove reads best without the voice
    music = beats._pcm(bed) if (own and bed.exists()) else pcm
    cards += groove.kick_cards(music, song) + groove.build_cards(music, song)
    measured = groove.measures(music, song)
    return cards, measured


def _song_check(a: argparse.Namespace) -> int:
    """Cards for what a song take missed of its own plan: each says what was asked, what was
    measured, where, and the fix. Kept beside the take, and printed; nothing blocks on them."""
    from .bar import plan

    if a.file:
        return _song_check_file(a)
    if not a.job:
        raise ContractError("song-check needs a job, or --file and --song")
    job = open_job(a.job)
    song = job.read("song")
    take = _resolve_song_take(job, a.take)
    path = job.work / take["file"]
    cards, measured = _build_song_cards(job, take, path, song)
    path.with_suffix(".groove.json").write_text(json.dumps(measured, indent=1))
    if not plan.spans(song):
        print(f"{job.id}: the song file names no bars or tempo, so its sections cannot be placed")
    out = path.with_suffix(".cards.json")
    out.write_text(json.dumps(cards, indent=1, ensure_ascii=False))
    _print_cards(cards)
    if measured:
        print(
            f"kick enters at {measured.get('kick_enters_sec')} s; syncopation "
            f"{measured.get('syncopation', 'not read')} (a reading, not a limit)"
        )
    print(f"{job.id} take {take['n']}: {len(cards)} card(s), kept in {out}")
    return 0


def _print_readings_report(report: dict[str, Any]) -> None:
    from .bar import song as musicbar

    for r in report["readings"]:
        print(f"{'ok  ' if r['ok'] else 'MISS'} {r['id']:<30} {r['value']!s:<12} {r['limit']}")
    print(f"{report['met']}/{report['total']} readings met; score {musicbar.score(report)}")


def _file_cards(
    audio: Path, song: dict[str, Any], heard: list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    from .bar import groove, plan
    from .editor import beats

    pcm = beats._pcm(audio)
    cards = plan.energy_cards(plan.profile(pcm, song), song)[1] + plan.key_cards(pcm, song)[1]
    cards += plan.pronounce_cards(song, heard or []) + plan.words_cards(song, heard or [])
    cards += groove.kick_cards(pcm, song) + groove.build_cards(pcm, song)
    return cards


def _song_check_file(a: argparse.Namespace) -> int:
    """The same readings and cards for a song this engine did not make, so any song, from any
    tool, is held to the same plan. Nothing is spent: the words are read by a free local
    transcriber, and nothing is written beside the file."""
    from . import song_outside
    from .bar import song as musicbar

    if not a.song:
        raise ContractError("--file needs --song, the song file the audio was made from")
    audio, song = Path(a.file), json.loads(Path(a.song).read_text())
    if not audio.is_file():
        raise ContractError(f"no such file: {audio}")
    heard = song_outside.free_heard(audio)
    report = musicbar.measure(audio, song, heard)
    _print_readings_report(report)
    cards = _file_cards(audio, song, heard)
    _print_cards(cards)
    print(f"{audio.name}: {len(cards)} card(s)")
    return 0


def _song_add(a: argparse.Namespace) -> int:
    """Take a song made by another tool into a job as a take, so the same readings, judges, review
    page and verdicts apply to it and to the engine's own takes."""
    from . import song_outside

    audio = Path(a.audio)
    if not audio.is_file():
        raise ContractError(f"no such file: {audio}")
    job = open_job(a.job)
    take = song_outside.add_outside_take(job, audio, a.by)
    found = take["readings"]
    print(f"{job.id}: take {take['n']} from {a.by}: score {found['score']}")
    print(f"  missed: {', '.join(found['misses']) or 'nothing'}")
    return 0


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
    report = benchreport.write(job, a.shot, _numbers(a.only), again=a.again, reveal=a.reveal)
    print(f"watch them: {report['video']}")
    print(job.work / "bench" / f"{a.shot}.report.md")
    if report["shown"]:
        print(f"{report['status']}: {report['reason']}")
    else:
        print("the readings and the pick are kept until you give a verdict on these takes")
    return 0


def _verdict(a: argparse.Namespace) -> int:
    job = open_job(a.job)
    kw = {"reviewer": a.reviewer, "shot": a.shot, "note": a.note, "aspect": a.aspect,
          "reason": a.reason}  # fmt: skip
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


def _job_places(root: Any, job_name: str, shot: str) -> dict[int, int]:
    job = Job(root / job_name)
    line = benchreport.line_of(job, shot)
    ranking, close = benchreport.rules("sing" if line else "video")
    found = benchreport.rank(benchreport.benched(job, shot), ranking, close)
    return {r["n"]: i for i, r in enumerate(found["order"])}


def engine_agreement(root: Any) -> dict[str, list[int]]:
    """For each aspect: of a person's preferences between two bench takes, how many the engine's
    ranking put the same way round, and how many it ranked at all."""
    tally: dict[str, list[int]] = {}
    places: dict[tuple[str, str], dict[int, int]] = {}
    for row in verdicts.preferences(root):
        key = (row["job"], row["shot"])
        if key not in places:
            places[key] = _job_places(root, row["job"], row["shot"])
        seen = places[key]
        won, lost = row["won"]["n"], row["lost"]["n"]
        if won in seen and lost in seen:
            counts = tally.setdefault(row["aspect"], [0, 0])
            counts[0] += int(seen[won] < seen[lost])
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


def _judge_line(kind: str, judge: Any) -> str:
    lacks = judges.missing(judge)
    return f"{kind} {judge.name}: " + ("ready" if not lacks else "; ".join(lacks))


def judges_on_this_machine() -> list[str]:
    """One line per judge in the config: ready, or what this machine lacks."""
    lines = []
    for kind in judges.KINDS:
        found = judges.configured(kind)
        if not found:
            lines.append(f"{kind}: none configured")
        for judge in found:
            lines.append(_judge_line(kind, judge))
    return lines


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "bench": _bench,
    "bench-report": _bench_report,
    "verdict": _verdict,
    "signals": _signals,
    "agreement": _agreement,
    "review-set": _review_set,
    "judges": _judges,
    "song-check": _song_check,
    "song-add": _song_add,
}


def dispatch(a: argparse.Namespace) -> int | None:
    command = COMMANDS.get(a.cmd)
    return command(a) if command else None
