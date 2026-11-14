# 0017. An autonomy level per review gate

Status: proposed · 2026-11-14.

## Context

Every review gate in Kalainova is held by a person today. The long-term aim is for review gates to be handed to an automated check once that check has demonstrated reliable agreement with human judgment, without redesigning the gate mechanism itself. 

Previously, nothing in a stream contract declared who decides a gate, and an automated check had no vocabulary to indicate uncertainty.

## Decision

1. **Per-gate autonomy levels in the stream contract.**
   A stream may declare an `autonomy` object configuring each review gate to one of three levels:
   - `human` (default): A person decides the gate. Automated checks shadow and record their findings without gating.
   - `by-exception`: The automated check passes clear cases; a person reviews only flagged or `unsure` cases.
   - `audit`: Pieces proceed through the gate automatically; a person reviews a sample after the fact.

2. **Named gates.**
   The configurable gates are:
   - `track_pick`: Choosing a song or soundbed track take.
   - `stills`: Accepting the visual style, composition, and anatomy of key stills before video motion is paid for.
   - `animatic`: Accepting the rough cut draft (timing, sound, blocking).
   - `final`: QA checks on the assembled release piece.

3. **Kit freeze and publish are not delegable.**
   - Kit freeze (`kalainova kit freeze`) remains strictly a human attestation.
   - Publish is declared in the schema and **fixed at `human`** (`"publish": {"const": "human"}`). Handing publish to automation would contradict ADR 0004 and ADR 0007 and requires a separate decision.

4. **Uncertainty is a first-class status.**
   An automated check may return `unsure` in addition to `pass`, `warn`, and `fail`. `unsure` is recorded in `qa.json` under `schemas/qa.schema.json`. In `by-exception` mode, an `unsure` outcome escalates to human review.

5. **Promotion and demotion by evidence.**
   Movement of a gate from `human` to `by-exception` or `audit` requires measured agreement ($\ge 0.8$ AUC separation against human verdicts via `kalainova signals`). If agreement drops, the gate reverts to `human`.

6. **Paid spend limits hold.**
   At every autonomy level, spend remains capped by `cost_cap_per_job` and the brief.

## Consequences

- Stream contracts explicitly document gate governance.
- Runtime behavior remains unchanged until autonomy gate handlers are implemented in a future phase.
