"""KIT: what must stay the same. Versioned, frozen, and backed by a content-addressed store.

  kits/<id>/draft/kit.json   editable, until a human freezes it
  kits/<id>/v<N>/kit.json    frozen; any later edit is detected by content_sha256
  store/<aa>/<sha256><ext>   the bytes, outside git. Point $KALAINOVA_STORE at durable storage.

Reference images stay out of git but are the character: losing them loses the face.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import shutil
from pathlib import Path
from typing import Any

from . import blobstore, kitrules
from .blobstore import sha256_file
from .jobfs import ContractError, validate

MAX_REFERENCE_BYTES = 8 * 1024 * 1024  # references travel inline to the provider
Kit = dict[str, Any]


def store_root(root: Path) -> Path:
    return Path(os.environ.get("KALAINOVA_STORE", root / "store"))


def blob_path(root: Path, entry: dict[str, Any]) -> Path:
    """The local path of a stored file, fetched from durable storage if it is not cached yet."""
    sha = str(entry["sha256"])
    path = store_root(root) / sha[:2] / f"{sha}{entry['suffix']}"
    if not path.exists():
        blobstore.fetch(path)
    return path


def put(root: Path, src: Path, *, label: str = "") -> dict[str, Any]:
    """Copy a file into the store and return the entry a kit records."""
    if not src.is_file():
        raise ContractError(f"no file at {src}")
    entry: dict[str, Any] = {"sha256": sha256_file(src), "suffix": src.suffix.lower()}
    if label:
        entry["label"] = label
    dst = store_root(root) / entry["sha256"][:2] / f"{entry['sha256']}{entry['suffix']}"
    if not dst.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
    blobstore.push(dst)
    return entry


def _dir(root: Path, kit_id: str) -> Path:
    if not kitrules.NAME.match(kit_id):
        raise ContractError(f"kit id {kit_id!r}: use lowercase letters, digits, - and _")
    return root / "kits" / kit_id


def draft_path(root: Path, kit_id: str) -> Path:
    return _dir(root, kit_id) / "draft" / "kit.json"


def read_draft(root: Path, kit_id: str) -> Kit:
    path = draft_path(root, kit_id)
    if not path.exists():
        raise ContractError(f"kit {kit_id} has no draft; run `kit new` or `kit bump`")
    return dict(json.loads(path.read_text()))


def write_draft(root: Path, kit_id: str, kit: Kit) -> Path:
    validate("kit", kit, f"kits/{kit_id}/draft/kit.json")
    path = draft_path(root, kit_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(kit, indent=2, ensure_ascii=False) + "\n")
    return path


def new(root: Path, kit_id: str, *, label: str = "") -> Path:
    if _dir(root, kit_id).exists():
        raise ContractError(f"kit {kit_id} exists; use `kit bump` to change it")
    kit: Kit = {"schema_version": "0.1", "kit_id": kit_id, "version": "draft"}
    if label:
        kit["label"] = label
    return write_draft(root, kit_id, kit)


def _slot_owner(kit: Kit, slot: str) -> dict[str, Any]:
    group, _, name = slot.partition(".")
    if group in ("identity", "style") and not name:
        return dict(kit.setdefault(group, {}))
    if group in kitrules.NAMED_SLOTS and name:
        return dict(kit.setdefault(group, {}).setdefault(name, {}))
    raise ContractError(f"unknown image slot {slot!r}: use identity, style, looks.<name>, ...")


def add_file(root: Path, kit_id: str, slot: str, src: Path, *, label: str = "") -> Kit:
    """Store a file and attach it to a slot of the draft: an image reference or an audio file."""
    kit = read_draft(root, kit_id)
    suffix = src.suffix.lower()
    if slot in ("music.theme", "music.whoosh", "voice.sample"):
        if suffix not in kitrules.AUDIO_SUFFIXES:
            raise ContractError(f"{slot} takes audio, not {suffix}")
        group, key = slot.split(".")
        kit.setdefault(group, {})[key] = put(root, src, label=label)
        write_draft(root, kit_id, kit)
        return kit
    if suffix not in kitrules.IMAGE_SUFFIXES:
        raise ContractError(f"{slot} takes {sorted(kitrules.IMAGE_SUFFIXES)}, not {suffix}")
    if src.is_file() and src.stat().st_size > MAX_REFERENCE_BYTES:
        raise ContractError(f"{src.name} is over {MAX_REFERENCE_BYTES >> 20} MB; downscale it")
    owner = _slot_owner(kit, slot)
    owner["refs"] = [*(owner.get("refs") or []), put(root, src, label=label)]
    group, _, name = slot.partition(".")
    if name:
        kit[group][name] = owner
    else:
        kit[group] = owner
    write_draft(root, kit_id, kit)
    return kit


def merge(root: Path, kit_id: str, fields: dict[str, Any]) -> Kit:
    """Merge text fields into the draft, such as persona, style text, or origin."""
    kit = read_draft(root, kit_id)
    for key, value in fields.items():
        if key in ("schema_version", "kit_id", "version", "frozen_at", "frozen_by"):
            raise ContractError(f"{key} is set by the engine")
        if isinstance(value, dict) and isinstance(kit.get(key), dict):
            kit[key] = {**kit[key], **value}
        else:
            kit[key] = value
    write_draft(root, kit_id, kit)
    return kit


def versions(root: Path, kit_id: str) -> list[int]:
    found = [p.parent.name[1:] for p in _dir(root, kit_id).glob("v*/kit.json")]
    return sorted(int(v) for v in found if v.isdigit())


def freeze(root: Path, kit_id: str, *, by: str) -> Kit:
    """Turn the draft into the next immutable version. A human does this: `by` is their attestation
    that the face and voice were invented, and that the character is an adult."""
    if not by.strip():
        raise ContractError("freeze needs the name of the human who checked this kit")
    kit = read_draft(root, kit_id)
    bad = kitrules.problems(kit)
    missing = [
        f"{slot}: {entry['sha256'][:12]} is not in the store"
        for slot, entry in kitrules.files(kit)
        if not blob_path(root, entry).is_file()
    ]
    if bad or missing:
        raise ContractError(f"kit {kit_id} cannot freeze:\n  " + "\n  ".join(bad + missing))
    number = (versions(root, kit_id) or [0])[-1] + 1
    now = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    kit.update(version=number, frozen_by=by, frozen_at=now)
    kit["content_sha256"] = kitrules.content_hash(kit)
    validate("kit", kit, f"kits/{kit_id}/v{number}/kit.json")
    path = _dir(root, kit_id) / f"v{number}" / "kit.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(kit, indent=2, ensure_ascii=False) + "\n")
    shutil.rmtree(draft_path(root, kit_id).parent)
    return kit


def bump(root: Path, kit_id: str) -> Path:
    """Start a new draft from the latest version. Jobs stay pinned to the versions they locked."""
    if draft_path(root, kit_id).exists():
        raise ContractError(f"kit {kit_id} already has a draft")
    known = versions(root, kit_id)
    if not known:
        raise ContractError(f"kit {kit_id} has no frozen version to start from")
    kit = load(root, kit_id, known[-1])
    for key in ("frozen_at", "frozen_by", "content_sha256"):
        kit.pop(key, None)
    kit["version"] = "draft"
    return write_draft(root, kit_id, kit)


def load(root: Path, kit_id: str, version: int) -> Kit:
    """A frozen version, refused if it was edited after freezing."""
    path = _dir(root, kit_id) / f"v{version}" / "kit.json"
    if not path.exists():
        raise ContractError(
            f"kit {kit_id}@{version} does not exist. A character is drafted, looked at on a sheet "
            f"(`kalainova look {kit_id}`), picked from by a person, and frozen by a person "
            f"(`kalainova kit freeze {kit_id} --by NAME`); a stream pins only a frozen version"
        )
    kit: Kit = json.loads(path.read_text())
    validate("kit", kit, str(path))
    bad = kitrules.frozen_problems(kit)
    if bad:
        raise ContractError(f"kit {kit_id}@{version}: " + "; ".join(bad))
    return kit


def verify_files(root: Path, kit: Kit) -> list[str]:
    """Problems with the stored bytes: a file that is missing or no longer matches its hash."""
    out = []
    for slot, entry in kitrules.files(kit):
        path = blob_path(root, entry)
        if not path.is_file():
            out.append(f"{kit['kit_id']}: {slot}: {entry['sha256'][:12]} is not in the store")
        elif sha256_file(path) != entry["sha256"]:
            out.append(f"{kit['kit_id']}: {slot}: {entry['sha256'][:12]} changed on disk")
    return out
