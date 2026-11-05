# 0002. Rent the tool, own the job folder, the gate, and the log

Status: accepted · 2026-11-05

## Context

Generators, clippers, voices, music models, and schedulers change monthly. The record of what shipped does not.

## Decision

Tools that make files are rented and named only inside a job that calls them. The repo owns the job contract (`schemas/`), the gates (`scripts/`), and `measure.json`.

## Consequences

Switching a vendor never changes engine docs. Invoices are compared with `measure.json`, not assumed to be progress.
