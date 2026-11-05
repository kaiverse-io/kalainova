---
kind: agent-context
status: active
last_reviewed: 2026-11-05
---

# Kalainova — Agent Context

Content generation engine for any subject. Video, audio, stills, and text. Inspired by `kaiverse-io/chassis` for the cockpit (this file, `just`, docs and ADRs, a contract eval, pre-commit, a devcontainer, the `open-a-job` skill). Do not copier-stamp a service into this repo.

The brief for the next agent is `CLAUDE_HANDOVER.md`. Read it before changing the tree. Names that appear only in that file stay in that file. The handover predates ADR 0007: where it says "no compiler", the ADRs in `docs/decisions/` win. The current verdict and kill checks are in `docs/explanation/premortem-2026-11-05-studio.md`.

## What you are building

A job. Not a niche, and not a sample domain checked into the tree.

Read `docs/consolidation.md`, then `docs/strategies.md`. Pick **one** peer way (funded cut, owned master, or generated). Copy `jobs/_template` to `jobs/<id>/`. The subject the operator asked for goes in that job's own files. Do not add the subject to `README.md`, `ARCHITECTURE.md`, schemas, or strategy docs. Do not open `procedural` or `downstream-sku` until one job is `accepted` or `measured`. The studio plan is `docs/studio.md`.

## Planes

- **Guardrails.** This file, `ARCHITECTURE.md`, `docs/decisions/`, `justfile` (`just ci`), `scripts/check.py`, `scripts/lint_docs.py`, pre-commit.
- **One strategy per job.** Do not cross strategies inside one job folder.
- **One distribution identity per strategy.** A funded-clip post never goes out on an identity used for owned or generated work.
- **Humans gate publish.** A human approves every piece (`kalainova approve`). Agents never write `approval.json`; `kalainova publish` posts only the approved, QA-checked bytes (ADR 0007). Agents never submit a campaign URL.
- **Rent the models, own the line.** The ffmpeg compile path is owned (ADR 0007): `python3 -m kalainova make <job>`. Rented models make the bytes, swapped in `config/studio.yaml`. Procedural formats and SKUs still wait for a proof.

## Forbidden

- Committing `mp3`, `mp4`, `wav`, `m4a`, `mov`, or `webm`.
- Naming a vertical, niche, brand, creator, or topic in the engine docs or schemas. Those words belong only inside a job folder the operator opened, and only if that job exists.
- Checking in a sample subject "to show how it works."
- Inventing a factual claim. If the script states a fact, `script_packet.json` carries a source for it.
- Using source material that is not covered by `rights` on the job: `funded-brief`, `owned`, or `licensed`.
- Batching before one unit of that strategy is accepted (funded) or measured (everything else).
- Comment-bait or a course funnel. That is not a strategy in this engine.
