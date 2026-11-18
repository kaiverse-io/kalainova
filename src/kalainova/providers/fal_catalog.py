"""What fal publishes about a model: its request schema (free, no key) and this account's unit price
(read with the key). The fal adapter checks a payload against the first before it is sent, and the
router corrects an estimate with the second."""

from __future__ import annotations

import os
from functools import cache
from typing import Any

import requests

from .. import knowledge
from . import rehearsal
from .transport import TIMEOUT

SCHEMA = "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id="  # public, no key
PRICING = (
    "https://api.fal.ai/v1/models/pricing"  # this account's unit prices, read with the same key
)
Fields = dict[str, Any]


@cache
def list_price(model: str) -> dict[str, Any] | None:
    """This account's price per billing unit for a model and the unit, from fal's pricing API (read
    once per process). None when it cannot be read: no key, a rehearsal, or no answer."""
    key = os.environ.get("FAL_KEY")
    if not key or rehearsal.active() is not None:
        return None
    try:
        r = requests.get(
            PRICING, params={"endpoint_id": model}, headers={"Authorization": f"Key {key}"},
            timeout=TIMEOUT,
        )  # fmt: skip
        r.raise_for_status()
        rows = [p for p in r.json().get("prices", []) if p.get("endpoint_id") == model]
        return (
            {"unit_price": float(rows[0]["unit_price"]), "unit": rows[0].get("unit")}
            if rows
            else None
        )
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def unit_price(model: str) -> float | None:
    found = list_price(model)
    return found["unit_price"] if found else None


@cache
def _inputs(model: str) -> tuple[dict[str, Fields], frozenset[str]]:
    """Every request field fal's published schema lists for a model, with what it says of each
    (type, maxLength, maximum...), and the ones it requires. Free: fal serves every model's schema
    with no key. Raises when it cannot be read."""
    r = requests.get(SCHEMA + model, timeout=30)
    r.raise_for_status()
    found: dict[str, Fields] = {}
    needed: set[str] = set()
    for name, body in r.json()["components"]["schemas"].items():
        if name.endswith("Input") and "properties" in body and "Element" not in name:
            found.update(body["properties"])
            needed |= set(body.get("required") or [])
    return found, frozenset(needed)


def input_schema(model: str) -> tuple[frozenset[str], frozenset[str]]:
    """The request fields fal's published schema lists for a model, and the ones it requires."""
    fields, needed = _inputs(model)
    return frozenset(fields), needed


def input_fields(model: str) -> dict[str, Fields]:
    """What fal's published schema says of each request field of a model."""
    return _inputs(model)[0]


def schema_problems(model: str, payload: Fields) -> list[str]:
    """What fal would refuse in a request before it is sent: a field its schema does not list, or
    one it requires that is missing. A schema that cannot be read is a problem too."""
    try:
        have, need = input_schema(model)
    except (requests.RequestException, ValueError, KeyError) as exc:
        return [f"could not read {model}'s schema ({exc})"]
    sent = set(payload)
    found = [f"not in {model}'s schema: {sorted(sent - have)}"] if sent - have else []
    found += [f"{model} requires {sorted(need - sent)}"] if need - sent else []
    fields = input_fields(model)
    for name, value in payload.items():  # a limit the vendor states is checked before sending
        most = knowledge.stated_max(fields.get(name) or {})
        if isinstance(value, str) and most is not None and len(value) > most:
            found.append(f"{name} is {len(value)} characters and {model} takes at most {most}")
    return found
