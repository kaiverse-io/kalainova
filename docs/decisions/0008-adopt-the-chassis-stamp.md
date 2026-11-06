# 0008. Adopt the chassis stamp

Status: accepted · 2026-11-06. Supersedes 0006.

## Context

ADR 0006 adapted the chassis planes by hand because this repo had no service. It has one now: an engine with runtime dependencies, and agents working in it daily. The operator asked for a fresh stamp so template updates flow in.

## Decision

- Stamped from `kaiverse-io/chassis` v0.14.1. `.copier-answers.yml` records the answers, and `copier update --trust` pulls later tags as a real diff.
- The package moves to `src/kalainova/`, run through `uv`. Gates are `ruff`, strict `mypy`, `import-linter`, `gitleaks`, `opengrep`, a coverage ratchet, and `ci-arch`. The engine contract gates stay and run first.
- Kept from before the stamp: flat ADR numbering here, Mermaid for views other than the Component Diagram, and the engine docs lint.
- Not adopted: `.github/workflows/.yaml`, which v0.14.1 emits with release automation off because its conditional filename renders empty. `copier update` may bring it back until that is fixed upstream. Delete it if it does.
- Debt from before the stamp is listed by file in `pyproject.toml` under ruff `per-file-ignores` and mypy `overrides`. Those lists only shrink. New modules are held to the full gates.

## Consequences

`python3 -m kalainova` becomes `uv run kalainova`. Every open branch sees the reformat and the move as a conflict once.
