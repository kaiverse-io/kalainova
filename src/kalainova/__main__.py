"""kalainova CLI.

  uv run kalainova new <id> --strategy generated --identity <label> --subject "..."
                            [--media video,audio,text]
  uv run kalainova make <job>          plan -> assets -> edit -> render -> qa
                                       (idempotent; --force redoes)
  uv run kalainova stage <job> <stage>  run one stage: plan|assets|edit|compile|render|qa
  uv run kalainova approve <job> --reviewer <name> --platforms youtube,instagram
  uv run kalainova publish <job> <platform> [--live]
  uv run kalainova measure <job>
  uv run kalainova status <job>
  uv run kalainova clean <job> [--dry-run]   delete what make can rebuild; the final and assets stay
  uv run kalainova rehearse <job>      every paid request and its price, with nothing sent
  uv run kalainova review <job>        a page of every take side by side, to judge by eye
  uv run kalainova bar <job or file>   hold it to the studio bar
  uv run kalainova comic <job>         lay out and letter a comic from comic_script.json
  uv run kalainova story <job>         typeset a book and an EPUB from story.json
  uv run kalainova providers [--check <provider> --job <job> [--capability x] [--spend]]
  uv run kalainova intake <job> <file> --record <record.json>   a finished file from an outside tool

What stays the same (see `kalainova kit --help`, `stream --help`):
  kalainova kit new|add|set|freeze|bump|show <kit> ...
  kalainova stream new|show|canon <stream> ...
  kalainova schedule <stream> <date> "<brief>"
  kalainova request <stream> "<brief>" [--cast a,b]   a locked job for that stream

Before money leaves (signoff_cli.py, ADR 0022):
  kalainova rehearse|limits|package|packages|sign|stop|resume

Shot by shot, songs, research, and what comes after a cut (see production_cli.py):
  kalainova shotplan|takes|take|retake|bench|sheet|filmstrip|cutcheck|export <job> ...
  kalainova song|song-video|research|clips|dub|verdict|signals|provenance|ledger <job> ...

Editing arm (your own footage):
  uv run kalainova ingest <job> <files or folders...>   split into shots, score every shot
  uv run kalainova edit <job> "30s reel, warm, fast cuts, title: ..."   direct -> render -> qa
  uv run kalainova revise <job> "opening slower, drop 03_blurry, cooler"  re-edit from a comment
  uv run kalainova shots <job>                       list shots with scores (ids for notes)

Stock (free-license footage, needs PEXELS_API_KEY and/or PIXABAY_API_KEY and network):
  uv run kalainova stock <job> "Cape Town" [--count 10]          fetch, credit, ingest
  uv run kalainova reel <id> "Cape Town" "20s reel, cinematic, warm, title: Cape Town"
                            new job -> stock -> edit
"""

from __future__ import annotations

import argparse
import sys

from . import editor_cli, job_cli, production_cli, studio_cli, trace
from .job_cli import STAGES, _bar, _clean, _document, _make, _new, open_job  # noqa: F401
from .jobfs import ContractError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kalainova")
    sub = p.add_subparsers(dest="cmd", required=True)
    job_cli.add_parsers(sub)
    editor_cli.add_parsers(sub)
    studio_cli.add_parsers(sub)
    production_cli.add_parsers(sub)
    return p


@trace.scoped
def main(argv: list[str] | None = None) -> int:
    p = build_parser()
    a = p.parse_args(argv)
    trace.relabel(stage=getattr(a, "stage", None) or a.cmd)
    try:
        for handler in (
            studio_cli.dispatch,
            production_cli.dispatch,
            editor_cli.dispatch,
            job_cli.dispatch,
        ):
            handled = handler(a)
            if handled is not None:
                return handled
        return 1
    except ContractError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
