"""What a render plan may say: a closed list of operations, each with typed arguments.

A plan can be written by a model, so nothing in it is trusted. Every value is coerced to its type
before it reaches ffmpeg, and every path has to stay inside the job's work folder.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import look
from ..jobfs import ContractError

OPS = (
    "still",
    "cut",
    "scale",
    "concat",
    "overlay_text",
    "mix_audio",
    "loudnorm",
    "burn_captions",
    "caption_files",
    "export_audio",
    "export",
)
MOTIONS = ("none", "push_in", "push_out", "pan_left", "pan_right", "drift_up")
PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow")
GRADES = tuple(look.LOOKS)
RANGES = {"crop_x": (0.0, 1.0), "speed": (0.25, 4.0), "zoom": (1.0, 1.5), "gamma": (0.5, 2.0)}
ENTRY_NUMBERS = ("start_sec", "end_sec", "gain_db")

# Closed arg spec per op. Every value is coerced to its type before it reaches ffmpeg, so a
# model-written plan cannot smuggle filtergraph text through a number. Text (titles, captions)
# only ever goes into .ass files, never into a filtergraph.
SPEC: dict[str, dict[str, Any]] = {
    "still": {
        "source": "path",
        "out": "path",
        "width": "int",
        "height": "int",
        "fps": "num",
        "duration_sec": "num",
        "motion": MOTIONS,
        "crop_x": "num?",
        "grade": GRADES + (None,),
        "gamma": "num?",
    },
    "cut": {
        "source": "path",
        "kind": ("video",),
        "in_sec": "num",
        "out_sec": "num",
        "fps": "num",
        "out": "path",
        "pad_to_sec": "num?",
        "speed": "num?",
        "audio_out": "path?",
        "audio_from_source": "bool?",
    },
    "scale": {
        "input": "path",
        "out": "path",
        "width": "int",
        "height": "int",
        "fps": "num",
        "duration_sec": "num",
        "crop_x": "num?",
        "picture_box": "box?",
        "zoom": "num?",
        "grade": GRADES + (None,),
        "gamma": "num?",
    },
    "concat": {
        "inputs": "paths",
        "out": "path",
        "fps": "num",
        "transition": ("cut", "dissolve", None),
        "xfade_sec": "num?",
        "durations": "list",
        "audio_inputs": "list",
        "audio_out": "path?",
    },
    "overlay_text": {
        "input": "path",
        "out": "path",
        "width": "int",
        "height": "int",
        "overlays": "list",
        "titles": "list",
        "duration_sec": "num",
        "theme": ("studio", "bold", None),
    },
    "burn_captions": {
        "input": "path",
        "out": "path",
        "width": "int",
        "height": "int",
        "style": ("studio", "kinetic", "plain"),
        "captions": "list",
    },
    "caption_files": {"cues": "list", "fps": "num"},
    "export_audio": {"audio": "path", "master": "path", "delivery": "path", "synthetic": "bool?"},
    "mix_audio": {
        "out": "path",
        "duration_sec": "num",
        "voice": "path?",
        "voice_chain": "bool?",
        "music": "path?",
        "music_gain_db": "num?",
        "duck": "bool?",
        "sfx": "list",
        "ambience": "list",
    },
    "loudnorm": {"input": "path", "out": "path", "target_lufs": "num", "true_peak_dbtp_max": "num"},
    "export": {
        "video": "path",
        "audio": "path?",
        "out": "path",
        "crf": "int",
        "preset": PRESETS,
        "thumbnail": "path?",
        "thumbnail_square": "path?",
        "cover_at_sec": "num?",
        "cover_file": "path?",
        "audio_only": "path?",
        "fade_in_sec": "num?",
        "fade_out_sec": "num?",
        "duration_sec": "num?",
        "fps": "num?",
        "master": "path?",
        "synthetic": "bool?",
    },
}


def _is_number(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool)


def is_box(v: object) -> bool:
    """Four finite shares of the frame, x, y, w, h, with a picture left inside it."""
    if not isinstance(v, list) or len(v) != 4:
        return False
    if not all(_is_number(x) for x in v):
        return False
    x, y, w, h = v
    return bool(0 <= x and 0 <= y and 0 < w and 0 < h and x + w <= 1 and y + h <= 1)


def _plain_path(v: object) -> bool:
    return isinstance(v, str) and bool(v) and not v.startswith("-")


def _check_num(v: Any) -> None:
    if not _is_number(v) or not math.isfinite(v):
        raise ValueError(f"{v!r} is not a number")


def _check_int(v: Any) -> None:
    if isinstance(v, bool) or not isinstance(v, int) or not 0 < v <= 8192:
        raise ValueError(f"{v!r} is not an int in range")


def _check_bool(v: Any) -> None:
    if not isinstance(v, bool):
        raise ValueError(f"{v!r} is not a bool")


def _check_path(v: Any) -> None:
    if not _plain_path(v):
        raise ValueError(f"{v!r} is not a relative path")


def _check_paths(v: Any) -> None:
    if not isinstance(v, list) or not all(_plain_path(x) for x in v):
        raise ValueError("inputs must be a list of relative paths")


def _check_list(v: Any) -> None:
    if not isinstance(v, list):
        raise ValueError("expected a list")


def _check_box(v: Any) -> None:
    if not is_box(v):
        raise ValueError(f"{v!r} is not x, y, w, h inside the frame")


CHECKS: dict[str, Callable[[Any], None]] = {
    "num": _check_num,
    "int": _check_int,
    "bool": _check_bool,
    "path": _check_path,
    "paths": _check_paths,
    "list": _check_list,
    "box": _check_box,
}


def _checked(kind: Any, v: Any) -> Any:
    """The value as its declared kind. Raises ValueError for anything else."""
    if isinstance(kind, tuple):
        if v not in kind:
            raise ValueError(f"{v!r} not in {kind}")
        return v
    CHECKS[kind](v)
    return float(v) if kind == "num" else v


def _well_formed_entry(entry: Any) -> bool:
    return (
        isinstance(entry, dict)
        and _plain_path(entry.get("path"))
        and all(_is_number(entry.get(k, 0)) for k in ENTRY_NUMBERS)
    )


def _check_entries(out: dict[str, Any], n: int) -> None:
    for entry in [*(out.get("sfx") or []), *(out.get("ambience") or [])]:
        if not _well_formed_entry(entry):
            raise ContractError(f"step {n} (mix_audio): malformed sfx entry")
    for path in out.get("audio_inputs") or []:
        if not _plain_path(path):
            raise ContractError(f"step {n} (concat): malformed audio input")


def _check_ranges(out: dict[str, Any], n: int) -> None:
    for key, (low, high) in RANGES.items():
        value = out.get(key)
        if value is not None and not low <= value <= high:
            raise ContractError(f"step {n}: {key} out of range")


def _value(key: str, kind: Any, args: dict[str, Any], op: str, n: int) -> Any:
    optional = isinstance(kind, str) and kind.endswith("?")
    plain = kind.rstrip("?") if isinstance(kind, str) else kind
    if key not in args or args[key] is None:
        if plain == "list":
            return []
        if optional or (isinstance(plain, tuple) and None in plain):
            return None
        raise ContractError(f"step {n} ({op}): missing {key}")
    try:
        return _checked(plain, args[key])
    except ValueError as exc:
        raise ContractError(f"step {n} ({op}): {key}: {exc}") from exc


def coerce(op: str, args: dict[str, Any], n: int) -> dict[str, Any]:
    """A step's arguments with every value checked, or a refusal that names the bad one."""
    spec = SPEC[op]
    extra = set(args) - set(spec)
    if extra:
        raise ContractError(f"step {n} ({op}): unknown args {sorted(extra)}")
    out = {key: _value(key, kind, args, op, n) for key, kind in spec.items()}
    _check_entries(out, n)
    _check_ranges(out, n)
    return out


def safe_path(work: Path, rel: str) -> Path:
    """A path a plan named, refused unless it stays inside the job's work folder."""
    path = (work / rel).resolve()
    if work.resolve() not in path.parents and path != work.resolve():
        raise ContractError(f"path escapes job work dir: {rel}")
    return path
