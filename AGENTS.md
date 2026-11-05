---
kind: agent-context
status: active
last_reviewed: 2026-11-05
---

# Kalainova — Agent Context

Content generation engine for any subject. Video, audio, stills, and text. Inspired by `kaiverse-io/chassis` for the cockpit (this file, `just`, docs and ADRs, a contract eval, pre-commit, a devcontainer, the `open-a-job` skill). Do not copier-stamp a service into this repo.

The brief for the next agent is `CLAUDE_HANDOVER.md`. Read it before changing the tree. Names that appear only in that file stay in that file.

## What you are building

A job. Not a niche, and not a sample domain checked into the tree.

Read `docs/consolidation.md`, then `docs/strategies.md`. Pick **one** peer way (funded cut, owned master, or generated). Copy `jobs/_template` to `jobs/<id>/`. The subject the operator asked for goes in that job's own files. Do not add the subject to `README.md`, `ARCHITECTURE.md`, schemas, or strategy docs. Do not open an extension, a format, or a compiler until one job is `accepted` or `measured`.

## Planes

- **Guardrails.** This file, `ARCHITECTURE.md`, `docs/decisions/`, `justfile` (`just ci`), `scripts/check.py`, `scripts/lint_docs.py`, pre-commit.
- **One strategy per job.** Do not cross strategies inside one job folder.
- **One distribution identity per strategy.** A funded-clip post never goes out on an identity used for owned or generated work.
- **Humans gate publish.** Agents do not upload, and they do not submit a campaign URL.
- **Rent first.** Do not add a compiler, a renderer, or a shared pipeline until one job has `status: accepted` or `status: measured`.

## Forbidden

- Committing `mp3`, `mp4`, `wav`, `m4a`, `mov`, or `webm`.
- Naming a vertical, niche, brand, creator, or topic in the engine docs or schemas. Those words belong only inside a job folder the operator opened, and only if that job exists.
- Checking in a sample subject "to show how it works."
- Inventing a factual claim. If the script states a fact, `script_packet.json` carries a source for it.
- Using source material that is not covered by `rights` on the job: `funded-brief`, `owned`, or `licensed`.
- Batching before one unit of that strategy is accepted (funded) or measured (everything else).
- Comment-bait or a course funnel. That is not a strategy in this engine.
