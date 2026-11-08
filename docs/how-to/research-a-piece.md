# How to research a piece

A piece may state a fact only if a source says it, and that is checked by a program.

```bash
uv run kalainova research <job> "What do we need to know?" --query "a narrower search"
```

This reads what the listed search providers find, keeps a private snapshot of each source, and writes `research.json`. Wikipedia and OpenAlex need no key. Exa needs `EXA_API_KEY`.

With a model listed, findings are drafted for you. Without one, write them yourself in `research.json`:

```json
{
  "id": "f1",
  "statement": "The fact, in plain words.",
  "source_ids": ["s01"],
  "quote": "The exact words from that source."
}
```

Then check them:

```bash
uv run kalainova research <job> --check
```

A finding whose quote is not in a source it cites is marked as failed, whoever wrote it. Copy the quote and do not paraphrase it. When a page cannot be fetched, such as a PDF, paste its text into a snapshot file named by `snapshot`.

Planners and writers only see findings that passed. In `script_packet.json`, each claim names its finding:

```json
{"id": "c1", "statement": "...", "source": "https://...", "finding": "f1"}
```

With research on file, a claim with no checked finding fails QA. Put what the sources could not establish under `gaps`, so nobody states it.

This shows that a source says a thing, not that the thing is so. A person still reads the piece.
