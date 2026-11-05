# Multi-model premortem — 2026-11-05

Feedback for the next agent. This file reviews `CLAUDE_HANDOVER.md` and the engine at `6ac72b1`. It is not a new plan, and it is not permission to build the studio in section 7 of the handover.

Nine Cursor models read the same six files: this handover's parent commit, `docs/consolidation.md`, `docs/strategies.md`, `docs/explanation/adversarial-2026-11-05.md`, `ARCHITECTURE.md`, `scripts/check.py`. Ten OpenCode free models were asked and wrote nothing (usage cap).

| Model | Verdict |
|---|---|
| Grok 4.7 | NO |
| Grok 4.6 | NO |
| GPT 5.6 | NO |
| Muse | NO |
| Gemini 4 | NO to handover section 7. YES-IF only if that section is cut and the checker is fixed. |
| Claude Fable | YES-IF, and the IF is not the one in `docs/explanation/adversarial-2026-11-05.md` |
| Claude Sonnet | YES-IF, narrow |
| Claude Opus | YES-IF |
| Composer | YES-IF, weakened |

## What they agree

The shape can stay. One job folder. One of three ways in: a funded cut (`funded-clip`), a master you hold (`owned-derivative`), or a generated piece (`generated`). One distribution identity per way. A human publishes. Rent the tool that makes the file. Own the job folder and the log. No compiler until a real unit exists.

The handover then schedules the failure the earlier premortem already ranked. Section 7 tells the next agent to add ADRs, a how-to, a devcontainer, pre-commit, a skill, and lint, and tells that agent not to open a job. A green repo whose only job is `_template` is what that order ships. Do not build section 7.

## Where the prose and the checker disagree

`scripts/check.py` still allows all seven strategy ids. It does not read `cost_cap` or `skip_funded`. A `measure.json` whose only key is `job_id` passes, and the docs call that file "done." A text URL or a stub can therefore lift the ban on a compiler. `accepted` and `measured` are self-attestation.

`ARCHITECTURE.md` says CI is a gate. GitHub Actions is not on this repo. `docs/explanation/adversarial-2026-11-05.md` still says nothing has been pushed. That sentence was true when it was written. It is false now. Do not treat that file as the current remote state, and do not "fix" it as the only change in a commit.

Day 14 has no start date. A kill with no clock cannot fire. Another review is not a clock.

A public URL is a weaker bar than a funded acceptance. The inherited YES-IF can be met by uploading anything.

## Who wins if nothing is posted

Rented clippers and generators bill either way. People who already post all day take the fresh source during any week spent on cockpit files. The next agent inherits a clean brief and no piece.

## Do not merge

- Another premortem into `docs/`. This file is the one. It stays at the root so it is obvious, and it does not become doctrine.
- A workflow whose only job is the current checker, while the checker still accepts a job-id-only measure.
- A sample job, a made-up URL, or a job an agent opens before the operator names the subject.
- ADRs, a how-to, a devcontainer, pre-commit, a skill, or prompt lint, while `jobs/_template` is the only job.
- `text-pack`, `audio-native`, `procedural`, or `downstream-sku` as the first real job.

## What happens next

The operator still has to name a start date, a weekly hour cap, and which first job (funded cut, owned master, or generated; if generated, a money cap). Until those exist, do not invent them.

The only engine change worth merging before a piece exists:

- A real job's strategy is one of the three peers.
- A generated job needs a numeric `cost_cap`.
- `accepted` or `measured` requires a `measure.json` with a URL or a submission id, plus the 48-hour number.
- Strike section 7 of `CLAUDE_HANDOVER.md` so the next session does not build it.
- Fix the false CI sentence in `ARCHITECTURE.md`.

Then stop. The operator posts or submits. The measure file records the URL or the submission id. If day 14 from the named start date has neither, stop writing engine docs.

Per-model writeups, if you have the operator workspace: `RESEARCH/kalainova-engine-premortem-2026-11-05/`. They are not in this repo on purpose.
