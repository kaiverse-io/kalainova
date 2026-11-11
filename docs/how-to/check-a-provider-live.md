# Check a provider against the live service

The tests run on fakes, so nothing in CI shows that an adapter matches a vendor's real reply. `kalainova providers --check` makes the smallest real call each capability supports, once, and says what it found. It costs real money, so it is opt-in on every side.

```bash
uv run kalainova providers --check <provider> --job <job> [--capability video]
uv run kalainova providers --check <provider> --job <job> --spend
```

1. Use a job with a `cost_cap`. The calls go through the router, so the ledger records them and the cap holds.
2. The first command prints each call and its estimated cost, then refuses. Read the estimate.
3. Add `--spend` to make the calls. It never runs when `CI`, `GITHUB_ACTIONS`, or a pytest run is detected, and no recipe in `just ci` calls it.
4. Keys come from the environment, as `connect-a-provider` describes. Nothing prints one.

Each capability reports one of:

- `passed`: the service answered, the engine read the reply, and the file or text is usable. The charge is shown beside the estimate. A gap means the price table is wrong.
- `schema mismatch`: the service answered but the adapter could not read it (a missing field, a wrong shape, an unusable file). The message carries what was wrong. Fix the adapter in the same change and note what the live schema was.
- `not reached`: no answer (key, network, timeout, refusal). Nothing is learned about the schema.
- `unchecked`: no cheap call exists (a whole song, lip sync, stem separation, local rendering).

On a pass, the command prints any line in `config/studio.yaml` still marked `VERIFY` for that model. Remove the mark and put the date in the comment. The command does not edit the config.
