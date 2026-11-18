"""Studio config: provider preference per capability, model ids, unit prices.

config/studio.yaml in the repo is the base. A private file named by $KALAINOVA_CONFIG is laid over
it, key by key, so it holds only what it changes and never hides a section the repo adds later.
A job may override with a "providers" object in job.json.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def overlay(base: dict, over: dict) -> dict:
    """`over` laid on `base`: tables merge key by key; any other value, a list included, replaces."""
    out = dict(base)
    for key, value in over.items():
        below = out.get(key)
        out[key] = (
            overlay(below, value) if isinstance(value, dict) and isinstance(below, dict) else value
        )
    return out


class _OneOfEach(yaml.SafeLoader):
    """A YAML reader that refuses a key written twice in one table. YAML lets the second copy win
    silently, so a section added at the end of a file would drop the one above it."""


def _one_of_each(loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False) -> dict:
    seen: set = set()
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=True)
        if key in seen:
            raise ValueError(f"{node.start_mark.name}: {key!r} is written twice (line "
                             f"{key_node.start_mark.line + 1}); merge the two into one")  # fmt: skip
        seen.add(key)
    return loader.construct_mapping(node, deep)


_OneOfEach.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _one_of_each)


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open() as text:  # the file object, so a duplicate key names its file
        return yaml.load(text, Loader=_OneOfEach) or {}  # noqa: S506 - a SafeLoader subclass


@lru_cache(maxsize=1)
def _repo() -> dict:
    return _read(REPO / "config" / "studio.yaml")


@lru_cache(maxsize=1)
def studio() -> dict:
    """The repo's config with the private one laid over it.

    A private file used to replace the repo's whole: one copied before a section existed lost that
    section, and its stale prices under-reserved spend against the cap.
    """
    private = os.environ.get("KALAINOVA_CONFIG")
    return overlay(_repo(), _read(Path(private))) if private else _repo()


def _repo_bar() -> dict:
    return dict(_repo().get("bar") or {})


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


def sing_spec(provider: str, model: str) -> dict:
    """How a model sings a shot in one call (a still and a line in), or {} if it is not listed."""
    return dict((studio().get("sing_models", {}).get(provider, {})).get(model) or {})


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
