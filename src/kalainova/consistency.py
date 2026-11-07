"""What stays the same across pieces, and how the engine holds it there.

A kit says WHAT is fixed. RULES below says HOW each kind of thing is applied and checked, in one
place, so no channel configures it. resolve() combines a stream's kits and refuses conflicts;
build_lock() pins exact versions on a job; for_job() re-checks those pins before any later stage.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import blobstore, kitrules, kits
from .jobfs import ContractError, Job
from .providers import base

Kit = dict[str, Any]
Reference = dict[str, Any]


@dataclass(frozen=True)
class Rule:
    slot: str
    applied: str
    checked: str


RULES = (
    Rule("identity", "reference files sent with every still and video", "vision check, then human"),
    Rule("looks", "sent only when the beat names one", "beat must name one the kit has"),
    Rule("locations", "sent only when the beat names one", "beat must name one the kit has"),
    Rule("props", "sent only when the beat names one", "beat must name one the kit has"),
    Rule("voice", "pinned provider, voice id, model, settings", "fails if missing or different"),
    Rule("persona", "loaded into the script step", "never_say blocks; vision judge reads script"),
    Rule("style", "fixed text and references on every shot", "vision check"),
    Rule("music", "the same file is reused, never regenerated", "hash match"),
    Rule("format", "profile and edit settings set on the job", "existing QA checks"),
    Rule("topics", "loaded into the script step", "judge reads script"),
    Rule("canon", "loaded into the script step", "judge flags contradictions; human adds facts"),
)


@dataclass
class Resolved:
    """A stream's kits, combined. Character slots belong to a role; the rest are shared."""

    root: Path
    kits: dict[str, Kit]
    characters: dict[str, Kit]
    shared: dict[str, Any]
    named: dict[str, dict[str, dict[str, Any]]]
    canon: list[str]


def _claim(table: dict[str, str], slot: str, role: str) -> None:
    if slot in table:
        raise ContractError(
            f"kits {table[slot]} and {role} both fill {slot}; a slot has exactly one owner"
        )
    table[slot] = role


def _named_slots(role: str, kit: Kit, owners: dict[str, str], named: dict[str, Any]) -> None:
    for group in ("locations", "props"):
        for name, owner in (kit.get(group) or {}).items():
            _claim(owners, f"{group}.{name}", role)
            named[group][name] = owner


def resolve(root: Path, stream: dict[str, Any]) -> Resolved:
    loaded: dict[str, Kit] = {}
    for role, pin in (stream.get("kits") or {}).items():
        kit_id, version = kitrules.parse_pin(pin)
        loaded[role] = kits.load(root, kit_id, version)
    owners: dict[str, str] = {}
    characters: dict[str, Kit] = {}
    shared: dict[str, Any] = {}
    named: dict[str, dict[str, dict[str, Any]]] = {"locations": {}, "props": {}}
    for role, kit in loaded.items():
        if kitrules.is_character(kit):
            characters[role] = kit
        elif "voice" in kit:
            _claim(owners, "voice", role)
            shared["voice"] = kit["voice"]
        for slot in kitrules.SINGULAR_SHARED_SLOTS:
            if slot in kit:
                _claim(owners, slot, role)
                shared[slot] = kit[slot]
        _named_slots(role, kit, owners, named)
    canon_file = root / "streams" / str(stream.get("stream_id")) / "canon.jsonl"
    canon = (
        [json.loads(x)["fact"] for x in canon_file.read_text().splitlines() if x.strip()]
        if canon_file.exists()
        else []
    )
    return Resolved(root, loaded, characters, shared, named, canon)


def choose_cast(resolved: Resolved, wanted: list[str] | None) -> list[str]:
    """Who appears. Refuses to guess when the channel has several people and none was named."""
    roster = list(resolved.characters)
    if wanted:
        unknown = [c for c in wanted if c not in roster]
        if unknown:
            raise ContractError(f"{unknown} not on this stream; its cast is {roster or 'empty'}")
        return list(wanted)
    if len(roster) > 1:
        raise ContractError(f"this stream has several characters; choose with --cast: {roster}")
    return roster


def _supported(capability: str, pin: dict[str, Any] | None) -> dict[str, Any]:
    if not pin:
        raise ContractError(f"a stream with a character must pin a {capability} generator")
    try:
        provider = base.get(pin["provider"])
    except KeyError as exc:
        raise ContractError(str(exc)) from exc
    support = provider.reference_support(capability, pin["model"])
    if not support:
        raise ContractError(
            f"{pin['provider']}/{pin['model']} takes no reference images for {capability}, so it "
            "cannot hold a face. Pin one listed under reference_models in config/studio.yaml"
        )
    return support


def preflight(resolved: Resolved, stream: dict[str, Any], cast: list[str]) -> None:
    """Stop before spending if the pinned tools cannot keep what the kits promise."""
    media = set(stream.get("media") or [])
    pins = stream.get("generators") or {}
    if (resolved.shared.get("style") or {}).get("refs"):
        _supported("image", pins.get("image"))
    if cast:
        wanted = [c for c in ("image", "video") if c == "image" or c in media]
        for capability in wanted:
            support = _supported(capability, pins.get(capability))
            if len(cast) > support.get("max_characters", 99):
                raise ContractError(
                    f"{pins[capability]['model']} holds {support['max_characters']} characters "
                    f"at once; this job asks for {len(cast)}"
                )
    if media & {"audio", "video"}:
        speakers = [c for c in cast if "voice" in resolved.characters[c]]
        if not speakers and "voice" not in resolved.shared:
            raise ContractError(
                "no kit on this stream fills voice, so the piece would use a default voice"
            )
        silent = [c for c in cast if c not in speakers]
        if silent and "voice" not in resolved.shared:
            raise ContractError(f"{silent} have no voice in their kit")


def _canon(resolved: Resolved, stream_id: str) -> dict[str, Any]:
    path = resolved.root / "streams" / stream_id / "canon.jsonl"
    lines = path.read_text().splitlines() if path.exists() else []
    digest = hashlib.sha256("\n".join(lines).encode()).hexdigest()
    return {"lines": len(lines), "sha256": digest}


def build_lock(
    resolved: Resolved, stream: dict[str, Any], job_id: str, cast: list[str]
) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "job_id": job_id,
        "stream": stream["stream_id"],
        "distribution_identity": stream["distribution_identity"],
        "cast": cast,
        "generators": stream.get("generators") or {},
        "kits": {
            role: {
                "kit_id": kit["kit_id"],
                "version": kit["version"],
                "content_sha256": kit["content_sha256"],
            }
            for role, kit in resolved.kits.items()
        },
        "canon": _canon(resolved, stream["stream_id"]),
    }


def _home(job: Job) -> Path:
    return job.folder.parents[1]


def for_job(job: Job) -> tuple[Resolved, dict[str, Any]] | None:
    """The kits a job locked, or None for a job with no stream. Raises if anything has moved."""
    if not job.job.get("stream"):
        return None
    root = _home(job)
    lock = job.read("kit_lock")
    pins = {r: f"{k['kit_id']}@{k['version']}" for r, k in lock["kits"].items()}
    resolved = resolve(root, {"stream_id": lock["stream"], "kits": pins})
    bad = []
    for role, kit in resolved.kits.items():
        if kit["content_sha256"] != lock["kits"][role]["content_sha256"]:
            bad.append(f"{role}: {pins[role]} is not the version this job locked")
        bad += kits.verify_files(root, kit)
    if bad:
        raise ContractError(f"{job.id}: the kit lock does not hold:\n  " + "\n  ".join(bad))
    return resolved, lock


def lock_sha256(job: Job) -> str:
    return blobstore.sha256_file(job.path("kit_lock"))


# ------------------------------------------------------------------ the script
def planner_context(resolved: Resolved, cast: list[str]) -> str:
    """The fixed things the writer has to work inside."""
    context: dict[str, Any] = {}
    people = {}
    for role in cast:
        kit = resolved.characters[role]
        people[role] = {
            "look_description": (kit.get("identity") or {}).get("description", ""),
            "persona": kit.get("persona") or {},
            "looks": sorted(kit.get("looks") or {}),
        }
    if people:
        context["cast"] = people
    for group in ("locations", "props"):
        if resolved.named[group]:
            context[group] = sorted(resolved.named[group])
    if (resolved.shared.get("topics") or {}).get("rules"):
        context["topic_rules"] = resolved.shared["topics"]["rules"]
    if (resolved.shared.get("format") or {}).get("rules"):
        context["format_rules"] = resolved.shared["format"]["rules"]
    if resolved.canon:
        context["canon_so_far_fiction"] = resolved.canon
    return json.dumps(context, indent=2, ensure_ascii=False)


def _script_text(packet: dict[str, Any]) -> list[str]:
    publish = packet.get("publish") or {}
    return [
        *(b["text"] for b in packet["beats"]),
        *(packet.get("hooks") or []),
        str(publish.get("title", "")),
        str(publish.get("description", "")),
    ]


def _beat_problems(resolved: Resolved, beat: dict[str, Any], cast: list[str]) -> list[str]:
    out = []
    bid = beat.get("id", "?")
    members = beat.get("cast") or []
    for role in members:
        if role not in cast:
            out.append(f"{bid}: {role} is not cast on this job")
    for role, look in (beat.get("looks") or {}).items():
        kit = resolved.characters.get(role) or {}
        if role not in members:
            out.append(f"{bid}: names a look for {role}, who is not in the beat")
        elif look not in (kit.get("looks") or {}):
            out.append(f"{bid}: {role} has no look named {look}")
    return [*out, *_place_problems(resolved, beat), *_speaker_problems(beat, cast)]


def _place_problems(resolved: Resolved, beat: dict[str, Any]) -> list[str]:
    bid = beat.get("id", "?")
    out = []
    location = beat.get("location")
    if location and location not in resolved.named["locations"]:
        out.append(f"{bid}: no kit has the location {location}")
    for prop in beat.get("props") or []:
        if prop not in resolved.named["props"]:
            out.append(f"{bid}: no kit has the prop {prop}")
    return out


def _speaker_problems(beat: dict[str, Any], cast: list[str]) -> list[str]:
    bid = beat.get("id", "?")
    speaker = beat.get("speaker")
    if speaker and speaker not in cast:
        return [f"{bid}: speaker {speaker} is not cast on this job"]
    if not speaker and len(cast) > 1:
        return [f"{bid}: several people are cast, so the beat must name its speaker"]
    return []


def script_problems(resolved: Resolved, packet: dict[str, Any], cast: list[str]) -> list[str]:
    out = [p for beat in packet["beats"] for p in _beat_problems(resolved, beat, cast)]
    hooks = packet.get("hooks") or []
    if len(hooks) != 3:
        out.append(f"a stream piece carries three hooks, not {len(hooks)}")
    if not isinstance(packet.get("chosen_hook"), int) or not 0 <= packet["chosen_hook"] < len(
        hooks
    ):
        out.append("chosen_hook must point at one of the hooks")
    text = "\n".join(_script_text(packet)).lower()
    for role in cast:
        persona = resolved.characters[role].get("persona") or {}
        for banned in persona.get("never_say") or []:
            if str(banned).lower() in text:
                out.append(f"{role} would never say {banned!r}, and the script does")
    return out


def check_script(job: Job, resolved: Resolved, packet: dict[str, Any], cast: list[str]) -> None:
    bad = script_problems(resolved, packet, cast)
    if bad:
        raise ContractError(f"{job.id}: the script breaks its kits:\n  " + "\n  ".join(bad))


# ------------------------------------------------------------------- the shots
def _reference(resolved: Resolved, entry: dict[str, Any], label: str, group: str = "") -> Reference:
    return {
        "path": kits.blob_path(resolved.root, entry),
        "sha256": entry["sha256"],
        "label": label,
        "group": group,
    }


def _required_refs(resolved: Resolved, beat: dict[str, Any]) -> list[Reference]:
    out = []
    for role in beat.get("cast") or []:
        entry = resolved.characters[role]["identity"]["refs"][0]
        out.append(_reference(resolved, entry, f"{role}, the character", role))
    return out


def _wanted_refs(resolved: Resolved, beat: dict[str, Any]) -> list[Reference]:
    """Worth sending after the faces, most specific first: what the beat names, then the rest."""
    out = []
    for role, look in (beat.get("looks") or {}).items():
        for entry in resolved.characters[role]["looks"][look].get("refs") or []:
            out.append(_reference(resolved, entry, f"{role}, wearing {look}", role))
    location = beat.get("location")
    if location:
        for entry in resolved.named["locations"][location].get("refs") or []:
            out.append(_reference(resolved, entry, f"the location {location}"))
    for prop in beat.get("props") or []:
        for entry in resolved.named["props"][prop].get("refs") or []:
            out.append(_reference(resolved, entry, f"the prop {prop}"))
    for entry in (resolved.shared.get("style") or {}).get("refs") or []:
        out.append(_reference(resolved, entry, "the visual style"))
    for role in beat.get("cast") or []:
        for entry in resolved.characters[role]["identity"]["refs"][1:]:
            out.append(_reference(resolved, entry, f"{role}, another angle", role))
    return out


def shot_refs(
    resolved: Resolved, beat: dict[str, Any], capacity: int, *, start: Path | None = None
) -> list[Reference]:
    """References for one shot, within what the model takes. Refuses to drop a face to fit."""
    required = _required_refs(resolved, beat)
    if start:
        required.insert(0, {"path": start, "sha256": "", "label": "the start frame", "group": ""})
    if len(required) > capacity:
        raise ContractError(
            f"{beat.get('id')}: needs {len(required)} references and the model takes {capacity}"
        )
    return [*required, *_wanted_refs(resolved, beat)][:capacity]


def shot_prompt(resolved: Resolved, beat: dict[str, Any], fallback_style: str) -> str:
    """The cue plus the fixed text: who appears, how they look, the style, who may not appear."""
    parts = [str(beat.get("visual_cue") or beat["text"])]
    members = beat.get("cast") or []
    for role in members:
        description = (resolved.characters[role].get("identity") or {}).get("description")
        if description:
            parts.append(f"{role}: {description}")
    location = beat.get("location")
    if location and resolved.named["locations"][location].get("description"):
        parts.append(resolved.named["locations"][location]["description"])
    parts.append((resolved.shared.get("style") or {}).get("text") or fallback_style)
    if resolved.characters:
        parts.append(
            "The people shown are exactly the referenced characters, unchanged. No one else."
            if members
            else "No people in frame."
        )
    return ". ".join(p.rstrip(". ") for p in parts if p) + "."


def voice_for(resolved: Resolved, beat: dict[str, Any], cast: list[str]) -> dict[str, Any]:
    speaker = beat.get("speaker") or (cast[0] if len(cast) == 1 else None)
    if speaker and "voice" in resolved.characters[speaker]:
        return dict(resolved.characters[speaker]["voice"])
    if "voice" in resolved.shared:
        return dict(resolved.shared["voice"])
    raise ContractError(f"{beat.get('id')}: no locked voice for this beat")


def explain(resolved: Resolved) -> list[str]:
    """What is fixed on this stream right now, and how, for a person to read."""
    filled: dict[str, list[str]] = {}
    for role, kit in resolved.kits.items():
        for rule in RULES:
            if rule.slot in kit:
                filled.setdefault(rule.slot, []).append(
                    f"{role} ({kit['kit_id']}@{kit['version']})"
                )
    if resolved.canon:
        filled["canon"] = [f"{len(resolved.canon)} facts"]
    lines = ["what stays fixed, and how:"]
    for rule in RULES:
        owners = ", ".join(filled.get(rule.slot, [])) or "not fixed on this stream"
        lines.append(f"  {rule.slot:<10} {owners}")
        if rule.slot in filled:
            lines.append(f"  {'':<10} applied: {rule.applied}; checked: {rule.checked}")
    return lines


# ------------------------------------------------------------------------- QA
def _beats_with_cast(packet: dict[str, Any]) -> list[str]:
    return [b["id"] for b in packet["beats"] if b.get("cast")]


def _pin_problems(lock: dict[str, Any], assets: list[dict[str, Any]]) -> list[str]:
    out = []
    for asset in assets:
        kind = {"still": "image", "video": "video"}.get(asset.get("kind", ""))
        pin = (lock.get("generators") or {}).get(kind or "")
        uses_refs = (asset.get("provenance") or {}).get("kit_refs")
        if uses_refs and pin and asset.get("model") != pin["model"]:
            out.append(f"{asset['id']} came from {asset.get('model')}, not {pin['model']}")
    return out


def _voice_problems(
    resolved: Resolved, packet: dict[str, Any], lock: dict[str, Any], assets: list[dict[str, Any]]
) -> list[str]:
    voice_asset = next((a for a in assets if a.get("role") == "voice"), None)
    if voice_asset is None:
        return []
    used = ((voice_asset.get("provenance") or {}).get("kit_voices")) or {}
    out = []
    for beat in packet["beats"]:
        want = voice_for(resolved, beat, lock["cast"])
        if used.get(beat["id"]) != want["voice_id"]:
            out.append(f"{beat['id']} did not use the locked voice {want['voice_id']}")
    return out


def _music_problems(resolved: Resolved, assets: list[dict[str, Any]]) -> list[str]:
    out = []
    music = resolved.shared.get("music") or {}
    for key, asset_id in (("theme", "music"), ("whoosh", "whoosh")):
        if key not in music:
            continue
        asset = next((a for a in assets if a.get("id") == asset_id), None)
        if asset and (asset.get("provenance") or {}).get("kit_sha256") != music[key]["sha256"]:
            out.append(f"{asset_id} is not the {key} this kit fixes")
    return out


def recorded_checks(
    resolved: Resolved, lock: dict[str, Any], packet: dict[str, Any], manifest: dict[str, Any]
) -> list[dict[str, str]]:
    """Checks that need no model: the record proves the lock was applied."""
    assets = manifest["assets"]
    results = {}
    results["consistency.script"] = script_problems(resolved, packet, lock["cast"])
    results["consistency.generators"] = _pin_problems(lock, assets)
    results["consistency.voice"] = _voice_problems(resolved, packet, lock, assets)
    results["consistency.music"] = _music_problems(resolved, assets)
    missing = []
    by_id = {a["id"]: a for a in assets}
    for bid in _beats_with_cast(packet):
        for suffix in ("still", "video"):
            asset = by_id.get(f"{bid}.{suffix}")
            if asset and not (asset.get("provenance") or {}).get("kit_refs"):
                missing.append(f"{bid}.{suffix} was made with no reference files")
    results["consistency.references"] = missing
    return [
        {
            "id": check,
            "status": "fail" if bad else "pass",
            "detail": "; ".join(bad)[:500] or "held",
        }
        for check, bad in results.items()
    ]


def judge_images(resolved: Resolved, cast: list[str], *, per_character: int = 2) -> list[Path]:
    """What the vision judge compares the contact sheet with."""
    out = []
    for role in cast:
        for entry in resolved.characters[role]["identity"]["refs"][:per_character]:
            out.append(kits.blob_path(resolved.root, entry))
    return out


def judge_brief(resolved: Resolved, cast: list[str]) -> str:
    return planner_context(resolved, cast)


def judge_checks(verdict: dict[str, Any]) -> list[dict[str, str]]:
    """A clear 'no' from the judge fails the piece. An unclear answer warns the human."""
    out = []
    for key, check in (
        ("same_character", "consistency.character"),
        ("style_matches", "consistency.style"),
    ):
        value = verdict.get(key)
        status = "pass" if value is True else "fail" if value is False else "warn"
        out.append({"id": check, "status": status, "detail": f"judge: {key} = {value}"})
    resembles = verdict.get("resembles_real_person")
    out.append(
        {
            "id": "consistency.real_person",
            "status": "fail" if resembles is True else "warn" if resembles is None else "pass",
            "detail": f"judge: resembles_real_person = {resembles}. A human still makes this call",
        }
    )
    broken = verdict.get("script_breaks_kit") or []
    out.append(
        {
            "id": "consistency.persona_and_canon",
            "status": "fail" if broken else "pass",
            "detail": "; ".join(map(str, broken))[:500] or "judge: script fits the kit and canon",
        }
    )
    return out
