# How to open a job

The operator opens a job on his own machine, because the brief, the master, and the publish login are his.

1. Pick **one** peer in `docs/strategies.md`: `funded-clip`, `owned-derivative`, or `generated`.
2. Copy the template and name the folder after the job id:

   ```bash
   cp -r jobs/_template jobs/<id>
   rm jobs/<id>/README.md
   ```
3. Edit `jobs/<id>/job.json`:
   - `job_id` is `<id>` (the folder name)
   - `status` is `draft`
   - `strategy`, `media`, `rights` (`funded-brief` for a funded cut, `owned` or `licensed` otherwise)
   - `distribution_identity` is the label of the account this strategy posts from; never reuse it for another strategy
   - generated jobs: `cost_cap` before the first render; `skip_funded: true` only if you mean it
4. Write the subject, the brief, and any source notes inside `jobs/<id>/` only.
5. If there is a script, add `script_packet.json` with a source for every factual line.
6. Run `just check` (or `python3 scripts/check.py`) and `just lint`.
7. Render with the rented tool. Veto the hook in ten minutes. A human publishes and submits.
8. At 48 hours, write `measure.json` and set `status` to `accepted` (funded, tracking) or `measured`.

Media files stay on disk. Never commit them.
