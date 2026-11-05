#!/usr/bin/env python3
"""Gates: no media blobs in git, every job.json matches the engine contract."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MEDIA = {".mp3", ".mp4", ".wav", ".m4a", ".mov", ".webm"}
STRATEGIES = {
    "funded-clip",
    "owned-derivative",
    "generated",
    "procedural",
    "audio-native",
    "text-pack",
    "downstream-sku",
}
KINDS = {"video", "audio", "still", "text"}
RIGHTS = {"funded-brief", "owned", "licensed"}
STATUSES = {"template", "draft", "rented", "rendered", "accepted", "measured", "killed"}
FORMATS = {"list", "comparison", "countdown", "alert", "poll", "recap", "quote", "stat"}
OPS = {"cut", "concat", "scale", "overlay_text", "mix_audio", "loudnorm", "burn_captions", "export"}
ROLES = {"hook", "body", "payoff", "cta"}
CUT_ROLES = ROLES | {"bed", "other"}

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"{path}: invalid json ({exc})")
        return {}
    if not isinstance(data, dict):
        fail(f"{path}: expected an object")
        return {}
    return data


def tracked_paths() -> list[str]:
    try:
        out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [line for line in out.splitlines() if line]


def check_media() -> None:
    paths = tracked_paths()
    if not paths:
        return
    bad = [p for p in paths if Path(p).suffix.lower() in MEDIA]
    if bad:
        fail("media blobs must stay out of git:\n" + "\n".join(bad))


def require(data: dict, key: str, path: Path) -> None:
    if key not in data:
        fail(f"{path}: missing {key}")


def check_job(path: Path) -> None:
    data = load(path)
    if not data:
        return
    for key in ("schema_version", "job_id", "strategy", "media", "rights", "status"):
        require(data, key, path)
    if data.get("schema_version") != "0.1":
        fail(f"{path}: schema_version must be 0.1")
    if data.get("strategy") not in STRATEGIES:
        fail(f"{path}: unknown strategy {data.get('strategy')!r}")
    media = data.get("media")
    if not isinstance(media, list) or not media or any(k not in KINDS for k in media):
        fail(f"{path}: media must be a non-empty subset of {sorted(KINDS)}")
    if data.get("rights") not in RIGHTS:
        fail(f"{path}: rights must be one of {sorted(RIGHTS)}")
    status = data.get("status")
    if status not in STATUSES:
        fail(f"{path}: unknown status {status!r}")
    identity = data.get("distribution_identity", None)
    if status != "template" and not identity:
        fail(f"{path}: distribution_identity is required once the job leaves the template")
    if status == "template" and data.get("job_id") != "_template":
        fail(f"{path}: only jobs/_template may use status template")
    if data.get("strategy") == "procedural" and status != "template":
        if data.get("format") not in FORMATS:
            fail(f"{path}: procedural jobs need a format")
    if data.get("strategy") == "audio-native" and status != "template":
        if media and "audio" not in media:
            fail(f"{path}: audio-native jobs include audio")
    if data.get("strategy") == "text-pack" and status != "template":
        if media != ["text"]:
            fail(f"{path}: text-pack media is exactly ['text']")
    if data.get("strategy") == "downstream-sku" and status != "template":
        if not data.get("parent_job_id"):
            fail(f"{path}: downstream-sku needs parent_job_id")
    if data.get("format") not in (None, *FORMATS) and "format" in data:
        fail(f"{path}: unknown format")


def check_script(path: Path) -> None:
    data = load(path)
    if not data:
        return
    require(data, "beats", path)
    beats = data.get("beats") or []
    if not beats:
        fail(f"{path}: beats must not be empty")
    for beat in beats:
        if not isinstance(beat, dict):
            fail(f"{path}: beat is not an object")
            continue
        if beat.get("role") not in ROLES:
            fail(f"{path}: beat role {beat.get('role')!r}")
        if not beat.get("text"):
            fail(f"{path}: beat missing text")
    for claim in data.get("claims") or []:
        if not isinstance(claim, dict) or not claim.get("source"):
            fail(f"{path}: claim missing source")


def check_assets(path: Path) -> None:
    data = load(path)
    if not data:
        return
    assets = data.get("assets") or []
    if not assets:
        fail(f"{path}: assets must not be empty")
    for asset in assets:
        if not isinstance(asset, dict):
            fail(f"{path}: asset is not an object")
            continue
        if asset.get("kind") not in KINDS:
            fail(f"{path}: asset kind {asset.get('kind')!r}")
        if not asset.get("path"):
            fail(f"{path}: asset missing path")


def check_edit(path: Path) -> None:
    data = load(path)
    if not data:
        return
    if data.get("runtime") not in {"rented-tool", "ffmpeg", "remotion"}:
        fail(f"{path}: runtime")
    for cut in data.get("cuts") or []:
        if cut.get("role") not in CUT_ROLES:
            fail(f"{path}: cut role {cut.get('role')!r}")
        if cut.get("out_sec", 0) < cut.get("in_sec", 0):
            fail(f"{path}: cut {cut.get('id')} ends before it starts")


def check_render(path: Path) -> None:
    data = load(path)
    if not data:
        return
    steps = data.get("steps") or []
    if not steps:
        fail(f"{path}: steps must not be empty")
    for step in steps:
        if not isinstance(step, dict) or step.get("op") not in OPS:
            fail(f"{path}: op must be one of {sorted(OPS)}")


def check_measure(path: Path) -> None:
    data = load(path)
    if not data:
        return
    require(data, "job_id", path)


def main() -> int:
    check_media()
    jobs = sorted((ROOT / "jobs").glob("*/job.json"))
    if not jobs:
        fail("no jobs found")
    for path in jobs:
        check_job(path)
        folder = path.parent
        if (folder / "script_packet.json").exists():
            check_script(folder / "script_packet.json")
        if (folder / "asset_manifest.json").exists():
            check_assets(folder / "asset_manifest.json")
        if (folder / "edit_manifest.json").exists():
            check_edit(folder / "edit_manifest.json")
        if (folder / "render_plan.json").exists():
            check_render(folder / "render_plan.json")
        if (folder / "measure.json").exists():
            check_measure(folder / "measure.json")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("check ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
