# 0018. A stream may name one alternate provider and model

Status: proposed · 2026-11-14. Amends 0009.

## Context

A stream pins one provider and model per capability, and ADR 0009 set "No provider fallback for a pinned capability". If a provider retires, reprices, throttles, or alters a model behind an unchanged identifier, the stream halts. Vendors also change weights or prompt behavior without notice.

However, automatic failover between models during a run risks silent drift: a second model may alter face features, vocal tone, or style consistency across shots without the operator noticing.

## Decision

A stream may declare one alternate provider and model per capability beside its primary, under strict rules:

- **Human-gated switch.** A switch from primary to alternate is an explicit operational act recorded with the name of the person who authorized it. It is never an automatic, mid-flight failover.
- **Equal qualification.** The alternate must have passed the same qualification benchmark against the stream's kits as the primary (#88), recorded in `qualification.json` beside `stream.json`.
- **Open-weight anchor.** At least one of the two (primary or alternate) should have open weights where feasible, ensuring the stream does not depend solely on closed hosted endpoints.
- **Job immutability.** A job locked to a primary generator (`kit.lock.json`) is not silently re-run on an alternate; switching models requires requesting a new job so provenance remains unambiguous.

## Consequences

Streams gain resilience against provider deprecation and outages without risking silent character or visual drift. No schema or runtime changes are made in this decision; those follow acceptance by the operator in a subsequent change.
