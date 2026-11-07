---
name: research-a-piece
description: Gather sources for a Kalainova piece and write findings whose quotes are checked against those sources. Use when a piece states facts, or when asked to research a subject for a script, video, or book.
---

# Research a piece

1. Run `uv run kalainova research <job> "<question>"`, with `--query` for narrower searches. Everything stays in the job folder.
2. With no model listed, read the snapshots yourself and write findings into `research.json` (`docs/how-to/research-a-piece.md`). Copy each quote exactly.
3. Run `uv run kalainova research <job> --check`. Fix or remove what fails. Never edit a snapshot to make a quote pass.
4. Put anything the sources could not establish under `gaps`. Do not fill a gap from memory.
5. In the script, each factual line goes in `claims` with its `finding`. If no finding supports a line, rewrite the line so it states no fact.
6. Say plainly that this shows a source says a thing, not that the thing is so.
