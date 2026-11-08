"""How a piece was made, on one page: what a person answering for it needs to hand over.

For each asset: which model made it, which exact weights, which seed, what its terms ask, and its
hash.
For the piece: what people decided, what it cost, and the file that was approved. In the US, prompts
alone do not make someone the author of a model's output, while human selection and arrangement can
count, so this record keeps what people did alongside what the models did. It is a record, not legal
advice, and a person reads the terms before release.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from . import config, takes, verdicts
from .blobstore import sha256_file
from .jobfs import Job

REPORT = "provenance.json"
_NO_MODEL = {"operator", "kit", "chained", "clip", "track"}


def _terms(provider: str, model: str) -> dict[str, Any]:
    """What a model's terms ask. A file with no model behind it has none to read."""
    if not provider or provider in _NO_MODEL:
        return {}
    found = config.licence_for(provider, model.split(":")[0])
    if not found:
        return {"licence": "unknown: nobody has read these terms"}
    return {
        "licence": found.get("name"),
        "commercial_use": found.get("commercial"),
        "obligations": list(found.get("obligations") or []),
    }


def _how_it_was_made(asset: dict[str, Any]) -> dict[str, Any]:
    made = dict(asset.get("provenance") or {})
    line = {k: made[k] for k in ("seed", "weights_revision", "audio_format", "take") if k in made}
    if asset.get("prompt"):
        line["prompt"] = asset["prompt"]
    if asset.get("sha256") or made.get("sha256"):
        line["sha256"] = asset.get("sha256") or made["sha256"]
    return line


def _asset_line(asset: dict[str, Any]) -> dict[str, Any]:
    provider = str(asset.get("provider") or "")
    model = str(asset.get("model") or "")
    return {
        "id": asset["id"],
        "kind": asset["kind"],
        "provider": provider,
        "model": model,
        "rights_stated": asset.get("rights"),
        "synthetic": bool(asset.get("synthetic")),
        **_how_it_was_made(asset),
        **_terms(provider, model),
    }


def _human_decisions(job: Job) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    direction = job.folder / "direction.json"
    if direction.exists():
        for note in json.loads(direction.read_text()).get("notes") or []:
            out.append({"kind": "direction", "at": note.get("at"), "text": note.get("text")})
    for entry in verdicts.load(job.folder):
        out.append({"kind": "verdict", **entry})
    data = takes.load(job)
    for shot, entry in data["shots"].items():
        if entry.get("chosen_by") == "human":
            out.append({"kind": "chose a take", "shot": shot, "take": entry["chosen"]})
    if job.has("approval"):
        approval = job.read("approval")
        out.append(
            {"kind": "approval", "reviewer": approval["reviewer"], "at": approval["approved_at"]}
        )
    return out


def _files(job: Job) -> dict[str, str]:
    work: Path = job.work
    out = {}
    for name in (job.artifact().name, "final.master.mov", "final.epub"):
        path = work / name
        if path.exists():
            out[name] = sha256_file(path)
    return out


def _ledger(job: Job) -> dict[str, Any]:
    entries = json.loads(job.ledger_path.read_text()) if job.ledger_path.exists() else []
    by_provider: dict[str, float] = {}
    for entry in entries:
        name = str(entry.get("provider"))
        by_provider[name] = round(by_provider.get(name, 0.0) + float(entry.get("cost", 0.0)), 6)
    return {"total_estimated": round(job.spent(), 6), "by_provider": by_provider}


def report(job: Job) -> dict[str, Any]:
    """Everything the record holds about how this piece was made."""
    manifest = job.read("asset_manifest")
    lines = [_asset_line(a) for a in manifest["assets"]]
    data = job.job
    owed = sorted({o for line in lines for o in line.get("obligations", [])})
    return {
        "job_id": job.id,
        "written_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "rights_stated_on_job": data.get("rights"),
        "synthetic_disclosure": data.get("synthetic_disclosure", True),
        "files": _files(job),
        "assets": lines,
        "obligations": owed,
        "unknown_licences": [
            a["id"] for a in lines if str(a.get("licence", "")).startswith("unknown")
        ],
        "human_decisions": _human_decisions(job),
        "ledger": _ledger(job),
        "takes": {shot: len(entry["takes"]) for shot, entry in takes.load(job)["shots"].items()},
    }


def write(job: Job) -> Path:
    path = job.folder / REPORT
    path.write_text(json.dumps(report(job), indent=2, ensure_ascii=False) + "\n")
    return path
