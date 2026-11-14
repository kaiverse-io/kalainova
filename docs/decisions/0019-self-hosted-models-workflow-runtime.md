# 0019. Self-hosted models through one workflow runtime

Status: proposed · 2026-11-14. Amends 0010.

## Context

Each self-hosted model in the engine currently uses an in-house runner under `src/kalainova/providers/runners/`. Adding each new open-weight model requires writing and maintaining bespoke subprocess wrappers, managing independent virtualenvs, and tracking upstream inference driver changes.

In practice, new open-weight models, motion adapters, and fine-tunes arrive first as graph workflows for standardized node-based runtimes. ADR 0010 Phase 2 anticipated serverless CPU containers because models were rented over HTTP; supporting self-hosted models requires amending that assumption to allow GPU workers.

## Decision

Self-hosted models will be reached through one unified workflow adapter:

- **Single adapter interface.** Submit a declarative workflow, poll execution status, and retrieve artifact bytes.
- **External workflow templates.** Capabilities map to named workflow JSON templates with neutral input parameters (prompts, seeds, reference image hashes). These workflow definitions live in the operator's private home (`$KALAINOVA_HOME/workflows/`), never in this public repo.
- **Runtime as a service.** The runtime is called as a separate service via its HTTP/WebSocket API; it is never ported or embedded into the engine codebase.
- **Deprecation of per-model runners.** The bespoke runners in `providers/runners/` will be phased out once the unified workflow runtime is proven on accepted pieces.
- **Resource discipline.** Local model runs on an operator workstation must pass a benchmark verifying peak memory stays under the local ceiling before automated batch use. Video generation remains rented on cloud GPU endpoints until high local utilization justifies continuous hardware allocation.

## Consequences

Adding support for newly released open-source models becomes a workflow authoring task rather than engine code modification. Implementation follows acceptance of the first pieces on the rented baseline.
