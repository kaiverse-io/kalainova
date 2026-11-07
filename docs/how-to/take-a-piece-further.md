# How to take a piece further

## Open it in an editing system

```bash
uv run kalainova export <job> --to fcpxml   # Final Cut, Resolve
uv run kalainova export <job> --to otio     # Premiere, Resolve
uv run kalainova export <job> --to edl      # anything
```

This writes the cut, not the file, so a person can finish it. The sources stay where they are, and the timeline points at them. Speed changes, grades, and titles are not carried over.

## Cut short pieces from a long recording

Ingest the source first, then:

```bash
uv run kalainova clips <job> --count 3         # chooses moments, into clips.json
uv run kalainova clips <job> --count 3 --open  # and opens a job for each
```

A model chooses when one is listed. With none, the densest whole sentences are chosen, and you can edit `clips.json` by hand. Each clip starts and ends on a word, and needs a transcript. Each is its own job with its own human gate.

## Dub a piece

```bash
uv run kalainova dub <job> <language> <new id>
```

Each line is translated to fit its time, voiced, and laid over the piece's music and effects, so the original voice never leaks through. With no model listed, write `translation.json.<language>` in the job. The result is a new job with its own gate. A voice model has to support the language: check it, and listen.

## Make the record

```bash
uv run kalainova provenance <job>
uv run kalainova ledger <job> --invoice <amount>
```

`provenance.json` says what made each asset, with which weights and seed, what its licence asks, and what people decided. The ledger's numbers are estimates from `config/studio.yaml`, and the vendor's invoice is the truth, so record it and see the gap. Read each model's terms before release. This is a record, not legal advice.
