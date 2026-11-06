---
name: open-a-job
description: Open a Kalainova job folder for a piece the operator asked for, keeping the subject out of engine docs. Use when asked to start, open, or set up a job or a piece.
---

# Open a job

0. If the piece belongs to a channel or a character, use the `run-a-stream` skill instead.
1. Read `docs/strategies.md`. Ask the operator which peer if he has not said: `funded-clip`, `owned-derivative`, or `generated`. One per job.
2. Follow `docs/how-to/open-a-job.md` exactly. The subject, brief, and sources go only in `jobs/<id>/`.
3. Never edit `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `docs/`, or `schemas/` to mention the subject.
4. Run `just ci`. Fix shape errors; do not weaken a gate to pass.
5. Stop at the gate. Do not upload, submit a campaign URL, or write a `measure.json` with a URL you did not see.
6. Tell the operator what is ready and what he has to do next (render with the rented tool, veto the hook, publish).
