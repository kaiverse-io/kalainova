# 0007. Own the compile path and gate auto-post on a hash-bound approval

Status: accepted · 2026-11-05 (merged in PR #2, landed on main in PR #3). Supersedes 0003 for the render path and amends 0004.

## Context

ADR 0003 holds the compiler until one job is accepted or measured. The operator then asked for a studio that turns a brief into finished media on demand and posts after one human tap, with no spend limit on rented models. The premortem's failure 2 ("a tree that cannot make media") argues the same way: the line has to emit a frame.

## Decision

- The repo owns an ffmpeg compile path (`kalainova/`): plan → assets → edit → compile → render → qa. Rented models still make the bytes; providers and prices live in `config/studio.yaml`, and every capability has a zero-cost local fallback.
- The render plan is a closed op list with a typed arg spec per op. Paths stay inside the job's work dir. Text reaches only `.ass` files, never a filtergraph.
- A render plan is legal only when compiled from an `edit_manifest` with `runtime: ffmpeg`.
- A human still approves every piece. The approval binds to the sha256 of the exact file QA passed, and `kalainova publish` posts only those bytes. Agents never write `approval.json`. Synthetic media is always labelled, or the post is refused.
- `procedural` and `downstream-sku` still wait for a proof (0003 stands for them). Cost caps reserve before every paid call.

## Consequences

The tree makes media now. The day-14 proof still needs a public URL or a tracked submission, and this ADR does not count as one. Revert by reverting the PR: the cockpit gates stand on their own.
