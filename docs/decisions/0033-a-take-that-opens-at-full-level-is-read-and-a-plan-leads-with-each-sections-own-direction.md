# 0033. A take that opens at full level is read as such, and a plan leads each chunk with its section's own direction

Status: accepted · 2026-11-20. Builds on 0031 (a song request in its vendor's form) and 0032 (the writer leads).

## Context

The first take from the creative lead was made on Eleven Music v2.5 as a composition plan, one chunk per section, each section its exact length. The intro asked for a sparse, filtered opening with the kick entering late. The operator's verdict: the take came out in a neighbouring genre rather than the one asked, with no soft start or build-up, at full weight from the first second.

Measured, the intro was the take's loudest section: −8.1 dB RMS from the first second, against −7.9 dB for its loudest 3 s. The later dips the plan asked for did come: the pre-choruses at −12 dB, the breakdown at −14 and the outro at −20. Only the opening was ignored.

The first chunk had carried the whole song's style first, groove words and all, with the intro's note after it. ElevenLabs' schema says the first chunk's styles "set the overall tone and genre". Nothing in the engine read the opening, so QA passed.

The same verdict said the three masters at −3, 0 and +3 dB vocal "all sound the same", as ±1.5 dB had on 19 Nov.

## Decision

1. **A plan's chunk leads with its section's own note.** The song's style still goes on the first chunk, after the note, since that chunk sets the genre.
2. **A section can name what it keeps out** (`avoid` on a section), such as the drums of a soft intro. A plan chunk sends it as that chunk's negative styles, ahead of the song's `avoid`. No model takes it as style, and it is held to the imitation rule. The writer is told about it (`prompts/song_sound.md`).
3. **`song.intro_rise`** is a new reading: the intro's level against the loudest section, its bars placed at the song's tempo, or the first 15 s against the loudest 15 s when the song names no bars. It warns, and never blocks, at more than −3 dB (`song_intro_below_loudest_db`).
4. **The lab makes one master,** at the vocal as made, since vocal-level options are not heard. The repo default is unchanged: it is a studio's setting.

## Consequences

- **The reading separates the takes heard so far:**
  - the two Mureka V9.5 takes the operator accepted read −6.7 and −6.3 dB;
  - an ACE-Step draft reads −7.1;
  - the rejected Eleven take reads 0.0.

  That is four takes. The limit is a first guess, to be held to more verdicts.
- Whether leading with the note, plus the intro's `avoid`, gives Eleven a soft start is not yet heard. It needs a take, which is a person's decision.
- A take drifting into a neighbouring genre is a matter of genre craft, not engine code. The studio's genre notes say how its genre differs from its neighbours.
