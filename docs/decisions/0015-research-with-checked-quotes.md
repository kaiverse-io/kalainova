# 0015. A fact is usable when its quote is found in its source

Status: accepted · 2026-11-07.

## Context

Inventing a factual claim is a hard rule, and models are good at it. The engine checked only that a claim named a URL, and a model can invent a URL as easily as a fact.

## Decision

- Research keeps a private snapshot of each source's text, as it read when it was fetched.
- A finding states a fact and quotes its source, word for word. A program checks that the quote is in a snapshot of a source it cites. A finding that fails is thrown away, whoever wrote it.
- A model may draft findings. It never decides they are true.
- Writers and planners only see findings that passed. With research on file, a claim with no checked finding fails QA.
- With no model, the agent writes findings by hand and they are held to the same check.
- Snapshots stay in the job folder, which lives in the private home.

## Consequences

A true quote can still be misread, and a source can be wrong, so a person still reads the piece. A quote check cannot read a PDF or a page that needs a browser, and such a source needs its text supplied. This checks that a source says a thing, not that the thing is so.
