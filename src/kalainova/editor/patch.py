"""Patch a single cut in an existing edit_manifest without re-directing the whole piece."""

from __future__ import annotations

import datetime as dt
import json
from typing import Any

from ..jobfs import ContractError, Job


def patch_cut(
    job: Job,
    cut_index: int,
    *,
    source: str | None = None,
    in_sec: float | None = None,
    title: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    if not job.has("edit_manifest"):
        raise ContractError(f"{job.id}: missing edit_manifest.json; run the earlier stage first")
    em = job.read("edit_manifest")
    cuts = em.get("cuts", [])
    if not (0 <= cut_index < len(cuts)):
        raise ContractError(f"{job.id}: cut_index {cut_index} out of bounds for {len(cuts)} cuts")

    if source is not None:
        am = job.read("asset_manifest")
        asset_ids = {a["id"] for a in am.get("assets", [])}
        if source not in asset_ids:
            raise ContractError(f"source {source!r} not in asset_manifest")
        cuts[cut_index]["source"] = source

    if in_sec is not None:
        cuts[cut_index]["in_sec"] = float(in_sec)

    if title is not None:
        cuts[cut_index]["title"] = title

    approval = job.folder / "approval.json"
    approval_voided = approval.exists()
    if approval_voided:
        approval.unlink(missing_ok=True)

    direction_path = job.folder / "direction.json"
    if direction_path.exists():
        direction = json.loads(direction_path.read_text())
        direction.setdefault("notes", []).append(
            {
                "at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                "text": f"patch cut {cut_index}: {note or 'manual patch'}",
            }
        )
        direction_path.write_text(json.dumps(direction, indent=2, ensure_ascii=False) + "\n")

    job.write("edit_manifest", em)
    return {
        "job_id": job.id,
        "cut_index": cut_index,
        "cut": cuts[cut_index],
        "approval_voided": approval_voided,
    }
