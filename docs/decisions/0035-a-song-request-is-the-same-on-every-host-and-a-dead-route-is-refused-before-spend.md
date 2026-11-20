# 0035. A song request is the same on every host, a dead route is refused before spend, and the writer weighs what studies of listeners found

Status: accepted · 2026-11-20. Builds on 0023 (vendor-neutral providers), 0031 (a song request follows its vendor's guide), 0033 (a plan leads with each section's own direction) and 0034 (a take is read against its own plan).

## Context

The goal is a song that holds up beside released music, made in one paid take. The paid take is only as good as what is sent, so what is sent decides it. Five things got in the way.

- **A host changed the request.** ElevenLabs' own adapter built its composition plan from line counts, with the song's whole style on every chunk. fal's route to the same model used `song_text.plan`: bars at the tempo, each section's own note first, and the style on the first chunk only. Moving a model to another host changed what the model was asked.
- **A pronunciation hint reached the wrong section.** `pronounce` travelled inside the style, and a plan sends the style on its first chunk. A second-language word sung four sections later was sung as an English one.
- **fal retired its Mureka song routes** (a 410, billing nothing), although its catalog still listed them. Only a paid submit found that out. Mureka V9.5 is the best-ranked vocal model reachable by API.
- **The producer's verdict on the last take was "no soft start or build up, just bam bam bam from the first second".** The intro's note said "kick enters late", and nothing read the kick.
- **The research on what listeners like was used only after spending.** It read takes, and never reached the writer that decides the next song.

## Decision

1. **One request per model family, whatever the host.** Every host of a composition-plan model builds the plan in `song_text.plan`, and ElevenLabs' own adapter now sends `seed` and `force_instrumental` as fal does. A model with Mureka's request form is sent the request `fal_song` builds from its host's own rows, so fal and Mureka's API send the same request.
2. **A pronunciation hint goes on the chunk that sings the word.** `SongRequest.pronounce` carries the words and how each is said. It is keyed into the content key only when set, so a take paid for earlier keeps its key.
3. **Mureka's own API is a song provider** (`providers/mureka.py`, `MUREKA_API_KEY`):
   - `n: 1`, since each song is charged;
   - `wav_url` first, then `flac_url`, then the MP3;
   - the vendor's song id is kept with the last day an edit can name it (`song_id_until`, a month). After that day a repair uploads the take instead;
   - region edit is the repair route, from 3 to 30 s;
   - what the published spec refuses is refused before sending: its limits, its models, and which controls combine;
   - prices come from the pricing page, and the balance is read in cents.
4. **Lyria 3.5 on fal is a song route.**
   - `section_notes: timestamps` writes each section under a timed marker, its span from its bars.
   - A row's `languages` refuses a song in a language its model does not sing.
   - `prompt_max_chars` holds the style and the words together.
5. **A dead route is refused before spend** (`providers/retired.py`):
   - An HTTP 410 is a `RetiredError`. The router writes the route into the studio's `retired.json` the first time it sees one, and refuses it from then on, before pricing, reserving or asking for a sign-off. A rehearsal and `kalainova pin` refuse it the same way.
   - A config row can carry `retired` and `instead`, so every studio knows. fal's two Mureka song routes now point at Mureka's API.
6. **A take's groove is read against its plan** (`bar/groove.py`, printed by `song-check`):
   - **Kick card.** Raised for a steady kick in a section that keeps the kick out: by its `avoid`, or by energy 1. It is also raised for a kick from the first bar where the section's note holds the kick back.
   - **Build card.** Raised for a planned build that does not rise into the section it steps up to. Rise is checked against a straight ramp (Biliousis and Dahl 2026).
   - **Readings kept beside the take:** when the kick enters, and a Longuet-Higgins and Lee syncopation index for each section. These are readings, never limits, until verdicts calibrate them.
7. **A verdict can carry a reason label** (`verdict --reason`): plan, groove, vocal, hook, arrangement, genre, mix, picture, motion, lips or unclear. This gives the later fit of models and verifiers against verdicts the data it needs.
8. **A package carries the terms of what it pays**, as the studio's licence table holds them when the package is built: the page a person read, the day they read it, and what it asks. The sign-off sheet prints them. A vendor nobody has read says so.
9. **The writer weighs what studies of listeners found** (`prompts/song_writer.md`). The prompt presents it as evidence, never as a form, and a song may go against any of it on purpose:
   - a middling amount of syncopation;
   - one well-placed harmonic surprise;
   - a hook repeated exactly, with the voice forward;
   - a build that says what rises, bar by bar;
   - a soft opening that says so in its own note and in its `avoid`.

## Consequences

- **Proved at $0:** the groove card reads the take that drew the "bam bam bam" verdict as "planned: the kick enters late; measured: a kick from its first bar, on 79% of its beats", entering at 0.09 s.
- **Not yet heard in a take:** the per-chunk pronunciation, the plan order of 0033 and the writer's evidence. One planned comparison settles them: the same song file, one take each, on ElevenLabs' API, Mureka's API and Lyria 3.5.
- Mureka's region edit runs on V8, an older model than the V9.5 take it repairs. Every join has to be heard.
- Lyria 3.5 returns MP3 only, so a master made from it is lossy at its source. Its licence row says so.
- ElevenLabs' section repair (inpainting) is not built. It waits for an account that has it.
- A studio needs `MUREKA_API_KEY` and a $10 recharge for Mureka's API. It needs an ElevenLabs key on the Creator plan or higher before an ElevenLabs take can be streamed.
