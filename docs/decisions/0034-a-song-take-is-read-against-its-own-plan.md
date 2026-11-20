# 0034. A song take is read against its own plan, and what it missed becomes a card with a time and a fix

Status: accepted · 2026-11-20. Builds on 0032 (the writer leads a song's creative choices) and 0033 (a take that opens at full level is read).

## Context

The operator asked for "smart and innovative" verifiers grounded in the research on what makes music good. A brief went to two outside research passes, Codex and Cursor; their reports, a combined plan and an audit of Gemini's own synthesis sit in the studio's review folder for 2026-11-20.

**What both reports found:**
- The literature supports diagnosing specific faults, not one score for excellence.
- Learned judges track the quality of the signal rather than the structure. The operator's picks agree.
- Medium syncopation (Witek 2014) and uncertainty × surprise (Cheung 2019) have links to pleasure, but only within their own stimuli.
- Golden-ratio climaxes, "ear candy every 2–4 bars", and 1/f or Zipf as targets are lore or contested.

**What they agreed to build first:** a take judged against its own plan.

**Three things the engine could not see:**
- A take could ignore its arc: today's take opened at full weight, though its intro was planned as a filtered motif.
- A take could ignore its key: it sounds in F major, though F minor was asked.
- A take could miss an uncommon word: a second-language word was sung as an English one in the first pre-chorus.

## Decision

1. **The writer states the arc** as `energy` on every section, from 1 to 5. It is a creative choice, and a fresh draft must give it. The engine adds no shape of its own: it reads the take against the energy the writer chose.
2. **`bar/plan.py`** reads a take at its planned sections, each section's bars placed at the song's tempo:
   - each section's level, low end, brightness and onset density;
   - how closely its weight follows the planned energy (Spearman's rho);
   - a voice only where there are words, from the vocal stem;
   - the key heard against the key asked, using the Krumhansl–Kessler profiles: the relative key counts as half, and a weak fit is marked uncertain;
   - each word the song file says how to pronounce, where it is sung; a word heard as its pronunciation counts;
   - each section's own words, heard inside its span.

   It is pure numpy, reaches no model, and takes under a second for a three-minute take.
3. **Two new readings on every take,** which warn and never block: `song.energy_follows_plan` (rho ≥ 0.5) and `song.key_match` (≥ 0.5).
4. **`kalainova song-check <job> [--take N]`** prints cards and keeps them beside the take (`.cards.json`). Each card gives:
   - what was planned;
   - what was measured;
   - the time;
   - the fix: repair the section by region edit, retake, or listen.

   A plan miss is a card, not a block. With one paid take, a block saves nothing; a card names the next step.

## Consequences

- **On today's take,** `song-check` raised three cards: the key, the uncommon word not heard where it is sung (with the word heard instead), and the pre-chorus's words. Its earlier pronunciation false alarm, a word transcribed as its pronunciation spelling (the word said right), is gone.
- **The limits are first guesses.** They are to be held to verdicts. The combined plan sets the order: about 10–20 clear cases for a card's precision, and 50–100 pairwise verdicts before a craft feature ranks.
- **Still to come:**
  - Phase 2, in their own environments: section boundaries from all-in-one (MIT), syncopation on the drum grid, vocal pitch for hook recurrence, vocal unmasking.
  - Phase 3: genre fit, using the Essentia styles (non-commercial models) and owned reference tracks, and sameness across the stream's songs.
