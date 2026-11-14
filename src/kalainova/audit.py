"""Provider independence audit: what still exists in one vendor's form today.

Audits preference lists, models, and fallback chains in config/studio.yaml to identify single points
of vendor lock-in where losing a provider would halt production or degrade output.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from . import config


def audit_provider_independence(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Audit configured provider diversity and single-vendor risks."""
    if cfg is None:
        cfg = config.studio()

    pref = cfg.get("preference") or {}

    capabilities_audit: dict[str, Any] = {}
    single_vendor_count = 0
    multi_vendor_count = 0

    for cap, providers in sorted(pref.items()):
        if not isinstance(providers, list):
            providers = [providers]

        # Separate distinct rented vendors from local / open fallbacks
        rented = sorted({p for p in providers if p not in ("local", "mac")})
        has_local = any(p in ("local", "mac") for p in providers)

        if len(rented) == 0:
            diversity = "local-only"
        elif len(rented) == 1 and not has_local:
            diversity = "single-vendor"
            single_vendor_count += 1
        elif len(rented) == 1 and has_local:
            diversity = "single-vendor-with-local"
            single_vendor_count += 1
        else:
            diversity = "multi-vendor"
            multi_vendor_count += 1

        capabilities_audit[cap] = {
            "configured_providers": providers,
            "rented_providers": rented,
            "has_local_or_open_fallback": has_local,
            "diversity_status": diversity,
            "lock_in_risk": diversity in ("single-vendor", "single-vendor-with-local"),
        }

    return {
        "audited_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "total_capabilities": len(capabilities_audit),
        "single_vendor_count": single_vendor_count,
        "multi_vendor_count": multi_vendor_count,
        "capabilities": capabilities_audit,
    }


def format_table(report: dict[str, Any]) -> str:
    """Format independence audit report as a clean summary table."""
    lines: list[str] = [
        f"Provider Independence Audit ({report['audited_at']})",
        (
            f"Summary: {report['single_vendor_count']} single-vendor capability(s), "
            f"{report['multi_vendor_count']} multi-vendor capability(s)\n"
        ),
        f"  {'Capability':<15} {'Providers':<35} {'Local Fallback':<16} Status",
        "  " + "-" * 80,
    ]
    for cap, d in report["capabilities"].items():
        provs = ", ".join(d["configured_providers"]) or "(none)"
        local = "yes" if d["has_local_or_open_fallback"] else "no"
        lines.append(f"  {cap:<15} {provs:<35} {local:<16} {d['diversity_status']}")
    return "\n".join(lines)
