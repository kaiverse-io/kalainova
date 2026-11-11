# Evals

Two kinds, kept apart.

**Contract eval (running).** `evals/contract/` holds topicless jobs trees. Everything under `pass/` must pass `scripts/check.py`; everything under `fail/` must fail with the text in its `expect.txt`. Run with `just eval`. Broken shape is the test; no fixture has a subject, a golden video, or a made-up URL.

**Content eval (reserved).** It earns a CI job when one real job folder has `status: accepted` or `measured` with a `measure.json` that records where the artifact lives on disk. Until then there is no content eval, on purpose.

**Review set (private, built by you).** The studio bar's limits are only as good as the verdicts they were checked against. A verdict is a person's `kalainova verdict` on a piece or one shot, written to `verdicts.jsonl` in that job's folder under `$KALAINOVA_HOME`. That folder, and the media it points to, stay out of this repo: it is public, and it never holds media or a reference image. What the repo holds is the tools that read the set. `kalainova review-set` prints every verdict beside the readings it can be held against, then how many accepts and how many others each reading has. Below three of each it says "not enough yet" and draws no conclusion. A shot verdict is also paired with what that shot's own clip reads, as `shot.source_motion`. Nothing here changes a limit: when a reading separates or never does, propose the change in an issue with the table attached (ADR 0011). See `docs/how-to/check-a-provider-live.md` for the other half, proving adapters against live services.
