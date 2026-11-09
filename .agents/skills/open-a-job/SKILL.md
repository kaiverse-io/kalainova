---
name: open-a-job
description: Open a Kalainova job folder for a piece the operator asked for, keeping the subject out of engine docs. Use when asked to start, open, or set up a job or a piece.
---

# Open a job

0. If the piece belongs to a channel or a character, use the `run-a-stream` skill instead. To take one prompt all the way to a finished candidate, use `make-a-piece`.
1. Read `docs/strategies.md`. Ask the operator which peer if they have not said: `funded-clip`, `owned-derivative`, or `generated`. One per job.
2. Follow `docs/how-to/open-a-job.md` exactly. The job lives in `$KALAINOVA_HOME/jobs/<id>/`, never in this repo, and the subject, brief, and sources go only there.
3. Never edit `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `docs/`, or `schemas/` to mention the subject.
4. Run `python3 scripts/check.py --jobs "$KALAINOVA_HOME/jobs"`. Fix shape errors; do not weaken a gate to pass.
5. Stop at the gate. Do not upload, submit a campaign URL, or write a `measure.json` with a URL you did not see.
6. Tell the operator what is ready and what they do next: `uv run kalainova make <job>`, a look at the result, then approving and publishing, which are theirs.
