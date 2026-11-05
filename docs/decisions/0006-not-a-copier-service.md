# 0006. Not a Copier Python service

Status: accepted · 2026-11-05

## Context

`kaiverse-io/chassis` supplies the cockpit planes (agent context, one runner, CI, docs, evals, pre-commit, devcontainer, skills). Its template is a Python service; this repo has no service.

## Decision

Adapt the planes, not the package. Gates stay stdlib Python scripts behind `just`.

## Consequences

No runtime dependencies in the repo. A future compiler would arrive through ADR 0003's successor.
