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
OUTPUT_KEYS = {
    "out",
    "audio_out",
    "thumbnail",
    "thumbnail_square",
    "audio_only",
    "master",
    "delivery",
}
INPUT_LIST_KEYS = {"inputs", "audio_inputs"}
INPUT_ENTRY_KEYS = {"sfx", "ambience"}
INPUT_KEYS = {"source", "input", "video", "audio", "voice", "music", "cover_file"}
ENGINE_FILES = (
    "render/__init__.py",
    "render/spec.py",
    "render/picture.py",
    "render/sound.py",
    "render/export.py",
    "render/cover.py",
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


# The picture chain keeps lossless masters between steps, hundreds of megabits a second, so a short
# piece holds gigabytes it needs only while it is being changed. `make` rebuilds them from the
# assets at no cost. Sound stems stay: they are small, and a dub reuses them.
PICTURE_OPS = frozenset({"still", "cut", "scale", "concat", "overlay_text", "burn_captions"})


def rebuildable(work: Path, plan: dict[str, Any]) -> list[Path]:
    """The picture intermediates a plan writes: never the deliverables, an asset, or a take."""
    from .spec import safe_path

    found = []
    for step in plan.get("steps", []):
        if step.get("op") in PICTURE_OPS:
            for name in _outputs(step.get("args") or {}):
                path = safe_path(work, name)
                if path.is_file():
                    found.append(path)
    return found


def clean(work: Path, plan: dict[str, Any], *, dry_run: bool = False) -> tuple[list[Path], int]:
    """Delete what `rebuildable` lists. Returns the files and the bytes they held."""
    files = rebuildable(work, plan)
    freed = sum(p.stat().st_size for p in files)
    if not dry_run:
        for path in files:
            path.unlink()
        for folder in {p.parent for p in files}:
            if folder != work.resolve() and not any(folder.iterdir()):
                folder.rmdir()
    return files, freed
