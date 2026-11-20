---
name: a-plans-first-chunk-sets-the-whole-songs-tone
description: A composition-plan take opened at full level though its intro asked for a sparse start; the first chunk carried the whole style; lead each chunk with its own note, read the take against its plan, and expect key drift
metadata:
  type: feedback
---
A song was made on a model that takes a composition plan, one chunk per section. The intro asked for a sparse, filtered opening with the kick entering late. The producer heard a take in a neighbouring genre, with no soft start or build-up and full weight from the first second. QA passed.

**Measured:** the intro was the take's loudest section (0.0 dB below the loudest). The later dips the plan asked for did come. The take also sounded in the parallel major of the minor key asked (Krumhansl-Kessler fit 0.71 against 0.47), which is a brighter mood than asked. And one uncommon word was sung as an English one in a single section.

**Root cause:**
- the plan put the song's whole style, groove words included, first on the intro chunk;
- the vendor's schema says the first chunk's styles "set the overall tone and genre";
- nothing in the engine read the opening, the key or the plan.

**Fix:**
- `providers/song_text.plan` leads each chunk with its section's note, the style after it on the first chunk, and a section's own `avoid` as that chunk's negative styles;
- `bar/song.intro_rise` reads the intro against the loudest section;
- `bar/plan.py` reads a take against its song file: `energy` per section, voice, key, uncommon words, words per section;
- `kalainova song-check` prints the cards;
- tests: `tests/test_song_plan.py` and `tests/test_song_file_to_release.py`.

**Evidence:** the intro reading separated four takes. Two accepted takes read −6.7 and −6.3 dB, a free draft −7.1, and this take 0.0.

**Status:**
- The readings are proved on these takes.
- The plan-order fix is **unproved**: it needs one take of the same song file, which is a person's decision.

**Also:** two producers' rounds heard vocal-level master options of ±1.5 dB and ±3 dB as the same, so a studio can offer a single master (`song_master.vocal_db: [0]` in its own config).
