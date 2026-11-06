"""What makes a kit legal. Stdlib only, so scripts/check.py and the engine apply one set of rules.

A kit is judged by what it holds, not by a label: anything with a face or a persona is a character
and must be an invented adult, and anything with a voice must be an invented voice.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from typing import Any

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".flac"}
NAMED_SLOTS = ("looks", "locations", "props")
SINGULAR_SHARED_SLOTS = ("style", "music", "format", "topics")
MIN_AGE = 18
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")

Kit = dict[str, Any]


def content_hash(kit: Kit) -> str:
    """The hash of everything in the kit except the field that stores this hash."""
    body = {k: v for k, v in kit.items() if k != "content_sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def is_character(kit: Kit) -> bool:
    return "identity" in kit or "persona" in kit


def _refs(owner: Any) -> list[dict[str, Any]]:
    return list(owner.get("refs") or []) if isinstance(owner, dict) else []


def files(kit: Kit) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every stored file the kit points at, as (slot, entry)."""
    for slot in ("identity", "style"):
        for entry in _refs(kit.get(slot)):
            yield slot, entry
    for group in NAMED_SLOTS:
        for name, owner in (kit.get(group) or {}).items():
            for entry in _refs(owner):
                yield f"{group}.{name}", entry
    for key, entry in (kit.get("music") or {}).items():
        if isinstance(entry, dict):
            yield f"music.{key}", entry
    sample = (kit.get("voice") or {}).get("sample")
    if sample:
        yield "voice.sample", sample


def _origin_problems(kit: Kit) -> list[str]:
    origin = kit.get("origin") or {}
    out = []
    if origin.get("invented") is not True:
        out.append("origin.invented must be true: a face or voice here is made up, not a copy")
    if origin.get("real_person") is not False:
        out.append("origin.real_person must be false: a real person's likeness never renders")
    if not origin.get("attested_by"):
        out.append("origin.attested_by must name the human who checked the origin")
    return out


def _person_problems(kit: Kit) -> list[str]:
    person = kit.get("person") or {}
    out = []
    if person.get("fictional") is not True:
        out.append("person.fictional must be true for a character")
    age = person.get("age")
    if person.get("adult") is not True or not isinstance(age, int) or age < MIN_AGE:
        out.append(f"person must declare adult: true and an age of at least {MIN_AGE}")
    return out


def _file_problems(kit: Kit) -> list[str]:
    out = []
    for slot, entry in files(kit):
        if not SHA256.match(str(entry.get("sha256", ""))):
            out.append(f"{slot}: a file entry needs a sha256")
        allowed = AUDIO_SUFFIXES if slot.split(".")[0] in ("music", "voice") else IMAGE_SUFFIXES
        if str(entry.get("suffix", "")).lower() not in allowed:
            out.append(f"{slot}: suffix must be one of {sorted(allowed)}")
    return out


def problems(kit: Kit) -> list[str]:
    """Everything that stops this kit from being frozen or used."""
    out = _file_problems(kit)
    if "identity" in kit and not _refs(kit["identity"]):
        out.append("identity needs at least one reference image")
    if "identity" in kit or "voice" in kit:
        out += _origin_problems(kit)
    if is_character(kit):
        out += _person_problems(kit)
    voice = kit.get("voice")
    if voice is not None and not all(voice.get(k) for k in ("provider", "voice_id", "model")):
        out.append("voice needs provider, voice_id, and model, so it cannot drift")
    backstory = (kit.get("persona") or {}).get("backstory")
    if backstory and backstory.get("fiction") is not True:
        out.append("persona.backstory must be marked fiction: true")
    for group in NAMED_SLOTS:
        for name in kit.get(group) or {}:
            if not NAME.match(name):
                out.append(f"{group}.{name}: names are lowercase letters, digits, - and _")
    return out


def frozen_problems(kit: Kit) -> list[str]:
    """The checks for a version on disk, including that nobody edited it after freezing."""
    out = problems(kit)
    if not isinstance(kit.get("version"), int) or isinstance(kit.get("version"), bool):
        out.append("a frozen kit has an integer version")
    if not kit.get("frozen_by") or not kit.get("frozen_at"):
        out.append("a frozen kit names frozen_by and frozen_at")
    if kit.get("content_sha256") != content_hash(kit):
        out.append("content does not match content_sha256: a frozen version was edited")
    return out


def parse_pin(pin: str) -> tuple[str, int]:
    """'<kit>@<version>' to its parts. A kit pin always names an exact version."""
    kit_id, sep, version = pin.partition("@")
    if not sep or not kit_id or not version.isdigit():
        raise ValueError(f"kit pin {pin!r} must look like <kit>@<version>")
    return kit_id, int(version)
