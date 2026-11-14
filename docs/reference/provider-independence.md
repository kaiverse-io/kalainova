# Provider Independence and Single-Vendor Audit

Tracks where the engine or an identity relies on a single vendor today, and what paths exist to decouple or swap them.

## Diversity Status

The engine audits vendor diversity across all capabilities with:
```bash
kalainova audit-independence [--json]
```

Each capability is classified into:
- **multi-vendor:** Two or more distinct rented providers are configured in preference order.
- **single-vendor-with-local:** One rented vendor is configured, with an open-source or local offline fallback (`local` or `mac`).
- **single-vendor:** Only one vendor is configured. Losing this provider halts production for that capability.
- **local-only:** Self-hosted or in-house processing with no rented provider dependencies.

## Key Independence Mitigations

1. **Alternate Providers & Models (ADR 0018):** Streams can declare fallback pins and alternate routes.
2. **Standardized Operations, Not Vendor Features:** Calls adhere to canonical engine schemas rather than proprietary vendor parameters.
3. **Open-Weight Floors:** Self-hosted execution (ADR 0019) ensures a local baseline remains usable even when rented services change terms.
4. **Empirical Scorecards (ADR 0011):** Candidate replacements are measured against real job telemetry and blind human preferences before any switch.
