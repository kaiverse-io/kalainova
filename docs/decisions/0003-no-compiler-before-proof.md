# 0003. No compiler, second format, or SKU before a proof

Status: superseded in part by 0007 and 0009; procedural formats and SKUs still wait for a proof. Accepted · 2026-11-05 · amended by 0007

## Context

Every early build pass ended with a schema and no file. The premortem ranks 'the check is the product' as a top failure.

## Decision

Until one job is `accepted` or `measured`: no compiler, no render plan, no scheduler, no procedural format, no downstream SKU. `check.py` rejects a `render_plan.json` and extension strategies before that.

## Consequences

The first pieces are made with rented tools. Owning the compile path is a later ADR that supersedes this one, opened with the proof in hand.
