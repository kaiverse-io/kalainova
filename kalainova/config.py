"""Studio config: provider preference per capability, model ids, unit prices.

Lookup order: $KALAINOVA_CONFIG, then config/studio.yaml in the repo.
A job may override with a "providers" object in job.json.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def studio() -> dict:
    path = Path(os.environ.get("KALAINOVA_CONFIG", REPO / "config" / "studio.yaml"))
    return yaml.safe_load(path.read_text()) if path.exists() else {}


def preference(capability: str, job: dict | None = None) -> list[str]:
    """The providers to try, in order. A job's own list replaces the studio's, so naming one provider pins it."""
    job_pref = ((job or {}).get("providers") or {}).get(capability)
    if job_pref:
        return list(job_pref)
    return list(studio().get("preference", {}).get(capability, []))


def model_for(provider: str, key: str) -> str:
    return str(studio().get("models", {}).get(provider, {}).get(key, ""))


def price_for(provider: str, key: str) -> dict:
    return dict(studio().get("prices", {}).get(provider, {}).get(key, {}))


def profile(name: str) -> dict:
    return dict(studio().get("profiles", {}).get(name, {}))


def estimate(provider: str, capability: str, *, chars: int = 0, duration: float = 0.0, key: str | None = None) -> float:
    """Pre-call cost estimate from the price table, used to reserve against the cap."""
    p = price_for(provider, key or capability)
    return (
        chars / 1000 * p.get("per_kchar", 0)
        + duration * p.get("per_sec", 0)
        + duration / 60 * p.get("per_min", 0)
        + p.get("per_image", 0)
        + p.get("per_track", 0)
        + (4000 / 1e6 * p.get("input_per_mtok", 0) + 4000 / 1e6 * p.get("output_per_mtok", 0))
    )
