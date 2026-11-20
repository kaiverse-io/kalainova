# How to make a song

## Write it

Make a job with `"media": ["song"]`. A model writes `song.json` from the brief when one is listed: an API key's (`anthropic`), or a subscription's command line (`cli`: set `KALAINOVA_LLM_CLI` to Claude Code's `claude`, to `codex`, or to both separated by `:` so one at its limit passes to the other, and list `cli` under `preference.llm`; what it is asked leaves the machine for that vendor). Otherwise write it yourself:

```json
{
  "schema_version": "0.1",
  "job_id": "<id>",
  "title": "<title>",
  "style": "a short brief: genre, emotion, rhythmic feel, the voice, core instruments with their roles, texture",
  "bpm": 96,
  "duration_sec": 150,
  "pronounce": {"<an uncommon word the lines sing>": "<how it sounds>"},
  "sections": [
    {"kind": "verse", "lines": ["..."], "style": "a few words: what changes here", "visual": "what a lyric video shows here"},
    {"kind": "chorus", "lines": ["..."], "style": "how this section differs"}
  ]
}
```

Describe a sound. A style asking to imitate a named person is refused before it reaches a model. Words are original, and no real person's voice is ever used.

Name only what you want in `style`: a model hears every sound the style names, so "no autotune" asks for autotune, and a style that says "no", "without" or "never" is refused before spend. What to keep out goes in `avoid`. The same holds for each section's `style`, since it is sent too.

Write `style` as a short production brief rather than a list of keywords, in the order Mureka's own prompt guide gives: genre, emotion, rhythmic feel, the voice (its timbre, how close it sits, clear diction), the core instruments each with its role, and the production texture. Keep the few traits that matter most clear. When a take drifts, cut words rather than add them. The tempo and key go in `bpm` and `key`, and reach the model as numbers after the style.

Say how the track moves in each section's `style`, in a few words. Two takes of a style that fixes one groove "throughout" come back with the same beat. Where each note goes depends on the model:
- a model whose row in `audio_models` has `section_notes: tags` (Mureka) reads each note on its lyric tag, as in `[Verse] restrained and intimate`;
- any other model reads the notes after the style, in song order.

`pronounce` lists each word or name the lines sing that is not of the song's language, with how it is said. It reaches the model in the style, and a word no line sings is refused.

The engine's writer is held to all of this. A draft whose style runs past 450 characters, names a tempo, or has a section note past 80 characters is written again. `vocal_gender` (`female` or `male`) goes to a model that takes it as its own setting (Mureka). `words_by` says who wrote the words (`person`, `model`, or `person_edited_model`): the release's AI record is read from it, and the engine's writer sets `model`.

## Choose a genre

A genre profile is the studio's notes on a genre, kept in the private config under `genres:`:
- where the genre usually sits: a tempo range, keys, a usual arrangement with bar counts, base style words, what to keep out, and the voice;
- the song model and how many takes, which the engine pins unless the brief already does;
- `holds`: the few of `bpm`, `key`, `vocal_gender` and `structure` that every song of the genre must keep. A song file outside them is refused before spend. The rest is the writer's to choose.

Name a genre when the job is opened:

```sh
kalainova new <id> --identity <id> --subject "<brief>" --media song --genre <genre>
kalainova request <stream> "<brief>" --media song --genre <genre>
```

A stream that makes audio can be asked for a song.

## The writer leads

The writer is the song's creative lead (ADR 0032). From the person's brief it decides what this song is:
- its idea and the one device a listener remembers it by;
- its sub-style and sound;
- its tempo, key and length;
- its own arrangement and groove;
- how it is sung.

It writes that decision in `concept`, then the song. The engine adds no ideas of its own. It makes what the song file says, and refuses only what cannot go.

The writer is shown:
- the profile, as ground to lead from rather than a template;
- the artist's voice and canon from the stream's kits;
- the lengths the pinned model makes;
- the stream's songs so far, newest first, with their concept, tempo, key, sections and sound, so the new one stands apart from them.

A draft is told what is wrong and written again, up to three times, when it:
- breaks the song's rules;
- leaves what its genre holds;
- asks for a length the model does not make;
- repeats an earlier song of the stream, with the same tempo, key and run of sections, or the same title.

## Choose an engine

Pin one in the job's `providers`, for example `{"song": ["mac"], "transcribe": ["mac"]}`.

| Engine | Provider | Cost | Note |
|---|---|---|---|
| HeartMuLa, ACE-Step | `mac` | Free | Its own environment. See `docs/how-to/run-models-on-a-mac.md` |
| A hosted app | `spaces` | Free, rate limited | Needs the `spaces` extra. The lyrics leave this machine, and the app's terms need reading |
| Eleven Music | `elevenlabs` | Rented | Takes a section-by-section plan |
| MiniMax Music | `fal` | Rented | A style prompt plus tagged lyrics |
| Mureka V9.5 | `mureka` | Rented (`MUREKA_API_KEY`) | Mureka's own API: lyrics of up to 5,000 characters, with each section's note on its tag, plus a style prompt of up to 1,024 characters; 120 to 300 s; one song a call, the WAV kept. A weak section is sung again by region edit (3 to 30 s, on V8) |
| Mureka V9 | `mureka` | Rented | V9.5's request without a length: the model sets it |
| Mureka V9.5, V9 | `fal` | Retired | fal answers 410 for both since 2026-11-20, billing nothing; a pin or a plan naming them is refused, and pointed at `mureka` (ADR 0035) |
| Eleven Music v2.5 | `elevenlabs` or `fal` | Rented | A plan of one chunk per section: its words, its length from its bars at the song's tempo (3 to 120 s), its note as direction, how its uncommon words are said, and `avoid` on every chunk; a seed. Both hosts send the same plan. Streaming a take needs ElevenLabs' Creator plan or higher |
| Lyria 3.5 | `fal` | Rented | One prompt of up to 5,000 characters: the style, then each section under a marker timed from its bars (`[0:16-0:48] Verse: its note`). Sings English, German, Spanish, French, Hindi, Japanese, Korean and Portuguese; returns MP3 |
| Lyria 3 Pro | `fal` | Rented | One prompt carries the style and the lyrics; the model sets the length |

To use one model of a provider rather than its default, pin it:
`kalainova pin <job> song mureka:mureka-9.5 --takes 1`. That sets the brief's
`song_model`, the job's song provider and how many takes are made. A provider with no model
(`kalainova pin <job> song mac`) uses that provider's own default and clears any other vendor's
model the brief or its genre pinned. The router sends the
song there and nowhere else. `kalainova rehearse <job>` then writes down each take's request,
with its fields and price, and sends nothing. `kalainova song <job> --write` writes the song file
alone, inside its genre, so it can be read and rehearsed before anything is made.
`kalainova song <job> --write --keep-words` writes only its sound again: the style, what to keep
out, how uncommon words are said, and each section's note. Every line, the tempo, the key and who
wrote the words stay as they were, and the file it replaces is kept in the job's work folder. Use
it on words a person wrote, or to bring an older song file up to the current brief.
`kalainova song <job> --write --again` asks the writer for a new song in place of one nothing was
made from. The new one must stand apart from the old one too. `kalainova song <job> --write
--revise "<notes>"` hands the writer the song and a person's notes to revise it by, keeping what
the notes do not touch. Either way the old song is set aside in the work folder only once its
replacement passes. Once a take is made from a song, open a new job instead. Choose by listening, not by a model's reputation: open one job per
model with the same `song.json`, then hear them blind (below).

### Start from a free draft

A song can be drafted on a free model first, and a rented one asked to follow it. Make the draft as
its own job (ACE-Step on `mac`, say), then open the paid job with the same `song.json` and name the
draft in its brief:

```json
"song_model": {"provider": "fal", "model": "mureka/v9.5/generate/song"},
"song_guide": {"job": "<draft job>", "use": "reference"}
```

- `reference` sends a clip of the draft, cut on a bar where the most words are sung. The model
  takes up its sound and groove. Mureka takes 30 s, and the upload costs a cent. Mureka takes no
  style text with a reference, so the clip alone sets the sound.
- `remix` sends the whole draft, to be sung and produced again from the words and the style
  (`mureka/v9.5/song/remix`).

The engine refuses before spending when the model takes no such track, the draft has no finished
song, or the draft is not `owned` or `licensed`. Both files are kept by their hash in the song's
provenance. Evidence so far: a reference steers melody and drums, and has not been shown to raise
overall quality (ADR 0028).

## Make it

```bash
uv run kalainova song <job>
uv run kalainova takes <job>           # every take, and how each read
uv run kalainova take <job> song <n>   # your choice stands
```

To compare takes, or models, without knowing which is which:

```bash
uv run kalainova review <job> <job> ... --blind           # every take, shuffled, at one loudness
uv run kalainova review <folder> --rank <letters, best first> --reviewer NAME   # once per set
uv run kalainova review <job> <job> ... --judge           # every take scored by the judges
```

The page names takes by letter only, and the copies carry no tags from their source. Which job,
take and model each letter was is kept out of the folder, in `listen-keys/`, and is printed when
the ranking is recorded. A set is ranked once, because a
second ranking would be made knowing the answers.

A judge is a model trained to agree with people about quality (ADR 0024). The engine ships none. Name each one under `judges.song` in your private config: a command that takes `--out FILE` and audio paths, and writes `{path: {score: number}}`. `providers/runners/muqeval_run.py` runs MuQ-Eval (MIT), which scores musical impression from 1 to 5. Set it up with a checkout of its repo, its A1 weights, and an environment with torch, librosa, omegaconf, muq and `transformers==4.46.3`, since newer releases break the muq package. `providers/runners/aesthetics_run.py` runs Audiobox Aesthetics (CC-BY-4.0), which mostly reads production and tells similar takes apart poorly. The first judge's `rank_by` score ranks the takes that pass their readings. With `--judge`, every take of the named jobs is read again with the current readings and the transcript kept beside it (nothing is spent), scored at once, and listed best first, beside what its readings missed. The last line is the engine's pick between the jobs, by the rule that chooses within one: of the takes that pass every reading, the judge's highest; when none passes, it says so and names the closest. Each job keeps its own chosen take until its song is made again. A judge never hears the brief, so a take it likes may not sing the words, and that is what the readings are for.

Give every section an `energy` from 1 to 5: how much it carries, as you plan the song's arc. A take is read against it. `kalainova song-check <job> [--take N]` prints what a take missed of its own plan as cards, each with a time and a fix:
- a section carrying two or more levels off its planned energy;
- a voice where the plan has no words, or none where it has them;
- a key other than the one asked;
- an uncommon word from `pronounce` not heard where it is sung;
- a section whose words were mostly not heard there;
- a steady kick in a section that keeps it out (its `avoid`, or energy 1), or from the first bar of one whose note holds it back ("kick enters late");
- a build the plan steps up from (energy two or more below the next; a pre-chorus, or a note that says it builds) that does not rise into it.

The cards are kept beside the take, and none of them blocks (ADR 0034, ADR 0035). Beside them, `<take>.groove.json` keeps when the kick enters and a syncopation index for each section: readings to rank by once a person's verdicts calibrate them, never limits. Say what a verdict was about with `kalainova verdict ... --reason plan` (or groove, vocal, hook, arrangement, genre, mix), so the readings can be held to it.

A section can name what it keeps out in its own `avoid`, such as the drums of a soft intro; a plan model (Eleven Music v2.5) takes it on that section's chunk (ADR 0033).

A paid model makes one take unless the brief asks for more (ADR 0031): the request is made right instead, and a weak section is repaired rather than retaken. A free model makes more while a reading misses, up to `max_takes`, and readings pick one. Tempo against what was asked, steadiness, how many words can be picked out, whether the chorus can be (`song.chorus_heard`: the share of its lines a listener picks out at least half of), shape, and whether an intro opens below the loudest section (`song.intro_rise`, ADR 0033) all warn and never reject. Only a wrong level on the finished file blocks, because a reading cannot judge a song. Listen to it.

You get `final.wav` at -14 LUFS, `final.m4a`, and `final.lrc` with captions, timed to what was heard when something can transcribe it and spread by length when not. Stems come out when a `separate` provider is listed. The vocal stem is then transcribed as well, kept beside the take as `<take>.vocals.heard.json`, and the finished song's lyric readings are read from it, since a transcriber hears far more of a voice without its band. That is a second paid call, so it needs its own allowance; when no one signed one off, the engine says so, the mix's transcript stands, and QA's `song.lyrics_heard_from` warns. Release files for a distributor (WAV, FLAC, MP3 with tags and a cover) are written beside them: see `docs/how-to/release-a-song.md`. So is `release/ai_use.json`: what AI made, part by part (the words, the music, the vocal, the mastering), and the AI credits a distributor's form is likely to want. It suggests and sends nothing; the person uploading answers the live form.

## Choose its master

The song's master is a choice, not a default. `kalainova song master` renders options of a take,
each a take of the `master` shot, and you hear them blind at one loudness:

```sh
kalainova song master <job> --take 1 --vocal-db=-1.5,0,1.5          # the vocal down, as made, up
kalainova song master <job> --reference ~/refs/owned-track.flac      # matched to a track you own
kalainova song master <job> --level song-loud                        # -9 LUFS, -2 dBTP
kalainova review <job> --blind --shot master                         # hear them, then rank them
kalainova take <job> master 4                                        # the one you choose
```

- Nothing here spends. Stems come from a separator on this machine and `--hear` from a free
  transcriber; when neither is ready the command says so instead of calling a paid one.
- A vocal is moved by at most 3 dB (`song_master.vocal_db_most`): past that, a separated
  vocal's artefacts are heard.
- A reference is a released track you bought. It is analysed only, never copied into the song,
  and its name and hash are kept with the option.
- Each option is read again once encoded as AAC and MP3, because true peak rises in a codec.
- `kalainova song repair <job> --section chorus` sings one section again. On a model whose row
  names an edit route (Mureka on fal), it goes to that route with the section's words, by the
  take's own id when the vendor made it, at $0.10 an edit. A paid repair needs a package like any
  paid call.
- `kalainova song master <job> --release` makes the master you chose the song's `final.wav` and
  its release folder, and moves the render stamp to it. A master the readings picked is not
  released, and nor is a master of a song take the song does not stand on.
- `--hear` adds words heard, from one pass of a transcriber over the whole mix. On a generated
  take that pass can fail outright ("We'll be right back", seven times), so do not choose a master by
  it. Write down what you hear instead.

## Give it a picture

```bash
uv run kalainova song-video <job> <new id>
uv run kalainova make <new id> --from assets
```

This opens a job with a shot for each lyric line, starting on the beat, the track unchanged, and the lyrics as captions. It is landscape unless `--profile` names another, and a short (`--excerpt`) is `short-9x16`. Add `--stills` for stills instead of generated clips.

A track with few or no lyric lines is cut to its music instead. Bars are four beats. A phrase is 8 bars, or 4 where the energy is high (`--phrase-bars N` fixes it), a section that names its `bars` in `song.json` starts a shot, and the biggest rise in energy gets a cut where the drop lands. If the detector finds no steady pulse, the command says so and stops; it never cuts on a guess. With no clear energy peak it still cuts on phrases and says there is no drop.

Whether the cut follows the lyrics or the music, no shot is shorter than about a bar unless the whole piece is: a lyric line heard in passing, or a sliver at an excerpt's edge, joins the shot before it. A shot with a character in it is then split into whole bars from another angle (wide, close, medium), so it never runs past `character_shot_max_sec`. Where that split would leave less than a bar at the end, the last two pieces share their time on the bar nearest the middle instead.

Without a shot list, each shot's picture comes from the `visual` of its section in `song.json`, or else from the song's style. That describes the music, not a shot. To direct the shots, write a shot list and pass it with `--shots <file>`:

- one shot per line, in order, repeated when the cut has more shots than lines;
- `#` starts a comment;
- a line that starts with `B-roll:` is a shot with no character in it, so it is made from its still alone, with no face references;
- a line that starts with `Sings:` is a shot where the character sings. It is made in one call from its still and its line of the song's vocal stem, by a model that moves the face, the mouth and the body with the voice (`sing_models` in `config/studio.yaml`, ADR 0025). Nothing is lip-synced afterwards. The song needs stems: list a `separate` provider in its job before `kalainova song`. Without them the command refuses before it opens the video job. Name a framing that shows the mouth, such as front or three-quarter, and keep hands and the mic away from it. A shot made as a still does not sing, and the estimate prices each singing take as one sung call. The engine places them: the list's `Sings:` lines go to the moving shots that the vocal stem says are sung at least half the way, the longest first, as many as the list would have had in order, and the other lines fill the rest in order. When it is made, a planned singing shot is sung even if the excerpt's own stem reads it as sung under half the way, since the plan measured it against the whole song. Only a line with almost no voice in it is made as a plain clip.

To choose the model that sings, bench one singing shot: `kalainova bench <job> <shot> --models <model>,<model>` gives each the same still and line ([How to bench models](bench-models.md)). With `judges.lipsync` set, each take is scored on how its lips follow the line: `providers/runners/syncnet_run.py` runs SyncNet (MIT) from a checkout of `joonson/syncnet_python` and its two weight files, in their own environment. It gives a confidence (higher follows the line more closely), a distance (lower), and the offset between picture and sound in frames (0 is in sync). It was trained on speech, so compare takes of one line with it rather than reading it as a pass mark. A second judge, `providers/runners/mouth_run.py`, reads the same clip more plainly: MediaPipe's face landmarker (Apache-2.0) measures how far the mouth opens in each frame, and it reports how closely that follows the line's loudness and at what lag. A held note reads low on it, so it is a second opinion beside SyncNet, not a replacement. Only the first judge's `rank_by` ranks takes. Once a sung take is placed, its picture is slipped by the offset the judge measured, so lips that a model returned a few frames late or early land on the line; the clip keeps its length and nothing is redrawn. The bench's `bench/<shot>.mp4` shows each take slipped the same way.

```text
over the shoulder: her hands on the mixer, the crowd lit behind her
B-roll: close on the faders and the jog wheel, lights pulsing
Sings: front, waist up: she sings the hook to the crowd, one hand raised
```

A listed shot names its own framing, so the split adds no angle to it.

For a short, `--excerpt SECONDS` takes a stretch of that length, or `--start SECONDS` takes it from the nearest bar line. For a sung song with a vocal stem, the stretch is where most of the song's words are heard sung, a chorus word counting double, and then where the voice is on longest. That holds whether or not anyone sings on screen, and it needs no energy peak. An instrumental, or a song with no stem, takes the strongest stretch. The stretch starts and ends on bar lines, is cut from the mastered file with a short fade at each end, and is levelled again for the profile. Shots, seconds and the estimated price are printed first, with any key the paid run still needs; the command refuses if the estimate passes `cost_cap`. `kalainova rehearse <new id>` then shows every request and its price before anything is spent ([How to rehearse a paid run](rehearse-and-review-takes.md)). A track longer than 90 seconds defaults to stills with camera moves and a few moving shots, so the price stays inside a cap. Generated motion does not follow a tempo and is not promised to: the edit supplies the feel, and QA's `edit.cuts_on_beat` warns when cuts drift off the beat grid. `work/music_cuts.json` records each cut's distance from the nearest beat.
