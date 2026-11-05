# Evals

Two kinds, kept apart.

**Contract eval (running).** `evals/contract/` holds topicless jobs trees. Everything under `pass/` must pass `scripts/check.py`; everything under `fail/` must fail with the text in its `expect.txt`. Run with `just eval`. Broken shape is the test; no fixture has a subject, a golden video, or a made-up URL.

**Content eval (reserved).** It earns a CI job when one real job folder has `status: accepted` or `measured` with a `measure.json` that records where the artifact lives on disk. Until then there is no content eval, on purpose.
