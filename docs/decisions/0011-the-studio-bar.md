# 0011. The quality bar is numbers a tool computes

Status: accepted · 2026-11-06.

## Context

"Studio quality" had no definition, and the 2026-11-05 premortem named that as a way to die: a bar nobody can check is a bar nobody can pass or fail. The operator's reviews of early renders gave real signal (slideshow, repetitive, awkward, choppy), and the operator has now asked for quality work ahead of the engine freeze that premortem proposed. This ADR supersedes that freeze for quality work only.

## Decision

- `docs/studio-bar.md` is the goal. `bar.py` measures it, and its limits live in `config/studio.yaml`.
- A signal stays only if it separates good from bad on real, reviewed samples. A signal that does not gets deleted.
- Only an objective defect blocks approval: a wrong codec, wrong colour tags, clipping, a fallback font. Everything else shows as a warning. Taste stays with the human at the gate, so a perfect score is never required to ship and is never proof of quality.
- A delivery profile meets a premium platform's published ingest requirements. Passing them shows a file can be ingested. Whether a platform accepts a piece stays that platform's decision.

## Consequences

The picture path moved to lossless 10-bit intermediates, which take more disk and time. Fonts are vendored, so renders match across machines. The bar cannot judge writing, performance, or whether a generated shot looks real. The operator's first-review verdict remains the real test, and the premortem's kill checks on shipping still apply.
