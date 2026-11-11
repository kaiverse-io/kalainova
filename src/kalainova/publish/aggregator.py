"""The aggregator route: one upload that reaches several platforms."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests

from ..jobfs import ContractError
from . import labels


def upload_post(
    path: Path,
    platform: str,
    title: str,
    caption: str,
    handle: str | None = None,
    synthetic: bool = True,
) -> dict[str, Any]:
    """Upload-Post REST API. For TikTok, confirm the aggregator's app has passed TikTok's audit or
    posts land private. The AI label fields come from the aggregator's labelling guide, per platform
    (publish/labels.py); a platform the guide does not cover is refused for synthetic media."""
    label = labels.aggregator_fields(platform, synthetic)
    key = os.environ.get("UPLOAD_POST_API_KEY")
    user = handle or os.environ.get("UPLOAD_POST_USER")
    if not key or not user:
        raise ContractError(
            "set UPLOAD_POST_API_KEY and UPLOAD_POST_USER (the profile name in Upload-Post)"
        )
    with open(path, "rb") as fh:
        r = requests.post(
            "https://api.upload-post.com/api/upload",
            headers={"Authorization": f"Apikey {key}"},
            data={
                "user": user,
                "platform[]": platform,
                "title": title,
                "description": caption,
                **label,
            },
            files={"video": (path.name, fh, "video/mp4")},
            timeout=3600,
        )
    r.raise_for_status()
    return {"status": "posted", "response": r.json()}
