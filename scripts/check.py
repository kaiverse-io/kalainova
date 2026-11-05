#!/usr/bin/env python3
"""Gates. Stdlib only.

  python3 scripts/check.py                 the repo: no media blobs in git, every job folder honours the contract
  python3 scripts/check.py --jobs DIR      the same rules over another jobs directory
  python3 scripts/check.py --fixtures DIR  contract eval: every fixture under DIR/pass must pass, every
                                           fixture under DIR/fail must fail with the text in its expect.txt

The gate cannot tell you a piece is good, true, paid, or published. It rejects malformed shape.
"""

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
    "client",
    "procedural",
    "audio-native",
    "text-pack",
    "downstream-sku",
}
EXTENSIONS_AFTER_PROOF = {"procedural", "downstream-sku"}
KINDS = {"video", "audio", "still", "text"}
RIGHTS = {"funded-brief", "owned", "licensed"}
RIGHTS_FOR = {"funded-clip": {"funded-brief"}, "owned-derivative": {"owned", "licensed"}, "client": {"licensed"}}
STATUSES = {"template", "draft", "rented", "rendered", "approved", "published", "accepted", "measured", "killed"}
PROVEN = {"accepted", "measured"}
FORMATS = {"list", "comparison", "countdown", "alert", "poll", "recap", "quote", "stat"}
OPS = {"cut", "concat", "scale", "overlay_text", "mix_audio", "loudnorm", "burn_captions", "export"}
ROLES = {"hook", "body", "payoff", "cta"}
CUT_ROLES = ROLES | {"bed", "other"}
LOCAL_MODELS = {"local-studio-field", "local-pad", "local-whoosh", "local-typecard"}
CONTRACT = {
    "job.json": "job",
    "script_packet.json": "script_packet",
    "asset_manifest.json": "asset_manifest",
    "edit_manifest.json": "edit_manifest",
    "render_plan.json": "render_plan",
    "measure.json": "measure",
    "qa.json": "qa",
    "approval.json": "approval",
    "publish_log.json": "publish_log",
    "footage.json": "footage",
    "direction.json": "direction",
}

errors: list[str] = []


def fail(msg: str) -> None:
    errors.append(msg)


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"{rel(path)}: invalid json ({exc})")
        return {}
    if not isinstance(data, dict):
        fail(f"{rel(path)}: expected an object")
        return {}
    return data


def schema_keys(name: str) -> tuple[set[str], set[str]]:
    """(allowed top-level keys, required keys) from schemas/<name>.schema.json, which stays the source of truth."""
    schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
    return set(schema.get("properties", {})), set(schema.get("required", []))


def shape(data: dict, name: str, path: Path) -> None:
    allowed, required = schema_keys(name)
    for key in sorted(required - set(data)):
        fail(f"{rel(path)}: missing {key}")
    for key in sorted(set(data) - allowed):
        fail(f"{rel(path)}: unknown key {key!r}")
    if "schema_version" in data and data["schema_version"] != "0.1":
        fail(f"{rel(path)}: schema_version must be 0.1")


# ------------------------------------------------------------------ media
def tracked_paths() -> list[str] | None:
    try:
        out = subprocess.check_output(["git", "ls-files"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL)
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    return [line for line in out.splitlines() if line]


def check_media(paths: list[str] | None) -> None:
    if paths is None:
        print("note: not a git checkout; media check skipped", file=sys.stderr)
        return
    bad = [p for p in paths if Path(p).suffix.lower() in MEDIA]
    if bad:
        fail("media blobs must stay out of git:\n" + "\n".join(bad))


# ------------------------------------------------------------------ one job
def check_job(path: Path, data: dict, any_proven: bool) -> None:
    shape(data, "job", path)
    folder = path.parent.name
    if data.get("job_id") != folder:
        fail(f"{rel(path)}: job_id {data.get('job_id')!r} must equal its folder name {folder!r}")
    strategy = data.get("strategy")
    if strategy not in STRATEGIES:
        fail(f"{rel(path)}: unknown strategy {strategy!r}")
    media = data.get("media")
    if not isinstance(media, list) or not media or any(k not in KINDS for k in media):
        fail(f"{rel(path)}: media must be a non-empty subset of {sorted(KINDS)}")
        media = []
    rights = data.get("rights")
    if rights not in RIGHTS:
        fail(f"{rel(path)}: rights must be one of {sorted(RIGHTS)}")
    status = data.get("status")
    if status not in STATUSES:
        fail(f"{rel(path)}: unknown status {status!r}")
    if status == "template":
        if data.get("job_id") != "_template":
            fail(f"{rel(path)}: only jobs/_template may use status template")
        return
    if folder == "_template":
        fail(f"{rel(path)}: the template keeps status template")
    if not data.get("distribution_identity"):
        fail(f"{rel(path)}: distribution_identity is required once the job leaves the template")
    allowed = RIGHTS_FOR.get(strategy)
    if allowed and rights not in allowed:
        fail(f"{rel(path)}: {strategy} needs rights in {sorted(allowed)}, got {rights!r}")
    if data.get("skip_funded") and strategy != "generated":
        fail(f"{rel(path)}: skip_funded applies to generated jobs only")
    if strategy == "generated" and status != "draft" and data.get("cost_cap") is None:
        fail(f"{rel(path)}: generated jobs write cost_cap before the first render")
    if strategy == "procedural" and data.get("format") not in FORMATS:
        fail(f"{rel(path)}: procedural jobs need a format")
    if strategy == "audio-native" and "audio" not in media:
        fail(f"{rel(path)}: audio-native jobs include audio")
    if strategy == "text-pack" and media != ["text"]:
        fail(f"{rel(path)}: text-pack media is exactly ['text']")
    if strategy == "downstream-sku" and not data.get("parent_job_id"):
        fail(f"{rel(path)}: downstream-sku needs parent_job_id")
    if strategy in EXTENSIONS_AFTER_PROOF and not any_proven:
        fail(f"{rel(path)}: {strategy} is an extension; it waits until one job is accepted or measured")
    if "format" in data and data["format"] not in FORMATS:
        fail(f"{rel(path)}: unknown format")
    if status in PROVEN and not (path.parent / "measure.json").exists():
        fail(f"{rel(path)}: status {status} needs measure.json")
    for st, files in {"approved": ["qa.json", "approval.json"], "published": ["qa.json", "approval.json", "publish_log.json"]}.items():
        if status == st:
            for name in files:
                if not (path.parent / name).exists():
                    fail(f"{rel(path)}: status {st} needs {name}")


def check_script(path: Path, data: dict) -> None:
    shape(data, "script_packet", path)
    beats = data.get("beats")
    if not isinstance(beats, list) or not beats:
        fail(f"{rel(path)}: beats must be a non-empty list")
        beats = []
    for beat in beats:
        if not isinstance(beat, dict):
            fail(f"{rel(path)}: beat is not an object")
            continue
        if beat.get("role") not in ROLES:
            fail(f"{rel(path)}: beat role {beat.get('role')!r}")
        if not beat.get("text"):
            fail(f"{rel(path)}: beat missing text")
    for claim in data.get("claims") or []:
        if not isinstance(claim, dict) or not claim.get("source"):
            fail(f"{rel(path)}: claim missing source")


def check_assets(path: Path, data: dict) -> None:
    shape(data, "asset_manifest", path)
    assets = data.get("assets")
    if not isinstance(assets, list) or not assets:
        fail(f"{rel(path)}: assets must be a non-empty list")
        assets = []
    for asset in assets:
        if not isinstance(asset, dict):
            fail(f"{rel(path)}: asset is not an object")
            continue
        if asset.get("kind") not in KINDS:
            fail(f"{rel(path)}: asset kind {asset.get('kind')!r}")
        if not asset.get("path"):
            fail(f"{rel(path)}: asset missing path")
        if "rights" in asset and asset["rights"] not in RIGHTS:
            fail(f"{rel(path)}: asset rights {asset['rights']!r}")


def _num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_edit(path: Path, data: dict) -> None:
    shape(data, "edit_manifest", path)
    if data.get("runtime") not in {"rented-tool", "ffmpeg", "remotion"}:
        fail(f"{rel(path)}: runtime must be rented-tool, ffmpeg, or remotion")
    cuts = data.get("cuts") or []
    if not isinstance(cuts, list):
        fail(f"{rel(path)}: cuts must be a list")
        cuts = []
    for cut in cuts:
        if not isinstance(cut, dict):
            fail(f"{rel(path)}: cut is not an object")
            continue
        if "role" in cut and cut["role"] not in CUT_ROLES:
            fail(f"{rel(path)}: cut role {cut['role']!r}")
        a, b = cut.get("in_sec"), cut.get("out_sec")
        if not (_num(a) and _num(b)):
            fail(f"{rel(path)}: cut {cut.get('id')!r} needs numeric in_sec and out_sec")
        elif b <= a:
            fail(f"{rel(path)}: cut {cut.get('id')!r} ends before it starts")


def check_render(path: Path, data: dict, any_proven: bool) -> None:
    """ADR 0007: the owned ffmpeg compiler exists, so a render plan is legal when it was compiled from an
    ffmpeg edit manifest in the same job. A plan for a rented-tool job still means a compiler snuck in."""
    shape(data, "render_plan", path)
    em = path.parent / "edit_manifest.json"
    runtime = (json.loads(em.read_text()).get("runtime") if em.exists() else None)
    if runtime != "ffmpeg":
        fail(f"{rel(path)}: a render plan needs an edit_manifest with runtime ffmpeg (the owned compiler, ADR 0007)")
    steps = data.get("steps")
    if not isinstance(steps, list) or not steps:
        fail(f"{rel(path)}: steps must be a non-empty list")
        steps = []
    for step in steps:
        if not isinstance(step, dict) or step.get("op") not in OPS:
            fail(f"{rel(path)}: op must be one of {sorted(OPS)}")


def check_measure(path: Path, data: dict) -> None:
    shape(data, "measure", path)


def check_approval(path: Path, data: dict) -> None:
    """An approval binds to the exact bytes QA passed."""
    shape(data, "approval", path)
    qa_path = path.parent / "qa.json"
    if not qa_path.exists():
        fail(f"{rel(path)}: approval without qa.json")
        return
    qa = load(qa_path)
    if qa.get("passed") is not True:
        fail(f"{rel(path)}: approval exists but qa.json did not pass")
    checked = (qa.get("artifacts_sha256") or {}).get("video")
    if checked != data.get("artifact_sha256"):
        fail(f"{rel(path)}: approved sha256 is not the file QA checked")
    manifest_path = path.parent / "asset_manifest.json"
    if not manifest_path.exists():
        fail(f"{rel(path)}: approval without asset_manifest.json")
        return
    assets = load(manifest_path).get("assets")
    local = [a.get("id", "?") for a in (assets if isinstance(assets, list) else []) if isinstance(a, dict) and (
        a.get("provider") == "local" or a.get("model") in LOCAL_MODELS or str(a.get("model", "")).startswith("flite-"))]
    if local:
        fail(f"{rel(path)}: approval of a placeholder; the local provider made {local}")


# ------------------------------------------------------------------ a jobs tree
def check_tree(jobs_root: Path) -> None:
    folders = sorted(p.parent for p in jobs_root.glob("*/job.json"))
    if not folders:
        fail(f"no jobs found under {rel(jobs_root)}")
        return
    jobs = {f: load(f / "job.json") for f in folders}
    any_proven = any(j.get("status") in PROVEN for j in jobs.values())
    identities: dict[str, set[str]] = {}
    for folder, job in jobs.items():
        if not job:
            continue
        check_job(folder / "job.json", job, any_proven)
        if job.get("status") != "template" and job.get("distribution_identity"):
            identities.setdefault(job["distribution_identity"], set()).add(job.get("strategy"))
        for name, kind in CONTRACT.items():
            path = folder / name
            if kind == "job" or not path.exists():
                continue
            data = load(path)
            if not data:
                continue
            if data.get("job_id") not in (None, folder.name):
                fail(f"{rel(path)}: job_id {data.get('job_id')!r} must equal its folder name {folder.name!r}")
            if kind == "script_packet":
                check_script(path, data)
            elif kind == "asset_manifest":
                check_assets(path, data)
            elif kind == "edit_manifest":
                check_edit(path, data)
            elif kind == "render_plan":
                check_render(path, data, any_proven)
            elif kind == "measure":
                check_measure(path, data)
            elif kind == "approval":
                check_approval(path, data)
            elif kind in ("qa", "publish_log", "footage", "direction"):
                shape(data, kind, path)
    for ident, strategies in sorted(identities.items()):
        if len(strategies) > 1:
            fail(f"distribution_identity {ident!r} is used by {sorted(strategies)}; one identity per strategy")


# ------------------------------------------------------------------ contract eval
def run_fixtures(root: Path) -> int:
    """Each fixture is a jobs tree. Optional tracked.txt lists paths treated as git-tracked."""
    global errors
    results, bad = [], 0
    cases = sorted(p for p in (root / "pass").glob("*") if p.is_dir()) + sorted(p for p in (root / "fail").glob("*") if p.is_dir())
    if not cases:
        print(f"no fixtures under {root}", file=sys.stderr)
        return 1
    for case in cases:
        errors = []
        tracked = case / "tracked.txt"
        if tracked.exists():
            check_media([l.strip() for l in tracked.read_text().splitlines() if l.strip()])
        check_tree(case / "jobs")
        should_fail = case.parent.name == "fail"
        expect = (case / "expect.txt").read_text().strip() if (case / "expect.txt").exists() else ""
        if should_fail:
            ok = bool(errors) and (not expect or any(expect in e for e in errors))
        else:
            ok = not errors
        bad += not ok
        results.append(f"  {'ok  ' if ok else 'FAIL'} {case.parent.name}/{case.name}"
                       + ("" if ok else f"\n       expected {'failure containing ' + repr(expect) if should_fail else 'pass'}, got: {errors or 'no errors'}"))
    print("\n".join(results))
    print(f"fixtures: {len(cases) - bad}/{len(cases)} ok")
    return 1 if bad else 0


def main(argv: list[str]) -> int:
    if len(argv) >= 3 and argv[1] == "--fixtures":
        return run_fixtures(Path(argv[2]).resolve())
    jobs_root = Path(argv[2]).resolve() if len(argv) >= 3 and argv[1] == "--jobs" else ROOT / "jobs"
    check_media(tracked_paths())
    check_tree(jobs_root)
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("check ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
