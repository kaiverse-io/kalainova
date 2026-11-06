---
name: run-a-stream
description: Make a piece for one of the operator's channels or characters, keeping face, voice, and style fixed. Use when asked for content for a channel, character, series, or stream.
---

# Run a stream

1. Check `$KALAINOVA_HOME` is set and points outside this public repo. If it is not, stop and ask.
2. Run `uv run kalainova stream show <stream>` to see what is fixed. If the stream or character is ambiguous, ask.
3. Run `uv run kalainova request <stream> "<brief>"`, adding `--cast` if the stream has several characters.
4. Run `uv run kalainova make jobs/<id>`. A refusal is a finding, so report it. Do not weaken a kit or a gate to pass.
5. Stop at the gate and show the operator the file, contact sheet, and any QA warnings.

Never run `kit freeze`, set `origin.attested_by`, add canon, or run `approve`: each names a human. Follow `docs/how-to/run-a-stream.md` for setup.
