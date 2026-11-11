---
name: run-a-stream
description: Make a piece for one of the operator's channels or characters, keeping face, voice, and style fixed. Use when asked for content for a channel, character, series, or stream.
---

# Run a stream

1. Check `$KALAINOVA_HOME` is set and points outside this public repo. If it is not, stop and ask.
2. Run `uv run kalainova stream show <stream>` to see what is fixed. If the stream or character is ambiguous, ask. A character with no frozen kit yet is looked at first: `uv run kalainova look <kit>` writes a sheet of the candidate references for the operator to choose from. It changes no kit.
3. Run `uv run kalainova request <stream> "<brief>"`, adding `--cast` if the stream has several characters.
4. For a job with a cap, set `brief.animatic_gate` and run `uv run kalainova animatic jobs/<id>` first. The operator watches the rough cut and gives it a verdict before any video is paid for.
5. Run `uv run kalainova make jobs/<id>`. A refusal is a finding, so report it. Do not weaken a kit or a gate to pass.
6. Stop at the gate and show the operator the file, contact sheet, and any QA warnings.

Never run `kit freeze`, set `origin.attested_by`, add canon, or run `approve`: each names a human. Follow `docs/how-to/run-a-stream.md` for setup.
