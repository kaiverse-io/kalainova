"""Compare the field names the active studio config and the fal adapter use with fal's schemas.

Free: fal serves each model's input schema with no key. Not part of CI (it needs the network).
Reads whichever config is active (KALAINOVA_CONFIG, else config/studio.yaml) and says which.

    uv run python scripts/check_fal_schemas.py

Covers request field names only, not reply parsing, prices, or other vendors.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
URL = "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id="


def input_fields(model: str) -> set[str]:
    url = URL + urllib.parse.quote(model, safe="/")
    with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310 - fixed https host
        schemas = json.load(r)["components"]["schemas"]
    found: set[str] = set()
    for name, body in schemas.items():
        if name.endswith("Input") and "properties" in body and "Element" not in name:
            found |= set(body["properties"])
    return found


def _video_names(spec: dict) -> set[str]:
    names = {"prompt", "duration", *spec.get("extra", {})}
    names |= {spec[k] for k in ("image_param", "end_image_param") if spec.get(k)}
    names.add(spec.get("aspect_param", "aspect_ratio"))
    return {n for n in names if n}


def _reference_names(cap: str, spec: dict) -> set[str]:
    names = {"prompt", *spec.get("extra", {})}
    if spec.get("images_param"):
        names.add(spec["images_param"])
    if spec.get("elements"):
        names |= {"elements", "image_urls"}
    if cap == "video":
        names |= {"duration", "aspect_ratio"}
    return names


def expected(cfg: dict) -> dict[str, set[str]]:
    """Model id to the request fields the config says it is sent."""
    want: dict[str, set[str]] = {}
    for model, spec in cfg.get("video_models", {}).get("fal", {}).items():
        want[model] = _video_names(spec)
    for cap, models in cfg.get("reference_models", {}).get("fal", {}).items():
        for model, spec in models.items():
            want.setdefault(model, set()).update(_reference_names(cap, spec))
    for model, spec in cfg.get("audio_models", {}).get("fal", {}).items():
        names = {"lyrics", spec.get("style_field", "prompt")}
        if spec.get("max_sec"):
            names.add("duration")
        want.setdefault(model, set()).update(names)
    return want


def main() -> int:
    path = Path(os.environ.get("KALAINOVA_CONFIG", REPO / "config" / "studio.yaml"))
    print(f"config: {path}")
    cfg = yaml.safe_load(path.read_text())
    bad = 0
    for model, names in sorted(expected(cfg).items()):
        try:
            have = input_fields(model)
        except Exception as exc:  # noqa: BLE001 - report any network or schema failure per model
            print(f"  ?  {model}: could not read its schema ({exc})")
            bad += 1
            continue
        missing = sorted(names - have)
        note = f": not in schema: {missing}" if missing else ""
        print(f"  {'ok' if not missing else 'XX'} {model}{note}")
        bad += bool(missing)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
