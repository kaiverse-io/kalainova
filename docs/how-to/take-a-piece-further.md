# How to take a piece further

## Open it in an editing system

```bash
uv run kalainova export <job> --to fcpxml   # Final Cut, Resolve
uv run kalainova export <job> --to otio     # Premiere, Resolve
uv run kalainova export <job> --to edl      # anything
```

This writes the cut, not the file, so a person can finish it. The sources stay where they are, and the timeline points at them. Speed changes, grades, and titles are not carried over.

## Cut short pieces from a long recording

A cut needs a record of what it may use. Before `clips` will run, the job's `brief.source` names where the file came from (`origin`) and the file in the job folder that covers its use (`reference`: the brief, or the licence):

```json
"brief": {"subject": "<what the piece is about>", "source": {"origin": "<who supplied the file>", "reference": "brief.md"}}
```

The engine does not fetch a source. The file is the one the brief provides. Ingest it first, then:

```bash
uv run kalainova clips <job> --count 3         # chooses moments, into clips.json
uv run kalainova clips <job> --count 3 --open  # and opens a job for each
```

A model chooses when one is listed. With none, the densest whole sentences are chosen, and you can edit `clips.json` by hand. Each clip starts and ends on a word, and needs a transcript. A start inside a sentence moves to that sentence's first word, and opening fillers ("so", "um", "you know") are dropped, with no model. Each is its own job with its own human gate. A clip keeps its parent's brief, rights, identity and stream, carries the source's hash and a copy of the reference file, and says in `crop_basis` what its crop came from: `motion_centre` is where the picture moves in the scored shots, which is not a face. A clip of real footage is approved and posted without the generated-media label.

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

Options on `--open`:

- `--hook-card` opens each clip on a drawn title card of its title (1.6 s), and `--close-text TEXT` ends it on a 2.5 s card with that text. Both are drawn by the graphics provider, which needs Node 22 or newer and calls no service. The clip's words move past the opening card.
- `--crop face` asks a face detector first and falls back to the motion centre. The engine ships no detector. Name one in `config/studio.yaml` as a command: `clips: {face_command: ["your-detector", "{source}", "{start}", "{end}"]}`. It must print one JSON object, `{"x": 0.42}`, the face's horizontal centre from 0 to 1. `crop_basis` then says `face`. With no command, or a command that fails, the crop stays the motion centre.
