"""What the engine knows that is not code: how each kind of shot is directed, and what each model
takes, with where each claim comes from (ADR 0027).

Two layers, merged field by field, as config is:
- the engine's, shipped with the package: `prompts/directions.yaml`, and the model rows of the
  default config with their `limits`;
- a studio's, from its own config: `directions` to override one, `limits` in a model's row to add
  or correct a claim.

A direction has an id and a version, and `directions.lock` pins every text the engine has released,
so a text never changes under an old version. A limit is a claim with a source, a date, a class
(vendor, reseller, tested, observed) and whether it is provisional; one nobody has stated is
unknown, never safe. `kalainova guide` prints the merged view, `kalainova models refresh` holds the
claims against what vendors publish now, and every take records the versions that made it (`stamp`).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import yaml

from . import config, fingerprint, resources
from .jobfs import ContractError

Fields = dict[str, Any]
DIRECTIONS = "directions.yaml"
LOCK = "directions.lock"
SECTIONS = {"sing_models": "sing", "video_models": "video"}
CLASSES = ("vendor", "reseller", "tested", "observed")


@dataclass(frozen=True)
class Direction:
    id: str
    version: str
    text: str
    why: str
    layer: str  # "engine", shipped; or "studio", from the studio's own config

    @property
    def ref(self) -> str:
        return f"{self.id}@{self.version}"


def _engine_rows() -> dict[str, Fields]:
    return yaml.safe_load(resources.path("prompts", DIRECTIONS).read_text()) or {}


def directions() -> dict[str, Direction]:
    """Every direction, the studio's over the engine's."""
    out = {
        key: Direction(
            key,
            str(row["version"]),
            str(row["text"]).strip(),
            str(row.get("why") or "").strip(),
            "engine",
        )  # fmt: skip
        for key, row in _engine_rows().items()
    }
    for key, row in (config.studio().get("directions") or {}).items():
        if not row.get("version") or not row.get("text"):
            raise ContractError(f"the studio's direction {key} needs a version and a text")
        out[key] = Direction(key, f"studio-{row['version']}", str(row["text"]).strip(),
                             str(row.get("why") or "").strip(), "studio")  # fmt: skip
    return out


def direction(key: str) -> Direction:
    found = directions().get(key)
    if not found:
        raise ContractError(f"no direction {key} in prompts/{DIRECTIONS} or the studio's config")
    return found


def for_beat(beat: Fields) -> list[Direction]:
    """The directions a shot is given: a person singing on camera is directed to perform."""
    return [direction("perform.sing")] if beat.get("sings") else []


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def unpinned() -> list[str]:
    """The engine's directions whose text is not the one released under their version."""
    released = json.loads(resources.path("prompts", LOCK).read_text())
    out = []
    for key, row in _engine_rows().items():
        found = Direction(key, str(row["version"]), str(row["text"]).strip(), "", "engine")
        if released.get(found.ref) != _sha(found.text):
            out.append(found.ref)
    return out


def models() -> dict[str, tuple[str, str, Fields]]:
    """Every model a config row describes: `{model: (capability, provider, row)}`."""
    out: dict[str, tuple[str, str, Fields]] = {}
    studio = config.studio()
    for section, capability in SECTIONS.items():
        for provider, rows in (studio.get(section) or {}).items():
            for model, row in (rows or {}).items():
                out[model] = (capability, provider, dict(row or {}))
    return out


def prompt_field(capability: str, row: Fields) -> str:
    """The field a model's prompt goes in; empty when it takes none."""
    return str(row.get("prompt_param", "prompt")) if capability == "sing" else "prompt"


def limit(row: Fields, name: str) -> Fields | None:
    """A claim about one of a model's limits, such as `prompt_chars`, or None if no one made one."""
    found = (row.get("limits") or {}).get(name)
    return dict(found) if isinstance(found, dict) and found.get("max") is not None else None


def claim_text(claim: Fields | None) -> str:
    if not claim:
        return "unknown: no source states it"
    tag = f"{claim.get('class', '?')}, {claim.get('observed', '?')}"
    tag += ", provisional" if claim.get("provisional") else ""
    return f"at most {claim['max']} ({tag}; {claim.get('source', 'no source given')})"


def refresh(fields_of: Callable[[str], Fields]) -> list[str]:
    """Each model's recorded prompt limit held against what its vendor's schema states now. It
    reports and changes nothing: a reviewed claim is never overwritten by a fetch."""
    out = []
    for model, (capability, provider, row) in sorted(models().items()):
        field = prompt_field(capability, row)
        if provider != "fal" or not field:
            continue
        claim = limit(row, "prompt_chars")
        try:
            stated = stated_max(fields_of(model).get(field) or {})
        except Exception as exc:  # noqa: BLE001 - one unreadable schema must not hide the rest
            out.append(f"{model}: could not read its schema ({exc})")
            continue
        out.append(f"{model}: {_compare(field, claim, stated)}")
    return out


def stated_max(field: Fields) -> int | None:
    """The longest a field may be, where a schema states it, on the field or on one of its types."""
    for part in [field, *(field.get("anyOf") or [])]:
        if isinstance(part, dict) and part.get("maxLength") is not None:
            return int(part["maxLength"])
    return None


def _compare(field: str, claim: Fields | None, stated: int | None) -> str:
    if stated is not None and claim:
        if int(claim["max"]) != stated:
            return f"{field}: the schema now says {stated}, recorded {claim_text(claim)}: DIFFERS"
        return f"{field}: {claim_text(claim)}; the schema agrees"
    if stated is not None:
        return f"{field}: the schema says {stated}; checked before sending, not recorded"
    if claim:
        return f"{field}: {claim_text(claim)}; the schema states none"
    return f"{field}: {claim_text(None)}"


def stamp(beat: Fields | None = None, inputs: dict[str, str] | None = None) -> Fields:
    """What made a take, beyond its model and prompt: the engine, the merged knowledge, the
    directions given, the judges' setup, and the inputs' hashes."""
    studio = config.studio()
    knowledge = json.dumps(
        {"directions": {k: d.ref for k, d in directions().items()}, "config": studio},
        sort_keys=True, default=str,
    )  # fmt: skip
    judges = json.dumps(studio.get("judges") or {}, sort_keys=True, default=str)
    out: Fields = {
        "engine": fingerprint.code_stamp(),
        "knowledge": _sha(knowledge)[:12],
        "judges": _sha(judges)[:12],
        "directions": [d.ref for d in for_beat(beat or {})],
    }
    if inputs:
        out["inputs"] = dict(inputs)
    return out
