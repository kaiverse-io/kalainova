# How to open a job

For a piece on a channel or with a character, use `docs/how-to/run-a-stream.md` instead. This page is for a one-off job with no stream.

The operator opens a job on their own machine, because the brief, the master, and the publish login are theirs. Jobs live in the private home named by `$KALAINOVA_HOME` (ADR 0010), never in this repo.

1. Pick **one** peer in `docs/strategies.md`: `funded-clip`, `owned-derivative`, or `generated`.
2. Create it from the template:

   ```bash
   uv run kalainova new <id> --strategy <peer> --identity <label> --subject "<brief>" \
     --media video,audio --rights owned --duration <sec> --cost-cap <usd>
   ```
3. Check `$KALAINOVA_HOME/jobs/<id>/job.json`:
   - `job_id` is `<id>` (the folder name)
   - `status` is `draft`
   - `strategy`, `media`, `rights` (`funded-brief` for a funded cut, `owned` or `licensed` otherwise)
   - `distribution_identity` is the label of the account this strategy posts from; never reuse it for another strategy
   - generated jobs: `cost_cap` before the first render; `skip_funded: true` only if you mean it
4. Write the subject, the brief, and any source notes inside that job folder only.
5. If there is a script, add `script_packet.json` with a source for every factual line.
6. Run `python3 scripts/check.py --jobs "$KALAINOVA_HOME/jobs"`.
7. Run `uv run kalainova make $KALAINOVA_HOME/jobs/<id>` and look at the result. Veto the hook in ten minutes. A human approves, publishes, and submits.
8. At 48 hours, write `measure.json` and set `status` to `accepted` (funded, tracking) or `measured`.

Media files stay on disk. Never commit them.
