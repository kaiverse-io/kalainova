"""CLI for what stays the same: kits, streams, canon, schedules, and requests.

kalainova kit new|add|set|freeze|bump|show <kit> ...
kalainova stream new|show|canon <stream> ...
kalainova look <kit> [--stills --cost-cap N --image PROVIDER:MODEL]  a sheet to choose a look from
kalainova schedule <stream> <date> "<brief>" [--cast a,b]
kalainova request <stream> "<brief>" [--cast a,b] [--slot DATE] [--amplify NOTE]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import consistency, kits, lookdev, streams
from .jobfs import ContractError, home


def add_parsers(sub: Any) -> None:
    kit = sub.add_parser("kit").add_subparsers(dest="action", required=True)
    new = kit.add_parser("new")
    new.add_argument("kit")
    new.add_argument("--label", default="")
    add = kit.add_parser("add")
    add.add_argument("kit")
    add.add_argument("slot", help="identity, style, looks.<name>, music.theme, voice.sample, ...")
    add.add_argument("file")
    add.add_argument("--label", default="")
    setter = kit.add_parser("set")
    setter.add_argument("kit")
    setter.add_argument("file", help="a JSON file of fields to merge into the draft")
    freeze = kit.add_parser("freeze")
    freeze.add_argument("kit")
    freeze.add_argument("--by", required=True, help="the human attesting to this kit")
    kit.add_parser("bump").add_argument("kit")
    show = kit.add_parser("show")
    show.add_argument("kit")
    show.add_argument("--version", type=int)

    stream = sub.add_parser("stream").add_subparsers(dest="action", required=True)
    make = stream.add_parser("new")
    make.add_argument("stream")
    make.add_argument("--identity", required=True)
    make.add_argument("--strategy", default="generated")
    make.add_argument("--rights", default="owned")
    make.add_argument("--media", default="video,audio,text")
    make.add_argument("--kit", action="append", default=[], metavar="ROLE=KIT@VERSION")
    make.add_argument("--image", metavar="PROVIDER:MODEL")
    make.add_argument("--video", metavar="PROVIDER:MODEL")
    make.add_argument("--account", action="append", default=[], metavar="PLATFORM=HANDLE")
    make.add_argument("--max-per-day", type=int, default=1)
    make.add_argument("--cost-cap", type=float, required=True)
    make.add_argument("--skip-funded", action="store_true")
    stream.add_parser("show").add_argument("stream")
    canon = stream.add_parser("canon")
    canon.add_argument("stream")
    canon.add_argument("fact")
    canon.add_argument("--by", required=True)

    look = sub.add_parser("look", help="a sheet of a kit's candidate references; changes no kit")
    look.add_argument("kit")
    look.add_argument(
        "--stills", action="store_true", help="also make one test still per look (paid)"
    )
    look.add_argument(
        "--image", metavar="PROVIDER:MODEL", help="with --stills: a model that takes references"
    )
    look.add_argument(
        "--cost-cap", type=float, help="with --stills: the most the test stills may cost"
    )

    slot = sub.add_parser("schedule")
    slot.add_argument("stream")
    slot.add_argument("date")
    slot.add_argument("brief")
    slot.add_argument("--cast", default="")

    req = sub.add_parser("request")
    req.add_argument("stream")
    req.add_argument("brief", nargs="?", default="")
    req.add_argument("--cast", default="")
    req.add_argument("--slot")
    req.add_argument("--amplify", default="")
    req.add_argument("--duration", type=int)


def _pairs(items: list[str], what: str) -> dict[str, str]:
    out = {}
    for item in items:
        key, sep, value = item.partition("=")
        if not sep or not key or not value:
            raise ContractError(f"{what} must look like NAME=VALUE, not {item!r}")
        out[key] = value
    return out


def _pin(text: str | None) -> dict[str, str] | None:
    if not text:
        return None
    provider, sep, model = text.partition(":")
    if not sep:
        raise ContractError(f"generator must look like PROVIDER:MODEL, not {text!r}")
    return {"provider": provider, "model": model}


def _names(text: str) -> list[str] | None:
    return [x for x in text.split(",") if x] or None


def _kit(a: argparse.Namespace, root: Path) -> int:
    if a.action == "new":
        print(kits.new(root, a.kit, label=a.label))
    elif a.action == "add":
        kits.add_file(root, a.kit, a.slot, Path(a.file), label=a.label)
        print(f"added to {a.kit} draft: {a.slot}")
    elif a.action == "set":
        kits.merge(root, a.kit, json.loads(Path(a.file).read_text()))
        print(f"merged into {a.kit} draft")
    elif a.action == "freeze":
        print(f"{a.kit}@{kits.freeze(root, a.kit, by=a.by)['version']}")
    elif a.action == "bump":
        print(kits.bump(root, a.kit))
    else:
        known = kits.versions(root, a.kit)
        if a.version is None and not known:
            print(json.dumps(kits.read_draft(root, a.kit), indent=2, ensure_ascii=False))
        else:
            kit = kits.load(root, a.kit, a.version or known[-1])
            print(json.dumps(kit, indent=2, ensure_ascii=False))
    return 0


def _new_stream(a: argparse.Namespace, root: Path) -> None:
    data: dict[str, Any] = {
        "schema_version": "0.1",
        "stream_id": a.stream,
        "strategy": a.strategy,
        "distribution_identity": a.identity,
        "rights": a.rights,
        "media": a.media.split(","),
        "max_per_day": a.max_per_day,
        "cost_cap_per_job": a.cost_cap,
        "kits": _pairs(a.kit, "--kit"),
        "accounts": _pairs(a.account, "--account"),
    }
    pins = {k: v for k, v in (("image", _pin(a.image)), ("video", _pin(a.video))) if v}
    if pins:
        data["generators"] = pins
    if a.skip_funded:
        data["skip_funded"] = True
    resolved = consistency.resolve(root, data)
    consistency.preflight(resolved, data, list(resolved.characters))
    print(streams.create(root, data))


def _stream(a: argparse.Namespace, root: Path) -> int:
    if a.action == "new":
        _new_stream(a, root)
    elif a.action == "show":
        print(streams.show(root, a.stream))
    else:
        print(json.dumps(streams.canon_add(root, a.stream, a.fact, by=a.by), ensure_ascii=False))
    return 0


def _look(a: argparse.Namespace, root: Path) -> int:
    made: list[tuple[str, Path]] = []
    if a.stills:
        pin = _pin(a.image)
        if not pin or a.cost_cap is None:
            raise ContractError("--stills spends money: give --image PROVIDER:MODEL and --cost-cap")
        made = lookdev.make_test_stills(
            root, a.kit, cost_cap=a.cost_cap, provider=pin["provider"], model=pin["model"]
        )
    print(lookdev.sheet(root, a.kit, lookdev.out_dir(a.kit) / "look-sheet.jpg", stills=made))
    print(f"a person picks from it; `kalainova kit freeze {a.kit} --by NAME` stays a person's")
    return 0


def dispatch(a: argparse.Namespace) -> int | None:
    """Run a command from this module, or None if it belongs to another."""
    root = home()
    if a.cmd == "kit":
        return _kit(a, root)
    if a.cmd == "stream":
        return _stream(a, root)
    if a.cmd == "look":
        return _look(a, root)
    if a.cmd == "schedule":
        print(streams.schedule_add(root, a.stream, a.date, a.brief, cast=_names(a.cast)))
        return 0
    if a.cmd == "request":
        job = streams.request(
            root,
            a.stream,
            a.brief,
            cast=_names(a.cast),
            slot=a.slot,
            amplify=a.amplify,
            duration=a.duration,
        )
        print(job.folder)
        print(f"next: kalainova make {job.folder}")
        return 0
    return None
