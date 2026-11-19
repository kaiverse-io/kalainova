# 0029. A song's master is chosen by a person, among options the engine renders and hears blind

Status: accepted · 2026-11-19. The first slice of post-production: vocal level, reference matching and level. Arrangement edits come later. Builds on 0012 (open tools run as commands), 0016 (polish never replaces a lock), 0022 (no paid call until a ready package is signed off), 0024 (learned judges rank takes and never block).

## Context

A song's finish was one fixed recipe: a high-pass at 25 Hz, a cut after the last full bar with a fade, and one gain plus a limiter to −14 LUFS. Nothing in it was a choice, so nothing in it was anyone's decision, and the operator of a studio that makes songs uses no DAW.

What was found before building:

- Release quality is judged against references in the genre at matched loudness. No published spec gives numbers per genre (two independent research passes, 2026-11-19).
- The open mastering tool with the best listening evidence, Matchering 2.0, matches RMS, frequency response and peak to a reference. In one blind test of 472 listeners on one electronic track, it tied for third, behind two human engineers. Its own limiter holds sample peaks only.
- A separation model's stems do not add back to the mix they came from. On a generated 184 s take, the vocal and "other" stems from a Mel-RoFormer model left a residual 16 to 18 dB under the mix: audible, if the stems were summed back.
- True peak rises when a master is encoded as AAC or MP3. One measurement found 2.4 dB on a bright AAC encode, and no fixed headroom is safe for every mix.
- A single transcriber pass over a whole generated mix can fail outright: the same take heard as its lyrics, as unrelated sentences, and as "We'll be right back" seven times.

## Decision

1. **A master is a set of options, and a person chooses.** `kalainova song master <job>` renders each option of one song take as a take of a new `master` shot, beside the others. `kalainova review <job> --blind --shot master` puts them on one page at one loudness, named by letter only. `kalainova take <job> master <n>` records the choice. The choice is the creative decision, and it is on the record as the operator's.
2. **Options are made of a few exact moves.**
   - The take, cleaned as a finished song is (`songs.clean`).
   - The vocal moved by up to 3 dB, as a change added to the mix: mix + (gain − 1) × vocal. A vocal left alone leaves the mix sample for sample, and the stems are never summed back.
   - Matched to a reference track the operator owns, by Matchering run as its own program with its limiter off.
   - A level set by the engine's own oversampled limiter to a profile: `song` (−14 LUFS, −1 dBTP) or `song-loud` (−9 LUFS, −2 dBTP).
3. **Every option is read again once encoded.** Each is encoded as AAC and MP3 and decoded, and its true peak is read. Past −0.1 dBTP is a miss (`master_encoded_true_peak_max`).
4. **Making options never spends.** The stems and the hearing come only from a provider that costs nothing on this machine: a new `separator` provider (python-audio-separator, run as a command), and a free transcriber. When none is ready, the command says so and calls nothing paid. A dozen options must not cost a dozen calls.
5. **A reference is analysed, never copied.** It is a released track the operator bought. Its name and hash are kept with each option it shaped. It is never put in the repo, and nothing of it is in the song.
6. **Words heard do not choose a master.** `--hear` adds the reading, from one free pass over the mix. It is a diagnostic that can fail; the operator's own listening decides.

## Consequences

- The `master` shot sits in `takes.json`, with a `master` record per take: the source take, the vocal move, the reference, the level, the stems' provider, model and residual, what Matchering said, and how the encodes read. A master has no seed (it is `0`), because nothing in it is drawn at random.
- Stems are kept beside the cleaned source and named for its bytes and for the provider and model that split it. Another model splits again rather than reusing them.
- The `mac` provider no longer offers stems when `audio-separator` is not in its environment.
- `kalainova song master <job> --release` makes the chosen master the song's final file and release folder. Only a person's choice is released, and only a master of the song take the song stands on, whose lyric files fit it. The full session file, with every step's choice, comes in the next slice. Arrangement edits (DJ intros and outros, radio edits) come after. The main DJ store does not accept substantially generated music, so they wait until there is a use for them.
- The separation checkpoint and Matchering each have their own terms, listed in `config/studio.yaml` for a release's legal review.
