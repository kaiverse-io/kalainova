"""GATE -> PUBLISH -> MEASURE.

approve()  a human records approval. Bound to the exact bytes (sha256) that passed QA.
publish()  posts approved bytes through an official API or aggregator. Refuses if the
           file changed after approval, if QA failed, or if no approval exists.
measure()  pulls platform metrics into measure.json.

Agents may call publish() only after a human-written approval.json exists. The
approval is the gate; the posting itself can be automatic.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

import requests

from .. import config, consistency, preproduction, streams
from ..blobstore import sha256_file
from ..jobfs import ContractError, Job
from ..providers import base as providers
from . import labels
from .aggregator import upload_post as _upload_post


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _qa_bound(job: Job, final: Path) -> dict:
    """QA must have passed on exactly these bytes."""
    qa = job.read("qa")
    if not qa.get("passed"):
        failing = [c["id"] for c in qa["checks"] if c["status"] == "fail"]
        raise ContractError(f"{job.id}: QA failed ({failing}); fix and re-render before approval")
    hashes = qa.get("artifacts_sha256") or {}
    checked = hashes.get("video") or hashes.get("audio") or hashes.get("document")
    if not checked or checked != sha256_file(final):
        raise ContractError(f"{job.id}: {final.name} is not the file QA checked; run qa again")
    _master_bound(job, final, hashes)
    return qa


def _master_bound(job: Job, final: Path, hashes: dict) -> None:
    """The delivery master is what a platform ingests, so it is held to the same rule."""
    master = final.with_name("final.master.mov")
    checked = hashes.get("master")
    if checked is None and master.exists():
        raise ContractError(f"{job.id}: {master.name} exists and QA never checked it; run qa again")
    if checked is None:
        return
    if not master.exists() or sha256_file(master) != checked:
        raise ContractError(f"{job.id}: {master.name} is not the master QA checked; run qa again")


CAPTION_LIMITS = {
    "youtube": 4900,
    "instagram": 2200,
    "tiktok": 2200,
    "facebook": 5000,
    "x": 280,
    "linkedin": 3000,
    "threads": 500,
}

# The local provider says it is not the quality bar. QA may pass its output for CI; a human cannot approve it.
LOCAL_MODELS = {"local-studio-field", "local-pad", "local-whoosh", "local-typecard"}


def placeholder_assets(manifest: dict) -> list[str]:
    """Ids of the assets the local provider made."""
    return [
        a.get("id", "?")
        for a in manifest.get("assets", [])
        if a.get("provider") == "local"
        or a.get("model") in LOCAL_MODELS
        or str(a.get("model", "")).startswith("flite-")
    ]


# Provenance labels for files that no model made. They have no generation row and no licence row.
_NOT_A_MODEL = {"operator", "kit", "chained", "clip", "track"}


def _is_placeholder_provider(name: str) -> bool:
    """The provider class says its output is not a result, whatever the model string claims."""
    try:
        return bool(providers.get(name).placeholder)
    except KeyError:
        return False


def _generation_rows(job: Job) -> list[dict]:
    """The router's own record. A row labelled as intake was supplied by a caller, so it is no proof."""
    path = job.folder / "generations.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    return [r for r in rows if r.get("source") != "intake" and not r.get("meta", {}).get("intake")]


def _made_by_models(job: Job, manifest: dict) -> None:
    """The manifest may not name a provider or model the router never called, or one whose terms
    forbid commercial use. A draft job (brief.draft) may carry the second."""
    draft = bool((job.job.get("brief") or {}).get("draft"))
    rows = _generation_rows(job) if (job.folder / "generations.jsonl").exists() else None
    unbacked: list[str] = []
    limited: list[str] = []
    for asset in manifest.get("assets", []):
        provider = str(asset.get("provider") or "")
        if not provider or provider in _NOT_A_MODEL:
            continue
        if _is_placeholder_provider(provider):
            raise ContractError(
                f"{job.id}: placeholder; {provider} made {asset.get('id', '?')}. "
                "Render again with the paid models"
            )
        model = str(asset.get("model") or "")
        if rows is not None and not any(
            r.get("provider") == provider
            and str(r.get("model", "")).split(":")[0] == model.split(":")[0]
            for r in rows
        ):
            unbacked.append(f"{asset.get('id', '?')} ({provider}/{model})")
        if config.licence_for(provider, model.split(":")[0]).get("commercial") is False:
            limited.append(f"{asset.get('id', '?')} ({provider}/{model})")
    if unbacked:
        raise ContractError(
            f"{job.id}: the manifest names models the router never called: {unbacked}. "
            "Render again, or take the file in with intake and mark it so"
        )
    if limited and not draft:
        raise ContractError(
            f"{job.id}: terms do not allow commercial use of {limited}; "
            "use another model, or set brief.draft for a piece that will not be released"
        )


def _not_placeholder(job: Job) -> None:
    if not job.has("asset_manifest"):
        raise ContractError(
            f"{job.id}: no asset_manifest.json, so nothing shows who made the picture, voice, or music"
        )
    local = placeholder_assets(job.read("asset_manifest"))
    if local:
        raise ContractError(
            f"{job.id}: placeholder; the local provider made {local}. Render again with the paid models"
        )
    _made_by_models(job, job.read("asset_manifest"))
    made_from = job.read_stamp()
    final = job.artifact()
    if (
        not made_from
        or made_from.get("artifact_sha256") != sha256_file(final)
        or made_from.get("asset_manifest_sha256") != sha256_file(job.path("asset_manifest"))
    ):
        raise ContractError(
            f"{job.id}: {final.name} was not rendered from this asset_manifest.json; render again"
        )
    allowed = (job.job.get("brief") or {}).get("allow_stills")
    if job.read("asset_manifest").get("promise_breaks") and not allowed:
        raise ContractError(
            f"{job.id}: shots that asked to move did not; regenerate them, write those beats as "
            "stills, or set brief.allow_stills"
        )


def _stream_of(job: Job) -> dict | None:
    name = job.job.get("stream")
    return streams.load(job.folder.parents[1], name) if name else None


def _kit_bound(job: Job, stream: dict) -> None:
    """A stream piece must still be what its lock says, and go only to its own identity."""
    consistency.for_job(job)
    if job.read("asset_manifest").get("kit_lock_sha256") != consistency.lock_sha256(job):
        raise ContractError(f"{job.id}: assets were not made under this kit lock; render again")
    if job.job.get("distribution_identity") != stream["distribution_identity"]:
        raise ContractError(f"{job.id}: its identity is not the identity of {stream['stream_id']}")


def _account(job: Job, stream: dict, platform: str) -> str:
    handle = (stream.get("accounts") or {}).get(platform)
    if not handle:
        raise ContractError(f"{job.id}: {stream['stream_id']} has no account on {platform}")
    return str(handle)


def _is_restricted(stream: dict | None) -> bool:
    return bool(stream and (stream.get("restricted_tier") or {}).get("enabled"))


def _daily_limit(job: Job, stream: dict) -> None:
    today = dt.datetime.now(dt.UTC).date().isoformat()
    done = streams.posted_on(job.folder.parents[1], stream["stream_id"], today)
    if done >= stream["max_per_day"]:
        raise ContractError(f"{stream['stream_id']}: already {done} post(s) today, its daily limit")


def approve(
    job: Job, reviewer: str, *, platforms: list[str], notes: str = "", privacy: str = "public"
) -> dict:
    if not reviewer.strip():
        raise ContractError(f"{job.id}: approval needs the reviewer's name")
    final = job.artifact()
    preproduction.refuse_animatic(job, final)
    _qa_bound(job, final)
    _not_placeholder(job)
    stream = _stream_of(job)
    if stream:
        _kit_bound(job, stream)
        if stream.get("engine_version"):
            from .. import fingerprint

            fp = job.job.get("fingerprint") or fingerprint.fingerprint()
            fingerprint.verify({"fingerprint": fp}, stream["engine_version"])
        if not _is_restricted(stream):
            for platform in platforms:
                _account(job, stream, platform)
    packet = job.read("script_packet") if job.has("script_packet") else {}
    pub = packet.get("publish") or {}
    record = {
        "schema_version": "0.1",
        "job_id": job.id,
        "reviewer": reviewer,
        "approved_at": _now(),
        "artifact_sha256": sha256_file(final),
        **_master_record(final),
        "platforms": platforms,
        "title": pub.get("title") or packet.get("title") or job.id,
        "description": pub.get("description", ""),
        "hashtags": pub.get("hashtags", []),
        "synthetic_disclosure": labels.is_synthetic(job),
        "privacy": privacy,
        "notes": notes,
    }
    job.write("approval", record)
    job.set_status("approved")
    return record


def _master_record(final: Path) -> dict:
    master = final.with_name("final.master.mov")
    return {"master_sha256": sha256_file(master)} if master.exists() else {}


def _log(job: Job, entry: dict) -> None:
    log = (
        job.read("publish_log")
        if job.has("publish_log")
        else {"schema_version": "0.1", "job_id": job.id, "posts": []}
    )
    log["posts"].append(entry)
    job.write("publish_log", log)


def publish(
    job: Job, platform: str, *, dry_run: bool = True, publish_at: str | None = None
) -> dict:
    stream = _stream_of(job)
    if _is_restricted(stream):
        raise ContractError(
            f"{job.id}: this stream's output is a file for a person to place; the engine never posts it"
        )
    appr = job.read("approval")
    if platform not in appr["platforms"]:
        raise ContractError(f"{job.id}: {platform} not in approved platforms {appr['platforms']}")
    final = job.artifact()
    preproduction.refuse_animatic(job, final)
    if sha256_file(final) != appr["artifact_sha256"]:
        raise ContractError(
            f"{job.id}: {final.name} changed after approval; re-run QA and approval"
        )
    if _master_record(final).get("master_sha256") != appr.get("master_sha256"):
        raise ContractError(f"{job.id}: the master changed after approval; re-run QA and approval")
    _qa_bound(job, final)
    _not_placeholder(job)
    handle = None
    if stream:
        _kit_bound(job, stream)
        handle = _account(job, stream, platform)
        if not dry_run:
            _daily_limit(job, stream)
    if not dry_run and job.has("publish_log"):
        done = [
            p
            for p in job.read("publish_log")["posts"]
            if p["platform"] == platform and p["status"] == "posted"
        ]
        if done:
            raise ContractError(
                f"{job.id}: already posted to {platform} ({done[-1].get('url') or done[-1].get('post_id')})"
            )
    identity = job.job.get("distribution_identity")
    caption = appr["description"] + (
        "\n\n" + " ".join(appr["hashtags"]) if appr["hashtags"] else ""
    )
    limit = CAPTION_LIMITS.get(platform, 2200)
    if (job.folder / "stock.json").exists():
        from ..stock import credits

        if credits(job) not in caption[:limit]:
            raise ContractError(
                f"{job.id}: the stock credit would not survive {platform}'s {limit}-character caption; shorten it"
            )
    caption = caption[:limit]
    synthetic = labels.is_synthetic(job)
    if platform != "youtube":
        labels.aggregator_fields(platform, synthetic)  # refuses a platform with no label field
    when = labels.parse_publish_at(platform, publish_at)
    entry = {
        "platform": platform,
        "identity": identity,
        "at": _now(),
        "dry_run": dry_run,
        "title": appr["title"],
        "ai_label": synthetic,
    }
    if when:
        entry["scheduled_for"] = when
    if dry_run:
        entry["status"] = "dry_run"
    elif final.suffix != ".mp4":
        raise ContractError(
            f"{job.id}: no publisher takes audio-only {final.name} yet; the approval still stands"
        )
    elif platform not in ("youtube", "instagram", "tiktok", "x", "linkedin", "facebook", "threads"):
        raise ContractError(f"no publisher for {platform}")
    else:
        try:
            if platform == "youtube":
                entry.update(
                    _youtube_upload(
                        final,
                        appr["title"],
                        caption,
                        job.work / "thumb.jpg",
                        appr.get("privacy", "public"),
                        identity if stream else None,
                        synthetic=synthetic,
                        publish_at=when,
                    )
                )
            else:
                entry.update(
                    _upload_post(final, platform, appr["title"], caption, handle, synthetic)
                )
        except Exception as exc:
            entry.update(status="failed", error=str(exc)[:500])
            _log(job, entry)
            raise ContractError(f"{job.id}: {platform} upload failed: {exc}") from exc
    _log(job, entry)
    if not dry_run:
        job.set_status("published")
    return entry


# ------------------------------------------------------------- YouTube (official)
def _youtube_refresh_key(identity: str | None) -> str:
    """A stream posts with its own channel's token, so one channel's post cannot reach another."""
    if not identity:
        return "YOUTUBE_REFRESH_TOKEN"
    return "YOUTUBE_REFRESH_TOKEN_" + re.sub(r"[^A-Z0-9]+", "_", identity.upper())


def _youtube_token(identity: str | None = None) -> str:
    if not identity and os.environ.get("YOUTUBE_ACCESS_TOKEN"):
        return os.environ["YOUTUBE_ACCESS_TOKEN"]
    refresh = _youtube_refresh_key(identity)
    need = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", refresh)
    if not all(os.environ.get(k) for k in need):
        raise ContractError(f"set {need}" + ("" if identity else " or YOUTUBE_ACCESS_TOKEN"))
    r = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "client_id": os.environ["YOUTUBE_CLIENT_ID"],
            "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
            "refresh_token": os.environ[refresh],
            "grant_type": "refresh_token",
        },
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["access_token"]


def _youtube_upload(
    path: Path,
    title: str,
    description: str,
    thumb: Path,
    privacy: str,
    identity: str | None = None,
    *,
    synthetic: bool = True,
    publish_at: str | None = None,
) -> dict:
    tok = _youtube_token(identity)
    meta = {
        "snippet": {"title": title[:100], "description": description[:4900], "categoryId": "22"},
        "status": {
            "privacyStatus": privacy,
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": synthetic,
        },
    }
    if publish_at:  # YouTube holds a private upload and makes it public at this time
        meta["status"]["privacyStatus"] = "private"
        meta["status"]["publishAt"] = publish_at
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={
            "Authorization": f"Bearer {tok}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Type": "video/mp4",
            "X-Upload-Content-Length": str(path.stat().st_size),
        },
        data=json.dumps(meta),
        timeout=60,
    )
    init.raise_for_status()
    with open(path, "rb") as fh:
        up = requests.put(
            init.headers["Location"], headers={"Content-Type": "video/mp4"}, data=fh, timeout=3600
        )
    up.raise_for_status()
    vid = up.json()["id"]
    if thumb.exists():
        thumb_r = requests.post(
            f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
            headers={"Authorization": f"Bearer {tok}", "Content-Type": "image/jpeg"},
            data=thumb.read_bytes(),
            timeout=120,
        )
        if not thumb_r.ok:  # custom thumbnails need a verified channel; the upload itself stands
            pass
    return {"status": "posted", "post_id": vid, "url": f"https://youtube.com/shorts/{vid}"}


# ------------------------------------------------------------- Measure
def _identity_for(job: Job) -> str | None:
    return job.job.get("distribution_identity") if job.job.get("stream") else None


def measure(job: Job, *, force: bool = False) -> dict:
    log = job.read("publish_log")
    out = job.read("measure") if job.has("measure") else {"schema_version": "0.1", "job_id": job.id}
    for post in log["posts"]:
        if post.get("platform") == "youtube" and post.get("post_id"):
            r = requests.get(
                "https://www.googleapis.com/youtube/v3/videos",
                params={"part": "statistics", "id": post["post_id"]},
                headers={"Authorization": f"Bearer {_youtube_token(_identity_for(job))}"},
                timeout=60,
            )
            r.raise_for_status()
            stats = (r.json().get("items") or [{}])[0].get("statistics", {})
            age = (
                dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(post["at"])
            ).total_seconds() / 3600
            if age < 48 and not force:
                raise ContractError(
                    f"{job.id}: post is {age:.1f}h old; the keep/kill read is at 48h (use --force for a snapshot)"
                )
            out["views"] = int(stats.get("viewCount", 0))
            out["age_hours"] = round(age, 2)
            out["measured_at"] = _now()
            if age >= 48 and "views_48h" not in out:
                out["views_48h"] = out["views"]
            out["likes"] = int(stats.get("likeCount", 0))
            out["comments"] = int(stats.get("commentCount", 0))
            out["posted_at"] = post["at"]
            out["url"] = post.get("url")
    out["artifact_path"] = str(job.artifact())
    if job.ledger_path.exists():
        out["cost"] = round(job.spent(), 4)
    job.write("measure", out)
    if out.get("views_48h") is not None:
        job.set_status("measured")
    return out
