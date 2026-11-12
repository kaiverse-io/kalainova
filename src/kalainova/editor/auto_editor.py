"""Speech and silence cuts from the `auto-editor` command (WyattBlue/auto-editor), as an adapter
beside the in-house cuts in `speech.py`. The tool is its own program in its own environment; nothing
of it is here.

`auto-editor <file> --export v3 -o <out>` writes its edit as JSON: a timebase and, per track, clips
with `offset` (where in the source), `dur`, and `start` (where on the cut), all in frames. The loud
parts are the clips. This module reads the clips of the first track as the spans to keep.
Its judgement is loudness, not words, so a cut can land inside a quiet word: the margin it keeps
around sound (`margin`, 0.2s by default) is what guards against that.
"""

from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

from .. import config, opentools
from ..jobfs import Job
from ..opentools import BadInputError, BadOutputError, ToolFailedError

COMMAND = "auto-editor"
PROGRAM = "auto-editor"
VERSION_PATTERN = r"(?m)^(\d+\.\d+\.\d+)\s*$"
EXPECTS = "29"
TIMEOUT_SEC = 900
HINT = (
    "Install it in its own environment: uv venv --python 3.12 <dir> && uv pip install --python "
    "<dir>/bin/python auto-editor, then put <dir>/bin on PATH (docs/how-to/install-open-tools.md)"
)
TOLERANCE_SEC = 0.5  # a span may end this far past the probed length, for a rounded last frame


def settings() -> dict[str, Any]:
    chosen = config.adapter("speech_cuts")
    return {
        "command": chosen.get("command") or COMMAND,
        "expects": str(chosen.get("version") or EXPECTS),
        "timeout": float(chosen.get("timeout_sec") or TIMEOUT_SEC),
        "edit": str(chosen.get("edit") or "audio"),
        "margin": str(chosen.get("margin") or "0.2s"),
    }


def parse(text: str, duration: float, name: str) -> list[tuple[float, float]]:
    """The spans to keep, in seconds of the source, from auto-editor's v3 JSON."""
    try:
        doc = json.loads(text)
        base = Fraction(doc["timebase"])
        tracks = doc.get("v") or doc.get("a") or []
        clips = tracks[0] if tracks else []
        spans = []
        for clip in clips:
            if float(clip.get("speed", 1)) != 1:
                raise ValueError("a clip at another speed")
            start = Fraction(int(clip["offset"])) / base
            spans.append(
                (round(float(start), 3), round(float(start + Fraction(int(clip["dur"])) / base), 3))
            )
    except (ValueError, KeyError, TypeError, ZeroDivisionError, IndexError) as exc:
        raise BadOutputError(f"{name}: auto-editor's cut list is unreadable: {exc!r}") from exc
    if not spans:
        raise BadOutputError(f"{name}: auto-editor found no sound to keep")
    ordered = all(a < b for a, b in spans) and all(
        x[1] <= y[0] for x, y in zip(spans, spans[1:], strict=False)
    )
    if not ordered or spans[0][0] < 0 or spans[-1][1] > duration + TOLERANCE_SEC:
        raise BadOutputError(f"{name}: auto-editor's spans are out of order or outside the file")
    return [(a, min(b, round(duration, 3))) for a, b in spans]


def keeps(job: Job, source: Path, duration: float) -> list[tuple[float, float]]:
    """What to keep of `source` (a file in the job's folder), by loudness. Kept by the file's
    bytes and the options, so a source is analysed once."""
    opts = settings()
    if not source.is_file() or source.stat().st_size == 0:
        raise BadInputError(f"{source}: not a media file")
    src = opentools.inside(source, job.work)
    exe = opentools.find(
        opts["command"], capability="speech_cuts", adapter="auto_editor", hint=HINT
    )
    found = opentools.require_version(exe, VERSION_PATTERN, opts["expects"], program=PROGRAM)
    folder = opentools.inside(job.work / "speech_cuts", job.work)
    folder.mkdir(exist_ok=True)
    options = {"edit": opts["edit"], "margin": opts["margin"], "version": found}
    key = hashlib.sha256((opentools.sha256(src) + json.dumps(options, sort_keys=True)).encode())
    out = opentools.inside(folder / f"{key.hexdigest()[:20]}.v3", job.work)
    if out.is_file() and out.stat().st_size:  # the same bytes and options were analysed already
        return parse(out.read_text(), duration, src.name)
    argv = [
        exe, str(src), "--export", "v3", "-o", str(out), "--edit", opts["edit"],
        "--margin", opts["margin"], "--no-open", "--quiet",
    ]  # fmt: skip
    got = opentools.run(argv, timeout=opts["timeout"])
    opentools.record(job, "auto-editor", got, options=options, inputs=[src], outputs=[out])
    if got.returncode != 0:
        raise ToolFailedError(
            f"`{opts['command']}` failed on {src.name}: {got.stderr.strip()[-300:]}"
        )
    if not out.is_file() or out.stat().st_size == 0:
        raise BadOutputError(f"`{opts['command']}` exited 0 but wrote nothing for {src.name}")
    return parse(out.read_text(), duration, src.name)
