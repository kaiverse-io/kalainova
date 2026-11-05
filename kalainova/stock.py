"""STOCK. Free-license footage for a subject, pulled into a job as operator inputs.

Sources (keys in the environment; both are free to obtain):
  PEXELS_API_KEY    https://www.pexels.com/api/   Pexels License: free commercial use, no attribution required
                                                  (credit appreciated); not for resale unaltered
  PIXABAY_API_KEY   https://pixabay.com/api/docs/ Pixabay Content License: free commercial use

Every clip is recorded in stock.json with its source page, author, license, and a credit line, and the
job's publish description gets the credits appended. Rights on the asset are `licensed`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests

from .jobfs import ContractError, Job

MODIFIERS = ["aerial", "skyline", "sunset", "coast", "street", "mountain", "beach", "night", "nature", "people walking"]
TIMEOUT = 60


def queries_for(subject: str, n: int = 6) -> list[str]:
    """A shot list for a place or topic: wide establishing first, then texture."""
    return [subject] + [f"{subject} {m}" for m in MODIFIERS[: n - 1]]


# ------------------------------------------------------------------ Pexels
def _pexels(query: str, orientation: str, per_page: int = 15) -> list[dict]:
    key = os.environ.get("PEXELS_API_KEY")
    if not key:
        return []
    params = {"query": query, "orientation": orientation, "size": "medium", "per_page": per_page}
    for url in ("https://api.pexels.com/videos/search", "https://api.pexels.com/v1/videos/search"):
        r = requests.get(url, params=params, headers={"Authorization": key}, timeout=TIMEOUT)
        if r.status_code == 404:
            continue
        r.raise_for_status()
        out = []
        for v in r.json().get("videos", []):
            files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width") and f.get("height")]
            if not files:
                continue
            # the largest file at or under 4K, preferring >= 1080 on the short side
            files.sort(key=lambda f: (min(f["width"], f["height"]) >= 1080, -abs(min(f["width"], f["height"]) - 1440)), reverse=True)
            f = files[0]
            out.append({"source": "pexels", "id": str(v["id"]), "page": v.get("url", ""), "duration": v.get("duration", 0),
                        "width": f["width"], "height": f["height"], "link": f["link"],
                        "author": (v.get("user") or {}).get("name", ""), "author_url": (v.get("user") or {}).get("url", ""),
                        "license": "Pexels License", "query": query})
        return out
    return []


# ------------------------------------------------------------------ Pixabay
def _pixabay(query: str, orientation: str, per_page: int = 15) -> list[dict]:
    key = os.environ.get("PIXABAY_API_KEY")
    if not key:
        return []
    r = requests.get("https://pixabay.com/api/videos/", params={"key": key, "q": query, "per_page": per_page,
                                                               "video_type": "film", "safesearch": "true"}, timeout=TIMEOUT)
    r.raise_for_status()
    out = []
    for h in r.json().get("hits", []):
        vids = h.get("videos") or {}
        f = next((vids[k] for k in ("large", "medium") if vids.get(k, {}).get("url")), None)
        if not f:
            continue
        out.append({"source": "pixabay", "id": str(h["id"]), "page": h.get("pageURL", ""), "duration": h.get("duration", 0),
                    "width": f.get("width", 0), "height": f.get("height", 0), "link": f["url"],
                    "author": h.get("user", ""), "author_url": f"https://pixabay.com/users/{h.get('user', '')}-{h.get('user_id', '')}/",
                    "license": "Pixabay Content License", "query": query})
    return out


def available() -> list[str]:
    return [n for n, k in (("pexels", "PEXELS_API_KEY"), ("pixabay", "PIXABAY_API_KEY")) if os.environ.get(k)]


def pick(cands: list[dict], count: int, *, min_short_side: int = 720, min_dur: float = 4, max_dur: float = 40) -> list[dict]:
    """Varied, usable clips: one per query first (coverage), then the rest by resolution."""
    seen, ok = set(), []
    for c in cands:
        key = (c["source"], c["id"])
        if key in seen or min(c["width"], c["height"]) < min_short_side or not (min_dur <= (c["duration"] or 0) <= max_dur):
            continue
        seen.add(key)
        ok.append(c)
    by_query: dict[str, list[dict]] = {}
    for c in ok:
        by_query.setdefault(c["query"], []).append(c)
    chosen: list[dict] = []
    while len(chosen) < count and any(by_query.values()):
        for q in list(by_query):
            if by_query[q] and len(chosen) < count:
                chosen.append(by_query[q].pop(0))
    return chosen


def fetch(job: Job, subject: str, *, count: int = 10, orientation: str = "portrait") -> list[Path]:
    if not available():
        raise ContractError("no stock source: set PEXELS_API_KEY or PIXABAY_API_KEY (both free)")
    cands: list[dict] = []
    for q in queries_for(subject):
        for fn in (_pexels, _pixabay):
            try:
                cands += fn(q, orientation)
            except requests.RequestException as exc:
                print(f"  stock: {fn.__name__[1:]} '{q}' failed: {exc}")
    chosen = pick(cands, count)
    if not chosen:
        raise ContractError(f"no usable free stock found for {subject!r}")
    dst_dir = job.work / "stock"
    dst_dir.mkdir(exist_ok=True)
    paths, records = [], []
    for i, c in enumerate(chosen):
        dst = dst_dir / f"{i:02d}_{c['source']}_{c['id']}.mp4"
        if not dst.exists():
            with requests.get(c["link"], stream=True, timeout=300) as r:
                r.raise_for_status()
                with open(dst, "wb") as fh:
                    for chunk in r.iter_content(1 << 16):
                        fh.write(chunk)
        site = "Pexels" if c["source"] == "pexels" else "Pixabay"
        records.append({**c, "file": dst.name, "credit": f"Video by {c['author'] or 'unknown'} on {site}"})
        paths.append(dst)
    (job.folder / "stock.json").write_text(json.dumps({"schema_version": "0.1", "job_id": job.id, "subject": subject,
                                                       "clips": records}, indent=2, ensure_ascii=False) + "\n")
    return paths


def credits(job: Job) -> str:
    p = job.folder / "stock.json"
    if not p.exists():
        return ""
    clips = json.loads(p.read_text())["clips"]
    names = sorted({c["credit"] for c in clips})
    return "Footage: " + "; ".join(names)
