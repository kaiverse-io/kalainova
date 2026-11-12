"""Calling an open tool as a command (ADR 0012): the one place an adapter's subprocess is run.

An adapter names its program and the version it expects, checks both before a job reaches it, builds
an argument list (never a shell string), runs it with a timeout and kills the whole process group
when that passes, and keeps a bounded record of the run in the job's folder. Five failures are told
apart, each its own class, so a caller and an operator can see which one it was:

  ToolMissingError   the program is not on PATH, or is not the version this adapter was written for
  BadInputError      what the tool was handed is not usable, found before the tool runs
  ToolTimeoutError   the tool ran past its deadline and was cancelled
  ToolFailedError    the tool ran and exited non-zero
  BadOutputError     the tool exited zero but left nothing, or something unreadable

Nothing here imports another engine module but `jobfs`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .jobfs import ContractError, Job

KEEP_CHARS = 2000  # of each stream, from its end, where a tool's error usually is
LOG_NAME = "tool_runs.json"


class ToolError(ContractError):
    """A tool step that did not finish. The subclass says why."""


class ToolMissingError(ToolError):
    pass


class BadInputError(ToolError):
    pass


class ToolTimeoutError(ToolError):
    pass


class ToolFailedError(ToolError):
    pass


class BadOutputError(ToolError):
    pass


@dataclass(frozen=True)
class Run:
    argv: list[str]
    returncode: int
    started: str
    ended: str
    seconds: float
    stdout: str
    stderr: str


def _tail(text: str) -> str:
    return text if len(text) <= KEEP_CHARS else "..." + text[-KEEP_CHARS:]


def find(command: str, *, capability: str, adapter: str, hint: str) -> str:
    """The full path of the program, or a stop that names it, the config key, and how to install."""
    exe = shutil.which(command)
    if exe is None:
        raise ToolMissingError(
            f"adapters.{capability} is {adapter}, but `{command}` is not on PATH. {hint}, "
            f"or set adapters.{capability}.use to inhouse"
        )
    return exe


def run(argv: list[str], *, timeout: float, cwd: Path | None = None) -> Run:
    """Run one command to the end or to its deadline. The tool gets its own process group, so a
    timeout cancels it and anything it started."""
    started = datetime.now(UTC).isoformat(timespec="seconds")
    t0 = time.monotonic()
    try:
        proc = subprocess.Popen(  # noqa: S603 - an argument list from the adapter, never a shell
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        raise ToolMissingError(f"`{argv[0]}` could not be started: {exc}") from exc
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        name = Path(argv[0]).name
        raise ToolTimeoutError(f"`{name}` ran past {timeout:g}s and was cancelled") from exc
    return Run(
        argv=argv,
        returncode=proc.returncode,
        started=started,
        ended=datetime.now(UTC).isoformat(timespec="seconds"),
        seconds=round(time.monotonic() - t0, 2),
        stdout=_tail(out),
        stderr=_tail(err),
    )


def version(exe: str, pattern: str, *, flag: str = "--version", timeout: float = 120) -> str:
    """The version a program reports: the first group of `pattern` in what it prints."""
    got = run([exe, flag], timeout=timeout)
    found = re.search(pattern, got.stdout + "\n" + got.stderr)
    if not found:
        raise ToolMissingError(
            f"`{Path(exe).name} {flag}` printed no version this adapter can read"
        )
    return found.group(1)


def require_version(exe: str, pattern: str, expected: str, *, program: str) -> str:
    """Stop unless the program's version starts with `expected` ("0.18" takes 0.18.1)."""
    got = version(exe, pattern)
    if not (got == expected or got.startswith(expected.rstrip(".") + ".")):
        raise ToolMissingError(f"{program} {got} is installed; this adapter expects {expected}.x")
    return got


def inside(path: Path, root: Path) -> Path:
    """`path` resolved, only if it lies in `root` by real directories: `..` and a symlink anywhere
    along the way are refused, so a tool is never pointed outside the job's folders."""
    if ".." in path.parts:
        raise BadInputError(f"{path}: `..` is not allowed in a path a tool reads or writes")
    base = root.resolve()
    probe = path if path.is_absolute() else base / path
    for part in [probe, *probe.parents]:
        if part == base:
            break
        if part.is_symlink():
            raise BadInputError(f"{path}: {part.name} is a symlink, and a tool does not follow it")
    resolved = probe.resolve()
    if not resolved.is_relative_to(base):
        raise BadInputError(f"{path} is outside {root}")
    return resolved


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def record(
    job: Job,
    tool: str,
    got: Run,
    *,
    options: dict[str, Any],
    inputs: list[Path],
    outputs: list[Path],
) -> None:
    """Append what was run to the job's `tool_runs.json`: the program and its options, times, exit
    status, a bounded copy of what it printed, and the hash of every input and output."""
    log = job.work / LOG_NAME
    runs = json.loads(log.read_text()) if log.exists() else []
    runs.append(
        {
            "tool": tool,
            "argv": got.argv,
            "options": options,
            "started": got.started,
            "ended": got.ended,
            "seconds": got.seconds,
            "returncode": got.returncode,
            "stdout": got.stdout,
            "stderr": got.stderr,
            "inputs": {p.name: sha256(p) for p in inputs if p.is_file()},
            "outputs": {p.name: sha256(p) for p in outputs if p.is_file()},
        }
    )
    log.write_text(json.dumps(runs, indent=2) + "\n")
