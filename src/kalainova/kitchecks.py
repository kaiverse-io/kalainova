"""What QA asks of a stream job: did the record keep what the lock promised, do the frames match?

The first half reads the record and needs no model. The second half gives a model the kit's own
reference images and reads back what it saw.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import kits
from .consistency import Resolved, planner_context, script_problems, voice_for


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
