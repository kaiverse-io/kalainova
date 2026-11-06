# 0001. The subject is an input on the job

Status: accepted · 2026-11-05. Amended by 0009 and 0010: the subject is an operator input on a job, kit, or stream, all of which live in a private home.

## Context

Every playbook disagreed about topics and agreed about the machine: make a piece, put it where a person can see it, measure at 48 hours, keep or kill.

## Decision

The engine names no vertical, niche, brand, creator, or topic. The subject is written in `jobs/<id>/` only. `scripts/lint_docs.py` keeps engine docs clean, with an operator-local denylist that never enters git.

## Consequences

A real job with a real subject is allowed and expected. A sample subject checked in "to show how it works" is not.
