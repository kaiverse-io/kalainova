# 0009. Kits hold what stays the same; streams hold where it goes

Status: accepted · 2026-11-06. Amends 0001. Supersedes 0003 for building multiple streams.

## Context

Generated pieces drifted by construction: each shot started from text alone, so the same character got a new face each time. The operator runs many channels and many characters and asks for a piece on any of them. Modelling each of these as its own type would give several pipelines for one problem.

## Decision

Three objects, none of which names a subject:

- **Kit.** A versioned, frozen bundle of what must stay the same: face, looks, voice, persona, places, props, style, music, format, topic rules. The engine reacts to what a kit holds, not a label.
- **Stream.** One identity, one strategy, its kits by exact version, its generators, its limits, and its canon. A channel, an account, and a series are all streams.
- **Job.** One piece, as before. It adds a stream and `kit.lock.json`, which records exact versions and hashes.

`consistency.RULES` is the one table of how each kind of fixed thing is applied and checked. Nothing about it is configured per channel.

Rules: a job cannot override a kit; two kits cannot fill one slot; a frozen version never changes, and a new version moves no existing job; the pinned generator must take references or the request stops before spending; there is no provider fallback for a pinned capability; one identity belongs to one stream.

A kit with a face or a persona must declare an invented, adult, fictional character, attested by a named human. A check cannot prove a face is not a real person's, so the attestation and the human gate carry that, with the vision judge as a further signal.

The operator chose to build for many streams from the start, so the engine no longer holds a second character or stream behind a first measured unit. A schedule still renders nothing up front: a slot becomes a job only when requested, and every job passes the human gate.

A restricted tier is one off-by-default stream flag. A named human turns it on, its output is a file for a person to place, and the engine never posts it. It is not a second pipeline, and the engine's prompts refuse sexual content on every stream. Chat, subscriptions, payments, age checks, and third-party platforms stay outside this repo.

## Consequences

`scripts/check.py` validates kits, streams, locks, schedules, and canon. Reference quality is a vendor claim until a real render tests it.
