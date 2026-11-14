"""Opening variants that reuse a parent's rendered body and source assets."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .jobfs import ContractError, Job, open_child


def _share_assets(parent: Job, child: Job, manifest: dict[str, Any]) -> None:
    """Hard-link source files into the child work folder while keeping manifest paths stable."""
    for asset in manifest.get("assets", []):
        name = asset.get("path")
        if not isinstance(name, str):
            continue
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts:
            continue
        source = parent.work / rel
        destination = child.work / rel
        if not source.is_file() or destination.exists():
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)


def _hook_card(overlays: list[dict[str, Any]], duration: float) -> dict[str, Any]:
    for overlay in overlays:
        if overlay.get("kind") == "hook_card":
            return overlay
    card = {
        "kind": "hook_card",
        "start_sec": 0,
        "end_sec": min(1.6, duration) if duration > 0 else 1.6,
        "text": "",
    }
    overlays.insert(0, card)
    return card


def open_variant(
    parent: Job,
    new_id: str,
    *,
    opening_text: str | None = None,
    opening_shot: str | None = None,
    opening_card: dict[str, Any] | None = None,
    title: str | None = None,
) -> Job:
    """Open a child job with a changed opening and the parent's body assets and edit."""
    missing = [name for name in ("edit_manifest", "asset_manifest") if not parent.has(name)]
    if missing:
        raise ContractError(f"{parent.id}: opening variants need {', '.join(missing)}")

    parent_em = parent.read("edit_manifest")
    parent_am = parent.read("asset_manifest")
    if opening_shot is not None and not parent_em.get("cuts"):
        raise ContractError(f"{parent.id}: edit_manifest has no opening cut to replace")
    brief = {
        **parent.job.get("brief", {}),
        "variant_of": parent.id,
        "variant_type": "opening",
    }
    child = open_child(
        parent,
        new_id,
        profile=parent.job.get("profile") or "square",
        brief=brief,
    )

    child_am = {**parent_am, "job_id": child.id}
    child_em = {**parent_em, "job_id": child.id}
    cuts = child_em.setdefault("cuts", [])
    if opening_shot is not None:
        cuts[0] = {**cuts[0], "source": opening_shot}

    overlays = child_em.setdefault("overlays", [])
    if opening_text is not None:
        _hook_card(overlays, float(child_em.get("duration_sec", 0)))["text"] = opening_text
    if opening_card is not None:
        card = dict(opening_card)
        existing = next(
            (i for i, overlay in enumerate(overlays) if overlay.get("kind") == "hook_card"),
            None,
        )
        if existing is None:
            overlays.insert(0, card)
        else:
            overlays[existing] = card

    if title is not None and isinstance(child_em.get("brief"), dict):
        child_em["brief"]["title"] = title

    _share_assets(parent, child, child_am)
    child.write("asset_manifest", child_am)
    child.write("edit_manifest", child_em)
    if parent.has("script_packet"):
        packet = {**parent.read("script_packet"), "job_id": child.id}
        child.write("script_packet", packet)
    return child
