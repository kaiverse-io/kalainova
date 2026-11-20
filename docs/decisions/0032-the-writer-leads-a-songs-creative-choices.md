# 0032. The writer leads a song's creative choices, and a genre profile is ground to lead from, held only where the studio says

Status: accepted · 2026-11-20. Amends 0030 (a song is made inside its genre's profile). Builds on 0031 (a song request follows its vendor's prompt guide).

## Context

Under 0030 every song of one genre was the same song with new words:
- the profile fixed the arrangement, the same ten sections and bar counts every time;
- the base sound, the voice and the length were fixed;
- the tempo could move inside a six-bpm window, and the key among six;
- the writer saw no other song, so nothing stopped it from repeating one.

The operator heard this before it was named: "all 6 have the same type of beats". They then asked for the reverse. The agent that hands the engine its input takes the creative role, and tailors each fresh song to the person's input. The engine works from that, with no fixed pattern.

This also follows the line the studio already draws: the engine is a deterministic tool, and the models and agents make the creative choices.

## Decision

1. **The writer is the song's creative lead** (`prompts/song_writer.md`). From the brief it decides:
   - the idea, and the device a listener remembers;
   - the sub-style and sound;
   - the tempo, key and length;
   - its own arrangement and groove;
   - the vocal approach.

   It records that decision in the song file's new `concept` field, then writes the song. Whether the writer is a model through `llm` or the agent driving the session, it does the same job, and the engine adds no ideas of its own.
2. **A genre profile is ground, not a template.** The writer is handed it as where the genre usually sits. A profile now `holds` only what the studio names, from `bpm`, `key`, `vocal_gender` and `structure`. Only those are refused before spend. A profile that holds nothing refuses nothing.
3. **The writer sees what it must stand apart from** (`song_lead`):
   - the stream's songs so far, newest first, with their concept, tempo, key, sections and sound;
   - the lengths the pinned model makes (`min_sec` and `max_sec` on its row).
4. **A fresh draft is refused, and written again, only where it cannot go or would repeat:**
   - no `concept`;
   - a length the model does not make;
   - the same tempo, key and run of sections as an earlier song of the stream;
   - the same title.

   Rewriting a song's sound around its own words (`--keep-words`) is not held to these, since its words, tempo and key stand.

5. **A song is written again, or revised, without losing it.** `--write --again` asks for a new song that must also stand apart from the one it replaces. `--write --revise "<notes>"` hands the writer the song and a person's notes. Either way, the old file is set aside only once the replacement passes.
6. **A paid model makes one take unless the brief asks for more** (`songs.SAFE_TAKES`). A free model still makes more while a reading misses.

Outside review (Codex and Cursor, 2026-11-20) found the first build of points 3 to 5 wrong in four places, each now fixed:
- `--again` deleted the song before its replacement passed;
- `--again` let a rewrite clone the song it replaced;
- Mureka's minimum length was checked only at send time, not in `run` and `rehearse`;
- a request's own `--duration` was overwritten by its genre.

## Consequences

- What varies between songs is now the writer's craft rather than the profile's ranges. A weak writer now writes weak songs with nothing to stop it, where before it wrote safe, samey ones. The human gates stay in place: a person hears the take blind, chooses the master and approves the release.
- The refusal of imitation is mechanical too. An artist's name that matches none of its phrases is left to the writer's rules, since no check can tell a name from an instrument's brand.
- The repeat check is mechanical. Two songs can still sound alike with different tempos or arrangements. The stream's list is shown so the writer can do better than the check.
- A studio that wants a fixed artist voice, or a DJ-friendly tempo, says so in `holds`. The lab holds the persona's voice.
- Each song's `concept` is a record of what it was meant to be, kept with the job. A later reading can check whether the take delivered it.
