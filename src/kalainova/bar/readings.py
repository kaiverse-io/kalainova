"""A reading, its limit, and how a set of readings is reported."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .. import config


# ------------------------------------------------------------------ reading a file
@dataclass(frozen=True)
class Reading:
    id: str
    value: float | str | None
    limit: str
    ok: bool
    blocks: bool = False


def limits() -> dict[str, Any]:
    return config.bar_limits()


def at_most(rid: str, value: float, key: str, *, blocks: bool = False) -> Reading:
    limit = float(limits()[key])
    return Reading(rid, round(float(value), 4), f"<= {limit:g}", bool(value <= limit), blocks)


def at_least(rid: str, value: float, key: str, *, blocks: bool = False) -> Reading:
    limit = float(limits()[key])
    return Reading(rid, round(float(value), 4), f">= {limit:g}", bool(value >= limit), blocks)


def _tally(readings: list[dict[str, Any]]) -> dict[str, int]:
    return {"met": sum(bool(r["ok"]) for r in readings), "total": len(readings)}


def summarise(readings: list[dict[str, Any]]) -> dict[str, Any]:
    """Conformance and craft apart. Conformance is mostly the renderer checking its own work, so a
    single total flatters anything it makes: a flat gradient reads higher than real footage.
    """
    met = sum(bool(r["ok"]) for r in readings)
    return {
        "passed": met == len(readings),
        "met": met,
        "total": len(readings),
        "conformance": _tally([r for r in readings if r["blocks"]]),
        "craft": _tally([r for r in readings if not r["blocks"]]),
        "readings": readings,
    }


def summary_line(report: dict[str, Any]) -> str:
    """How a person should read a report: two numbers that mean different things."""
    conform, craft = report["conformance"], report["craft"]
    return (
        f"conformance {conform['met']}/{conform['total']}, craft {craft['met']}/{craft['total']}. "
        "A clean sheet shows no measured defect, not that the piece is good"
    )


def as_checks(report: dict[str, Any]) -> list[dict[str, str]]:
    """Readings as QA checks. Only an objective defect blocks. Taste stays with the human."""
    return [
        {
            "id": f"bar.{r['id']}",
            "status": "pass" if r["ok"] else ("fail" if r["blocks"] else "warn"),
            "detail": f"{r['value']} (limit {r['limit']})",
        }
        for r in report["readings"]
    ]
