"""Change one shot, re-encode what it touches, and keep the rest.

A step keeps its old output when its operation, its arguments, its input files, and the code that
runs it are all as they were last time. A kept step leaves its output untouched, so the steps after
it see nothing new either. Without this, every small change re-encodes a whole piece, which makes
long form impossible to iterate on.
"""

from __future__ import annotations

import hashlib
import json
from functools import cache
from pathlib import Path
from typing import Any

CACHE_FILE = ".render_cache.json"
OUTPUT_KEYS = {"out", "audio_out", "thumbnail", "audio_only", "master", "delivery"}
INPUT_LIST_KEYS = {"inputs", "audio_inputs"}
INPUT_ENTRY_KEYS = {"sfx", "ambience"}
INPUT_KEYS = {"source", "input", "video", "audio", "voice", "music"}
ENGINE_FILES = (
    "render/__init__.py",
    "render/spec.py",
    "render/picture.py",
    "render/sound.py",
    "render/export.py",
    "render/cache.py",
    "bar/sound.py",  # the mix sets music against the voice with this measure
    "media.py",
    "captions.py",
    "motion.py",
    "look.py",
)


@cache
def _engine_version() -> str:
    """Changing how a step runs must re-run it, so the code is part of what a step depends on."""
    digest = hashlib.sha256()
    here = Path(__file__).parents[1]
    for name in ENGINE_FILES:
        digest.update((here / name).read_bytes())
    return digest.hexdigest()


def _input_names(args: dict[str, Any]) -> list[str]:
    names = [str(args[k]) for k in INPUT_KEYS if args.get(k)]
    for key in INPUT_LIST_KEYS:
        names += [str(item) for item in args.get(key) or []]
    for key in INPUT_ENTRY_KEYS:
        names += [str(entry["path"]) for entry in args.get(key) or []]
    return sorted(names)


def _stat(work: Path, name: str) -> list[int] | None:
    path = work / name
    if not path.exists():
        return None
    info = path.stat()
    return [info.st_size, info.st_mtime_ns]


def key(work: Path, op: str, args: dict[str, Any]) -> str:
    """Everything this step's output depends on."""
    inputs = {name: _stat(work, name) for name in _input_names(args)}
    payload = {"op": op, "args": args, "inputs": inputs, "engine": _engine_version()}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _outputs(args: dict[str, Any]) -> list[str]:
    return [str(args[k]) for k in OUTPUT_KEYS if args.get(k)]


def unchanged(
    work: Path, done: dict[str, str], n: int, step_key: str, args: dict[str, Any]
) -> bool:
    outputs = _outputs(args)
    if not outputs or done.get(str(n)) != step_key:
        return False
    return all((work / name).exists() for name in outputs)


def remember(done: dict[str, str], n: int, step_key: str) -> None:
    done[str(n)] = step_key


def load(work: Path) -> dict[str, str]:
    path = work / CACHE_FILE
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text())
    except ValueError:
        return {}
    return {str(k): str(v) for k, v in loaded.items()}


def save(work: Path, done: dict[str, str]) -> None:
    (work / CACHE_FILE).write_text(json.dumps(done, indent=2) + "\n")
