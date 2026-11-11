"""AI-content labels and publish times for a post.

The label follows the assets: a piece with any synthetic asset is labelled, a piece with none is
not. Each platform's flag is the one the aggregator documents at
https://docs.upload-post.com/guides/ai-content-labeling (read 2026-11-12). A platform that guide
gives no request field for is refused for synthetic media, not posted unlabelled.
"""

from __future__ import annotations

import datetime as dt

from ..jobfs import ContractError, Job

# Platform -> request fields the aggregator maps to that platform's own disclosure flag. The
# cross-platform alias is_ai_generated covers these; Facebook Reels also take their own field.
AGGREGATOR_LABELS: dict[str, dict[str, str]] = {
    "tiktok": {"is_ai_generated": "true"},
    "instagram": {"is_ai_generated": "true"},
    "youtube": {"is_ai_generated": "true"},
    "x": {"is_ai_generated": "true"},
    "threads": {"is_ai_generated": "true"},
    "facebook": {"is_ai_generated": "true", "facebook_is_ai_generated": "true"},
}

# Platforms whose own API takes a publish time for an uploaded video. Others post on upload.
NATIVE_SCHEDULE = ("youtube",)


def is_synthetic(job: Job) -> bool:
    """True when any asset in the piece is synthetic. Same test QA uses for its disclosure check."""
    return any(a.get("synthetic") for a in job.read("asset_manifest")["assets"])


def aggregator_fields(platform: str, synthetic: bool) -> dict[str, str]:
    """The label fields for one platform, empty for a real-only piece, a refusal if none exist."""
    if not synthetic:
        return {}
    fields = AGGREGATOR_LABELS.get(platform)
    if fields is None:
        raise ContractError(
            f"{platform} has no documented AI-label field through the aggregator; "
            "this piece has synthetic assets, so it is not posted there"
        )
    return fields


def parse_publish_at(
    platform: str, value: str | None, now: dt.datetime | None = None
) -> str | None:
    """A UTC ISO time for a scheduled post, or None. Refused where the platform cannot hold one."""
    if not value:
        return None
    if platform not in NATIVE_SCHEDULE:
        raise ContractError(f"{platform} cannot hold a scheduled post through its own API")
    try:
        when = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"publish time {value!r} is not an ISO 8601 time") from exc
    if when.tzinfo is None:
        raise ContractError(
            f"publish time {value!r} needs a UTC offset, such as 2026-12-01T18:00:00Z"
        )
    if when <= (now or dt.datetime.now(dt.UTC)):
        raise ContractError(f"publish time {value!r} is not in the future")
    return when.astimezone(dt.UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
