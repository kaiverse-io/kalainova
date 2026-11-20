# 0031. A song request follows its vendor's own prompt guide: a short brief, notes on the lyric tags, and how uncommon words are said

Status: accepted · 2026-11-19; point 3 amended by 0035 (a hint goes on the chunk that sings the word). Builds on 0029 (a song file reaches its model as written) and 0030 (a song is made inside its genre's profile).

## Context

A paid song gets one take, so whatever that take can be is decided by what is sent. Two things in the request went against what the vendor publishes:

- **The style was long and carried the arrangement.** The writer was asked to say in the style how the track moves, section by section, under 900 characters. A real request ran to 758. Mureka's guide (28 Aug 2026) asks for a short production brief in a set order: genre, emotion, rhythmic feel, vocal direction, core instruments with their roles, section structure, production texture. It says to cut words when a result drifts, and to keep the three to five traits that matter most clear.
- **Each section's own note never reached any model.** The song file has a `style` on each section, and the engine dropped it: the lyrics went out with bare tags. The guide shows such notes on the lyric tags: `[Verse 1] restrained and intimate`.

The guide also asks for pronunciation notes on names and uncommon words, given in the prompt. One fresh song file sings two second-language phrases, and nothing in the request said how either one is said.

Mureka's own test of 100 V9.5 songs found 28% usable overall. A better request raises the odds of one take, but cannot make them certain, so repair by region edit stays the fallback.

## Decision

1. **Each model reads the section notes where it can.** A model row with `section_notes: tags` (both Mureka routes) reads each note on its section's lyric tag. Any other model reads the notes after the style, in song order. The provider puts them in place (`providers/song_text.py`). Release lyrics and LRC files keep bare tags.
2. **A section note is held to the style's rules.** It is sent, so a note that says "no", "without" or "never", or that asks to imitate someone, is refused before spend.
3. **`pronounce` in the song file** maps a word as written to how it is said. It reaches the model inside the style, before the tempo and key. A word that no line sings is refused.
4. **The writer drafts the brief in the vendor's order** (`prompts/song_writer.md`). A draft is written again when:
   - its style runs past 450 characters;
   - its style names a tempo;
   - a section note runs past 80 characters.

   A person's own song file is not held to these limits.
5. **The vendor's limits are refused before sending:** 1,024 characters of style and 5,000 of lyrics for Mureka.
6. **A song's sound can be written again around its own words** (`kalainova song <job> --write --keep-words`, `prompts/song_brief.md`). The writer writes the style, `avoid`, `pronounce` and the section notes. Every line, the tempo, the key and `words_by` stay as they were, and the old file is kept in the work folder. Both writer prompts share one set of sound rules (`prompts/song_sound.md`). This serves words a person wrote, and a comparison of two requests for the same words.

## Consequences

- One paid comparison will show whether the new request beats the old one: the same song, the old request against the new, one take each. Until then, this decision rests on the vendor's guide and has not yet been heard in a take.
- A model that reads notes after the style now gets the arrangement from the sections rather than from a long style, so a song file written before this change sends its arrangement twice to such a model. The writer no longer puts it in the style.
- A cloned voice (`vocal_id`) is the one audio input that keeps the text prompt. The combination rules are prompt with voice, or reference with voice, and never prompt with reference. It is a separate decision, because the voice must be invented and a person must attest it.
