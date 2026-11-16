"""Compare the active studio config's price rows with fal's own unit prices for this account.

Needs FAL_KEY, and makes one free read of fal's pricing API (https://api.fal.ai/v1/models/pricing);
no model is called and nothing is billed. Not part of CI (it needs the network and a key).
Reads whichever config is active (KALAINOVA_CONFIG, else config/studio.yaml) and says which.

    uv run python scripts/check_fal_prices.py

A per-second row that differs from fal's unit price fails, unless the row says why under
`checked:` (fal's unit price can be a base rate a resolution multiplies). A model fal prices in
another unit
(tokens, images, audio files) is listed for a person to read: there the table is an estimate, and
each call is settled at the units fal says it billed (X-Fal-Billable-Units), not at the table.
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
PRICING = "https://api.fal.ai/v1/models/pricing?endpoint_id="
TOLERANCE = 0.02  # a row within 2% of fal's price is the same price
RATE_KEYS = ("per_sec", "per_image", "per_track", "per_min", "cost_usd")


def config() -> tuple[dict, str]:
    base = REPO / "config" / "studio.yaml"
    cfg = yaml.safe_load(base.read_text())
    private = os.environ.get("KALAINOVA_CONFIG")
    if private and Path(private).exists():
        from kalainova.config import overlay  # the engine's own rule, so this checks what runs

        cfg = overlay(cfg, yaml.safe_load(Path(private).read_text()) or {})
    return cfg, f"config: {base}" + (f", with {private} laid over it" if private else "")


def models(cfg: dict) -> dict[str, str]:
    """Every fal model the config can call, with the capability row that prices it by default."""
    found: dict[str, str] = {}
    for cap, model in (cfg.get("models", {}).get("fal") or {}).items():
        if isinstance(model, str) and "/" in model:  # a model id, not a setting such as "2K"
            found[model] = cap
    for model in cfg.get("video_models", {}).get("fal", {}):
        found.setdefault(model, "image_to_video")
    for cap, listed in cfg.get("reference_models", {}).get("fal", {}).items():
        for model in listed:
            found.setdefault(model, "reference_to_video" if cap == "video" else cap)
    return found


def table_rate(prices: dict, model: str, cap: str) -> tuple[float | None, str]:
    """The rate the engine estimates with: the model's own row, else its capability's."""
    if (prices.get(model) or {}).get("checked"):
        own = prices[model]
        rate = next((float(own[k]) for k in RATE_KEYS if k in own), None)
        return rate, f"own row, checked: {own['checked']}"
    for name, source in ((model, "own row"), (cap, f"{cap} row"), ("video", "video row")):
        row = prices.get(name) or {}
        for key in RATE_KEYS:
            if key in row:
                return float(row[key]), f"{source}, {key}"
        if name == cap and cap not in ("image_to_video", "reference_to_video"):
            break
    return None, "no row"


def fal_prices(names: list[str], key: str) -> dict[str, dict]:
    found: dict[str, dict] = {}
    for i in range(0, len(names), 50):  # fal takes at most 50 endpoints a call
        ids = ",".join(names[i : i + 50])
        req = urllib.request.Request(  # noqa: S310 - fixed https host
            PRICING + urllib.parse.quote(ids, safe="/,"), headers={"Authorization": f"Key {key}"}
        )
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 - fixed https host
            for row in json.load(r).get("prices", []):
                found[row["endpoint_id"]] = row
    return found


def main() -> int:
    key = os.environ.get("FAL_KEY")
    if not key:
        print("FAL_KEY is not set: the pricing API needs it (one free read, nothing billed)")
        return 2
    cfg, said = config()
    print(said)
    prices = cfg.get("prices", {}).get("fal") or {}
    listed = models(cfg)
    try:
        theirs = fal_prices(sorted(listed), key)
    except Exception as exc:  # noqa: BLE001 - report any network failure once
        print(f"could not read fal's prices: {exc}")
        return 2
    bad = 0
    for model, cap in sorted(listed.items()):
        ours, source = table_rate(prices, model, cap)
        row = theirs.get(model)
        if not row:
            print(f"  ?  {model}: fal lists no price")
            continue
        unit, price = row.get("unit", "?"), float(row.get("unit_price", 0))
        if unit != "seconds":
            print(f"  ~  {model}: fal prices ${price} per {unit}; the table says {ours} ({source})")
            continue
        off = ours is None or abs(ours - price) > TOLERANCE * price
        why = "checked:" in source
        mark = "!!" if off and why else "XX" if off else "ok"
        print(f"  {mark} {model}: fal ${price}/s, table {ours} ({source})")
        bad += off and not why
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
