"""Provider and model scorecards: rate what we run on real jobs.

Aggregates operational traces and takes across runs to compute empirical metrics per capability
and model (latency, cost, failure rate, and human acceptance).
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
from pathlib import Path
from typing import Any

from .jobfs import validate

MIN_SAMPLE_THRESHOLD = 5


def aggregate_traces(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate trace dictionaries into per-capability and per-model scorecards."""
    by_cap: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for t in traces:
        cap = t.get("capability")
        model = t.get("model") or t.get("provider") or "unknown"
        if not cap:
            continue
        by_cap.setdefault(cap, {}).setdefault(model, []).append(t)

    out_capabilities: dict[str, Any] = {}
    for cap, models in sorted(by_cap.items()):
        cap_models: dict[str, Any] = {}
        has_qualified = False
        for model, records in sorted(models.items()):
            n = len(records)
            successes = sum(1 for r in records if r.get("outcome") == "success")
            durations = [float(r["duration_sec"]) for r in records if "duration_sec" in r]
            costs = [float(r["cost"]) for r in records if "cost" in r]

            avg_dur = round(sum(durations) / len(durations), 3) if durations else 0.0
            avg_cost = round(sum(costs) / len(costs), 5) if costs else 0.0
            succ_rate = round(successes / n, 3) if n else 0.0

            if n >= MIN_SAMPLE_THRESHOLD:
                status = "qualified"
                has_qualified = True
            else:
                status = f"not enough yet (n={n}, need at least {MIN_SAMPLE_THRESHOLD})"

            cap_models[model] = {
                "sample_count": n,
                "success_rate": succ_rate,
                "avg_duration_sec": avg_dur,
                "avg_cost": avg_cost,
                "verdict_acceptance_rate": None,
                "status": status,
            }

        if has_qualified:
            cap_status = "qualified"
        else:
            cap_status = f"not enough yet (need at least {MIN_SAMPLE_THRESHOLD} samples per model)"
        out_capabilities[cap] = {
            "status": cap_status,
            "models": cap_models,
        }

    report = {
        "schema_version": "0.1",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "min_samples": MIN_SAMPLE_THRESHOLD,
        "capabilities": out_capabilities,
    }
    validate("scorecard", report, "scorecard.json")
    return report


def _read_trace_file(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.is_file():
        return rows
    for line in path.read_text().splitlines():
        if line.strip():
            with contextlib.suppress(Exception):
                rows.append(json.loads(line))
    return rows


def scan_traces(root: Path) -> list[dict[str, Any]]:
    """Scan root or its subdirectories for trace.jsonl files."""
    if not root.exists():
        return []
    if root.is_file() and root.name == "trace.jsonl":
        return _read_trace_file(root)
    traces: list[dict[str, Any]] = []
    seen: set[Path] = set()
    for path in root.rglob("trace.jsonl"):
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            traces.extend(_read_trace_file(path))
    return traces


def scorecard_report(root: Path, capability: str | None = None) -> dict[str, Any]:
    """Generate scorecards from trace records under root."""
    traces = scan_traces(root)
    if capability:
        traces = [t for t in traces if t.get("capability") == capability]
    return aggregate_traces(traces)


def format_table(card: dict[str, Any], capability: str | None = None) -> str:
    """Format scorecard dictionary as a readable text table."""
    caps = card.get("capabilities", {})
    if capability and capability in caps:
        caps = {capability: caps[capability]}
    if not caps:
        return "No telemetry records found. Not enough data yet."

    lines: list[str] = []
    hdr = f"  {'Model':<35} {'Samples':<9} {'Success':<9} {'Avg Sec':<10} {'Avg Cost':<10} Status"
    for cap, data in caps.items():
        lines.append(f"\nCapability: {cap} ({data['status']})")
        lines.append(hdr)
        lines.append("  " + "-" * 90)
        for model, m in data["models"].items():
            succ = f"{m['success_rate'] * 100:.1f}%"
            dur = f"{m['avg_duration_sec']:.2f}s"
            cost = f"${m['avg_cost']:.4f}"
            lines.append(
                f"  {model:<35} {m['sample_count']:<9} {succ:<9} {dur:<10} {cost:<10} {m['status']}"
            )
    return "\n".join(lines)
