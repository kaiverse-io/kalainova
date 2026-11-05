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
import hashlib
import json
import os
from pathlib import Path

import requests

from ..jobfs import ContractError, Job


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _qa_bound(job: Job, final: Path) -> dict:
    """QA must have passed on exactly these bytes."""
    qa = job.read("qa")
    if not qa.get("passed"):
        failing = [c["id"] for c in qa["checks"] if c["status"] == "fail"]
        raise ContractError(f"{job.id}: QA failed ({failing}); fix and re-render before approval")
    checked = (qa.get("artifacts_sha256") or {}).get("video")
    if not checked or checked != sha256_file(final):
        raise ContractError(f"{job.id}: final.mp4 is not the file QA checked; run qa again")
    return qa


CAPTION_LIMITS = {"youtube": 4900, "instagram": 2200, "tiktok": 2200, "facebook": 5000, "x": 280, "linkedin": 3000, "threads": 500}


def approve(job: Job, reviewer: str, *, platforms: list[str], notes: str = "", privacy: str = "public") -> dict:
    final = job.work / "final.mp4"
    _qa_bound(job, final)
    packet = job.read("script_packet")
    pub = packet.get("publish") or {}
    record = {
        "schema_version": "0.1",
        "job_id": job.id,
        "reviewer": reviewer,
        "approved_at": _now(),
        "artifact_sha256": sha256_file(final),
        "platforms": platforms,
        "title": pub.get("title") or packet.get("title") or job.id,
        "description": pub.get("description", ""),
        "hashtags": pub.get("hashtags", []),
        "synthetic_disclosure": True,
        "privacy": privacy,
        "notes": notes,
    }
    job.write("approval", record)
    job.set_status("approved")
    return record


def _log(job: Job, entry: dict) -> None:
    log = job.read("publish_log") if job.has("publish_log") else {"schema_version": "0.1", "job_id": job.id, "posts": []}
    log["posts"].append(entry)
    job.write("publish_log", log)


def publish(job: Job, platform: str, *, dry_run: bool = True) -> dict:
    appr = job.read("approval")
    if platform not in appr["platforms"]:
        raise ContractError(f"{job.id}: {platform} not in approved platforms {appr['platforms']}")
    final = job.work / "final.mp4"
    if sha256_file(final) != appr["artifact_sha256"]:
        raise ContractError(f"{job.id}: final.mp4 changed after approval; re-run QA and approval")
    _qa_bound(job, final)
    if not dry_run and job.has("publish_log"):
        done = [p for p in job.read("publish_log")["posts"] if p["platform"] == platform and p["status"] == "posted"]
        if done:
            raise ContractError(f"{job.id}: already posted to {platform} ({done[-1].get('url') or done[-1].get('post_id')})")
    identity = job.job.get("distribution_identity")
    caption = appr["description"] + ("\n\n" + " ".join(appr["hashtags"]) if appr["hashtags"] else "")
    limit = CAPTION_LIMITS.get(platform, 2200)
    if (job.folder / "stock.json").exists():
        from ..stock import credits
        if credits(job) not in caption[:limit]:
            raise ContractError(f"{job.id}: the stock credit would not survive {platform}'s {limit}-character caption; shorten it")
    caption = caption[:limit]
    entry = {"platform": platform, "identity": identity, "at": _now(), "dry_run": dry_run, "title": appr["title"]}
    if dry_run:
        entry["status"] = "dry_run"
    elif platform not in ("youtube", "instagram", "tiktok", "x", "linkedin", "facebook", "threads"):
        raise ContractError(f"no publisher for {platform}")
    else:
        try:
            if platform == "youtube":
                entry.update(_youtube_upload(final, appr["title"], caption, job.work / "thumb.jpg", appr.get("privacy", "public")))
            else:
                entry.update(_upload_post(final, platform, appr["title"], caption))
        except Exception as exc:
            entry.update(status="failed", error=str(exc)[:500])
            _log(job, entry)
            raise ContractError(f"{job.id}: {platform} upload failed: {exc}") from exc
    _log(job, entry)
    if not dry_run:
        job.set_status("published")
    return entry


# ------------------------------------------------------------- YouTube (official)
def _youtube_token() -> str:
    if os.environ.get("YOUTUBE_ACCESS_TOKEN"):
        return os.environ["YOUTUBE_ACCESS_TOKEN"]
    need = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    if not all(os.environ.get(k) for k in need):
        raise ContractError(f"set YOUTUBE_ACCESS_TOKEN or {need}")
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": os.environ["YOUTUBE_CLIENT_ID"], "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
        "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"], "grant_type": "refresh_token"}, timeout=60)
    r.raise_for_status()
    return r.json()["access_token"]


def _youtube_upload(path: Path, title: str, description: str, thumb: Path, privacy: str) -> dict:
    tok = _youtube_token()
    meta = {
        "snippet": {"title": title[:100], "description": description[:4900], "categoryId": "22"},
        "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
                   "containsSyntheticMedia": True},
    }
    init = requests.post(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(path.stat().st_size)},
        data=json.dumps(meta), timeout=60)
    init.raise_for_status()
    with open(path, "rb") as fh:
        up = requests.put(init.headers["Location"], headers={"Content-Type": "video/mp4"}, data=fh, timeout=3600)
    up.raise_for_status()
    vid = up.json()["id"]
    if thumb.exists():
        thumb_r = requests.post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                      headers={"Authorization": f"Bearer {tok}", "Content-Type": "image/jpeg"},
                      data=thumb.read_bytes(), timeout=120)
        if not thumb_r.ok:  # custom thumbnails need a verified channel; the upload itself stands
            pass
    return {"status": "posted", "post_id": vid, "url": f"https://youtube.com/shorts/{vid}"}


# ------------------------------------------------------------- Upload-Post (aggregator)
def _upload_post(path: Path, platform: str, title: str, caption: str) -> dict:
    """Upload-Post REST API. Verify field names against docs.upload-post.com before first live post;
    for TikTok, confirm the aggregator's app has passed TikTok's audit or posts land private.

    The engine cannot yet set each platform's AI-content label through this aggregator, so synthetic
    media is refused here until UPLOAD_POST_AI_LABEL_FIELD names the verified request field."""
    label_field = os.environ.get("UPLOAD_POST_AI_LABEL_FIELD")
    if not label_field:
        raise ContractError("synthetic media needs an AI label; set UPLOAD_POST_AI_LABEL_FIELD after checking the aggregator docs")
    key = os.environ.get("UPLOAD_POST_API_KEY")
    user = os.environ.get("UPLOAD_POST_USER")
    if not key or not user:
        raise ContractError("set UPLOAD_POST_API_KEY and UPLOAD_POST_USER (the profile name in Upload-Post)")
    with open(path, "rb") as fh:
        r = requests.post("https://api.upload-post.com/api/upload",
                          headers={"Authorization": f"Apikey {key}"},
                          data={"user": user, "platform[]": platform, "title": title, "description": caption,
                                label_field: "true"},
                          files={"video": (path.name, fh, "video/mp4")}, timeout=3600)
    r.raise_for_status()
    return {"status": "posted", "response": r.json()}


# ------------------------------------------------------------- Measure
def measure(job: Job, *, force: bool = False) -> dict:
    log = job.read("publish_log")
    out = job.read("measure") if job.has("measure") else {"schema_version": "0.1", "job_id": job.id}
    for post in log["posts"]:
        if post.get("platform") == "youtube" and post.get("post_id"):
            r = requests.get("https://www.googleapis.com/youtube/v3/videos",
                             params={"part": "statistics", "id": post["post_id"]},
                             headers={"Authorization": f"Bearer {_youtube_token()}"}, timeout=60)
            r.raise_for_status()
            stats = (r.json().get("items") or [{}])[0].get("statistics", {})
            age = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(post["at"])).total_seconds() / 3600
            if age < 48 and not force:
                raise ContractError(f"{job.id}: post is {age:.1f}h old; the keep/kill read is at 48h (use --force for a snapshot)")
            out["views"] = int(stats.get("viewCount", 0))
            out["age_hours"] = round(age, 2)
            out["measured_at"] = _now()
            if age >= 48 and "views_48h" not in out:
                out["views_48h"] = out["views"]
            out["likes"] = int(stats.get("likeCount", 0))
            out["comments"] = int(stats.get("commentCount", 0))
            out["posted_at"] = post["at"]
            out["url"] = post.get("url")
    out["artifact_path"] = str(job.work / "final.mp4")
    if job.ledger_path.exists():
        out["cost"] = round(job.spent(), 4)
    job.write("measure", out)
    if out.get("views_48h") is not None:
        job.set_status("measured")
    return out
