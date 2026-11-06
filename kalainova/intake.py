"""INTAKE. A finished file from an outside tool enters the job, with a record of how it was made.

The record is the tool's own report, so it is not proof. It still has to name the provider, model, and
rights for every asset, and the same gates apply afterward: QA, the placeholder refusal, a human approval.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from . import media, render
from .jobfs import AUDIO_SUFFIXES, ContractError, Job


def _destination(job: Job, source: Path) -> Path:
    suffix = source.suffix.lower()
    if "video" in job.job.get("media", []):
        if suffix != ".mp4":
            raise ContractError(f"{job.id}: this job makes video, so intake needs an .mp4, got {source.name}")
    elif suffix not in AUDIO_SUFFIXES:
        raise ContractError(f"{job.id}: this job makes audio, so intake needs one of {AUDIO_SUFFIXES}, got {source.name}")
    return job.work / f"final{suffix}"


def run(job: Job, source: Path, record: dict) -> Path:
    if not source.is_file():
        raise ContractError(f"{job.id}: no file at {source}")
    dst = _destination(job, source)
    if media.duration(source) <= 0:
        raise ContractError(f"{job.id}: {source.name} has no duration")
    assets = record.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ContractError(f"{job.id}: the intake record needs a non-empty assets list")
    for asset in assets:
        missing = [k for k in ("id", "kind", "path", "provider", "model", "rights") if not asset.get(k)]
        if missing:
            raise ContractError(f"{job.id}: asset {asset.get('id', '?')} in the intake record is missing {missing}")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    previous = job.read_stamp() or {}
    job.write("asset_manifest", {"schema_version": "0.1", "job_id": job.id, "assets": assets})
    if dst.resolve() != source.resolve():
        shutil.copyfile(source, dst)
    render.stamp(job, dst)
    if previous.get("artifact_sha256") != sha:  # taking in the same file twice must not charge twice
        for asset in assets:
            job.charge(asset["provider"], asset["kind"], float(asset.get("cost", 0)), f"intake: {asset['id']}")
    job.set_status("rendered")
    return dst
