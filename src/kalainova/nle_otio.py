"""Timeline files through OpenTimelineIO, as an adapter beside `nle.py`.

`nle.py` writes the cut itself in three formats. This adapter has OpenTimelineIO's own command,
`otioconvert`, write the FCPXML and CMX 3600 from the cut's OTIO file, and read a timeline an
editor saved back into a summary. The tool is its own program in its own environment (each format
is its own package there: `otio-fcpx-xml-adapter`, `otio-cmx3600-adapter`); nothing of it is here.

It reads and writes files inside the job's work folder. Reading an edit back changes no cut and no
approval: the summary is a record, and applying it to the edit is a later step.
"""

from __future__ import annotations

import json
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from . import config, opentools
from .jobfs import Job
from .opentools import BadInputError, BadOutputError, ToolFailedError

COMMAND = "otioconvert"
PROGRAM = "OpenTimelineIO"
VERSION_PATTERN = r"OpenTimelineIO version: (\d+(?:\.\d+)+)"
EXPECTS = "0.18"
TIMEOUT_SEC = 120
HINT = (
    "Install it in its own environment: python3.12 -m venv <dir> && <dir>/bin/pip install "
    "opentimelineio otio-cmx3600-adapter otio-fcpx-xml-adapter, then put <dir>/bin on PATH "
    "(docs/how-to/install-open-tools.md)"
)
# the file each output format is called, and the OTIO adapter that writes or reads it
ADAPTERS = {"fcpxml": "fcpx_xml", "edl": "cmx_3600", "otio": "otio_json"}
SUFFIXES = {".fcpxml": "fcpxml", ".edl": "edl", ".otio": "otio"}


def settings() -> dict[str, Any]:
    chosen = config.adapter("timeline")
    return {
        "command": chosen.get("command") or COMMAND,
        "expects": str(chosen.get("version") or EXPECTS),
        "timeout": float(chosen.get("timeout_sec") or TIMEOUT_SEC),
    }


def available(command: str | None = None) -> bool:
    return shutil.which(command or COMMAND) is not None


def _program(opts: dict[str, Any]) -> str:
    exe = opentools.find(opts["command"], capability="timeline", adapter="otio", hint=HINT)
    opentools.require_version(exe, VERSION_PATTERN, opts["expects"], program=PROGRAM)
    return exe


def _convert(job: Job, src: Path, dst: Path, opts: dict[str, Any], *, reading: bool) -> None:
    """One `otioconvert` call, checked on both sides. Reading takes the input's adapter from its
    suffix; writing names the output's, so a changed default cannot change the format."""
    fmt = SUFFIXES.get(src.suffix.lower() if reading else dst.suffix.lower())
    if fmt is None:
        raise BadInputError(
            f"{(src if reading else dst).name}: not a timeline format ({list(SUFFIXES)})"
        )
    exe = _program(opts)
    flag = ["-I" if reading else "-O", ADAPTERS[fmt]]
    argv = [exe, "-i", str(src), "-o", str(dst), *flag]
    dst.unlink(missing_ok=True)
    got = opentools.run(argv, timeout=opts["timeout"])
    opentools.record(
        job,
        "otioconvert",
        got,
        options={"adapter": ADAPTERS[fmt], "reading": reading, "expects": opts["expects"]},
        inputs=[src],
        outputs=[dst],
    )
    if got.returncode != 0:
        raise ToolFailedError(
            f"`{opts['command']}` failed on {src.name}: {got.stderr.strip()[-300:]}"
        )
    if not dst.is_file() or dst.stat().st_size == 0:
        raise BadOutputError(f"`{opts['command']}` exited 0 but wrote nothing to {dst.name}")


def _check_written(dst: Path, fmt: str) -> None:
    """The output is the kind it should be, before the step counts as done."""
    text = dst.read_text(errors="replace")
    try:
        if fmt == "fcpxml":
            root = ET.fromstring(text)  # noqa: S314 - the file the tool just wrote, in our folder
            if root.tag != "fcpxml" or not root.findall(".//asset-clip"):
                raise ValueError("no fcpxml root or no clips")
        elif fmt == "edl":
            if "TITLE:" not in text or not any(line[:3].isdigit() for line in text.splitlines()):
                raise ValueError("no title or no events")
        else:
            json.loads(text)
    except (ET.ParseError, ValueError) as exc:
        raise BadOutputError(f"{dst.name} is not a readable {fmt} file: {exc}") from exc


def export(job: Job, to: str, otio_text: str) -> Path:
    """The cut as `timeline.<to>`, written by `otioconvert` from the cut's OTIO."""
    if to not in ADAPTERS:
        raise BadInputError(f"no export to {to}; choose from {tuple(ADAPTERS)}")
    opts = settings()
    src = opentools.inside(job.work / "timeline.otio", job.work)
    src.write_text(otio_text)
    dst = opentools.inside(job.work / f"timeline.{to}", job.work)
    if to == "otio":  # the cut's own OTIO is already that file
        return dst
    _convert(job, src, dst, opts, reading=False)
    _check_written(dst, to)
    return dst


def _rate_time(value: dict[str, Any] | None) -> float | None:
    if not value or not value.get("rate"):
        return None
    return float(value["value"]) / float(value["rate"])


def _first_timeline(node: Any) -> dict[str, Any]:
    """A Final Cut file reads as a collection (library, event) around its project's timeline."""
    if not isinstance(node, dict):
        raise ValueError("not an object")
    if str(node.get("OTIO_SCHEMA", "")).startswith("Timeline"):
        return node
    for child in node.get("children") or []:
        try:
            return _first_timeline(child)
        except ValueError:
            continue
    raise ValueError("no timeline in it")


def summarise(otio_json: str, name: str) -> dict[str, Any]:
    """Clips, in order, from an OTIO file: where each sits, which part of its source it uses."""
    try:
        document = _first_timeline(json.loads(otio_json))
        tracks = document["tracks"]["children"]
    except (ValueError, KeyError, TypeError) as exc:
        raise BadOutputError(f"{name}: the converted file is not an OTIO timeline: {exc}") from exc
    out: list[dict[str, Any]] = []
    for track in tracks:
        at = 0.0
        for item in track.get("children", []):
            span = item.get("source_range") or {}
            length = _rate_time(span.get("duration"))
            if length is None:
                continue
            if item.get("OTIO_SCHEMA", "").startswith("Clip"):
                ref = item.get("media_reference") or {}
                out.append(
                    {
                        "track": track.get("name") or track.get("kind"),
                        "kind": track.get("kind"),
                        "name": item.get("name"),
                        "target": ref.get("target_url"),
                        "start_sec": round(at, 3),
                        "duration_sec": round(length, 3),
                        "source_in_sec": round(_rate_time(span.get("start_time")) or 0.0, 3),
                    }
                )
            at += length
    if not out:
        raise BadOutputError(f"{name}: the timeline has no clips")
    picture = [c for c in out if c["kind"] == "Video"]
    return {"name": document.get("name"), "clips": out, "picture_clips": len(picture)}


def read_back(job: Job, source: Path) -> Path:
    """Read a timeline an editor saved (FCPXML, EDL, or OTIO) into `imports/<name>.json` in the
    job's work folder. The file may be anywhere; it is only read, and the tool writes inside."""
    if not source.is_file():
        raise BadInputError(f"{source}: not a file")
    if source.stat().st_size == 0:
        raise BadInputError(f"{source.name} is empty")
    opts = settings()
    folder = opentools.inside(job.work / "imports", job.work)
    folder.mkdir(exist_ok=True)
    converted = opentools.inside(folder / f"{source.name}.otio", job.work)
    _convert(job, source, converted, opts, reading=True)
    summary = summarise(converted.read_text(), source.name)
    summary["source"] = {"file": source.name, "sha256": opentools.sha256(source)}
    dst = opentools.inside(folder / f"{source.name}.json", job.work)
    dst.write_text(json.dumps(summary, indent=2) + "\n")
    return dst
