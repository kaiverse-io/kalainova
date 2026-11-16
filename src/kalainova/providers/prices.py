"""Prices the engine checks for itself, so a wrong or stale price table cannot under-reserve.

The price table (config/studio.yaml) is written by people and can be wrong: on 16 Nov 2026 it
priced Kling O3 at $0.112/s when fal listed $0.14 for this account. An estimate is therefore the
table's figure times a correction, the highest of:

- 1, the table itself;
- the vendor's list price over the table's rate, read from the vendor's pricing API at most once
  a day and kept beside the studio, used only when the vendor prices per second as the table does
  and the table's row gives no reason (`checked:`) for differing;
- the most a recent bill exceeded its table figure for that model, learned from every call where the
  vendor said what it billed (`settle_at_vendor` keeps both figures on the ledger).

So the engine corrects itself from its own bills, and a person fixes the table at leisure: a drift
past DRIFT is printed and stays on the record. The correction never lowers an estimate; a vendor
charging less shows on the ledger as the gap between the two figures.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from .. import config
from ..jobfs import Job
from .contract import Billable

LEARNED = "prices.learned.jsonl"
LISTED = ".cache/vendor-prices.json"
LIST_MAX_AGE = 24 * 3600
RECENT = 20  # bills a learned correction looks back over
DRIFT = 0.10  # a bill this far from its table figure is reported


def _root(job: Job) -> Path:
    return job.folder.parents[1]  # the studio: jobs/<id> sits under it, beside kits and streams


def _learned(job: Job, provider: str, model: str) -> list[float]:
    path = _root(job) / LEARNED
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("provider") == provider and row.get("model") == model:
            rows.append(float(row["ratio"]))
    return rows[-RECENT:]


def listed(job: Job, provider: str, model: str, fetch: Any = None) -> dict[str, Any] | None:
    """The vendor's list price for a model, from the studio's cache if under a day old, else from
    `fetch(model)` (the adapter's own reader), which is skipped when there is none."""
    path = _root(job) / LISTED
    try:
        cache = json.loads(path.read_text()) if path.exists() else {}
    except ValueError:
        cache = {}
    key = f"{provider}:{model}"
    row = cache.get(key)
    if row and time.time() - float(row.get("read_at", 0)) < LIST_MAX_AGE:
        return dict(row)
    found = fetch(model) if fetch else None
    if not found:
        return dict(row) if row else None
    row = {**found, "read_at": time.time()}
    cache[key] = row
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, indent=2) + "\n")
    except OSError:
        pass
    return row


def correction(
    job: Job, provider: Any, billable: Billable, model: str | None = None
) -> tuple[float, str]:
    """How much to raise a table estimate, and why: 1.0 and "" when the table stands. With no pin,
    the model checked is the provider's default for the call, the one it will use."""
    key = provider.price_key(billable)
    model = model or config.model_for(provider.name, key)
    if not model:
        return 1.0, ""
    found = [(1.0, "")]
    row = config.price_for(provider.name, key, model) or {}
    rate, reviewed = row.get("per_sec"), row.get("checked")
    vendor = listed(job, provider.name, model, provider.list_price)
    if vendor and rate and not reviewed and vendor.get("unit") == "seconds":
        found.append((float(vendor["unit_price"]) / float(rate), "the vendor's list price"))
    bills = _learned(job, provider.name, model)
    if bills:
        found.append(
            (max(bills), f"the most a recent bill exceeded the table ({len(bills)} bills)")
        )
    factor, why = max(found, key=lambda f: f[0])
    return round(factor, 4), why


def learn(job: Job, provider: str, model: str, meta: dict[str, Any]) -> None:
    """Keep what a call was billed against what the table said, and say so if they drift apart."""
    table, vendor = meta.get("table_cost"), meta.get("vendor_cost")
    if not table or vendor is None or not model:
        return
    ratio = float(vendor) / float(table)
    row = {
        "at": time.time(),
        "provider": provider,
        "model": model,
        "table_cost": table,
        "vendor_cost": vendor,
        "billed_units": meta.get("billed_units"),
        "ratio": round(ratio, 4),
    }
    try:
        with open(_root(job) / LEARNED, "a") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        return
    if abs(ratio - 1) > DRIFT:
        print(
            f"{job.id}: {provider} billed ${float(vendor):.4f} for {model} where the price table "
            f"said ${float(table):.4f}; later estimates for it are raised to match until the "
            "table is corrected",
            file=sys.stderr,
        )
