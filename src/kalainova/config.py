"""Studio config: provider preference per capability, model ids, unit prices.

Lookup order: $KALAINOVA_CONFIG, then config/studio.yaml in the repo.
A job may override with a "providers" object in job.json.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


@lru_cache(maxsize=1)
def studio() -> dict:
    path = Path(os.environ.get("KALAINOVA_CONFIG", REPO / "config" / "studio.yaml"))
    return yaml.safe_load(path.read_text()) if path.exists() else {}


@lru_cache(maxsize=1)
def _repo_bar() -> dict:
    path = REPO / "config" / "studio.yaml"
    return yaml.safe_load(path.read_text()).get("bar", {}) if path.exists() else {}


def bar_limits() -> dict:
    """The repo's limits, under a private config's, so an older config still has every limit."""
    return {**_repo_bar(), **(studio().get("bar") or {})}


def adapter(capability: str) -> dict:
    """Which implementation serves an open-tool capability (`adapters:` in the studio config).
    `use` names it; the rest is that adapter's own settings, such as the command to call.
    A capability not listed keeps its in-house implementation."""
    entry = (studio().get("adapters") or {}).get(capability) or {}
    return {"use": "inhouse", **entry}


def preference(capability: str, job: dict | None = None) -> list[str]:
    """The providers to try, in order. A job's own list replaces the studio's, so naming one provider pins it."""
    job_pref = ((job or {}).get("providers") or {}).get(capability)
    if job_pref:
        return list(job_pref)
    return list(studio().get("preference", {}).get(capability, []))


def model_for(provider: str, key: str) -> str:
    return str(studio().get("models", {}).get(provider, {}).get(key, ""))


def price_for(provider: str, key: str, model: str | None = None) -> dict:
    """A model's own price row if the table has one under its slug, otherwise the capability's."""
    table = studio().get("prices", {}).get(provider, {})
    return dict((model and table.get(model)) or table.get(key, {}))


def reference_spec(provider: str, capability: str, model: str) -> dict:
    """How a model takes reference images, or {} if it is not known to take them."""
    table = studio().get("reference_models", {}).get(provider, {}).get(capability, {})
    return dict(table.get(model) or {})


def audio_spec(provider: str, model: str) -> dict:
    """What a song or music model states about itself (its longest output, its field names)."""
    return dict((studio().get("audio_models", {}).get(provider, {})).get(model) or {})


def video_spec(provider: str, model: str) -> dict:
    """How a plain video model takes its inputs, or {} if it is not listed."""
    return dict((studio().get("video_models", {}).get(provider, {})).get(model) or {})


def profile(name: str) -> dict:
    return dict(studio().get("profiles", {}).get(name, {}))


def safe_zone(name: str) -> dict:
    """Where interface overlays leave room on a vertical profile, as fractions of the frame."""
    return dict(profile(name).get("safe_zone") or {})


@lru_cache(maxsize=1)
def _repo_licences() -> dict:
    path = REPO / "config" / "studio.yaml"
    return yaml.safe_load(path.read_text()).get("licences", {}) if path.exists() else {}


def licence_for(provider: str, model: str) -> dict:
    """What a model's terms allow, or {} if nobody has read them. A private config can add to these."""
    merged = {**_repo_licences(), **(studio().get("licences") or {})}
    table = merged.get(provider) or {}
    return dict(table.get(model) or table.get("*") or {})


def takes() -> dict:
    """How many takes a shot gets before anyone asks for more. A job's brief can override it."""
    return dict(studio().get("takes") or {})


def space_spec(capability: str) -> dict:
    """How a hosted Gradio app takes a request for this capability."""
    return dict((studio().get("models", {}).get("spaces") or {}).get(capability) or {})


def estimate(
    provider: str,
    capability: str,
    *,
    chars: int = 0,
    duration: float = 0.0,
    key: str | None = None,
    model: str | None = None,
) -> float:
    """Pre-call cost estimate from the price table, used to reserve against the cap."""
    p = (
        price_for(provider, key or capability, model)
        if model
        else price_for(provider, key or capability)
    )
    return (
        chars / 1000 * p.get("per_kchar", 0)
        + duration * p.get("per_sec", 0)
        + duration / 60 * p.get("per_min", 0)
        + p.get("per_image", 0)
        + p.get("per_track", 0)
        + p.get("per_call", 0)
        + p.get("cost_usd", 0)
        + (4000 / 1e6 * p.get("input_per_mtok", 0) + 4000 / 1e6 * p.get("output_per_mtok", 0))
    )
