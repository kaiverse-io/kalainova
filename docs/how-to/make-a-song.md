# How to make a song

## Write it

Make a job with `"media": ["song"]`. A model writes `song.json` from the brief when one is listed. Otherwise write it yourself:

```json
{
  "schema_version": "0.1",
  "job_id": "<id>",
  "title": "<title>",
  "style": "genre, instruments, mood, and the kind of voice, in plain words",
  "bpm": 96,
  "duration_sec": 150,
  "sections": [
    {"kind": "verse", "lines": ["..."], "visual": "what a lyric video shows here"},
    {"kind": "chorus", "lines": ["..."], "style": "how this section differs"}
  ]
}
```

Describe a sound. A style asking to imitate a named person is refused before it reaches a model. Words are original, and no real person's voice is ever used.

## Choose an engine

Pin one in the job's `providers`, for example `{"song": ["mac"], "transcribe": ["mac"]}`.

| Engine | Provider | Cost | Note |
|---|---|---|---|
| HeartMuLa, ACE-Step | `mac` | Free | Its own environment. See `docs/how-to/run-models-on-a-mac.md` |
| A hosted app | `spaces` | Free, rate limited | Needs the `spaces` extra. The lyrics leave this machine, and the app's terms need reading |
| Eleven Music | `elevenlabs` | Rented | Takes a section-by-section plan |
| MiniMax Music | `fal` | Rented | A style prompt plus tagged lyrics |
| Mureka | `fal` | Rented | Lyrics plus a style prompt of up to 1,024 characters; 120 to 300 s |
| Lyria 3 Pro | `fal` | Rented | One prompt carries the style and the lyrics; the model sets the length |

To use one model of a provider rather than its default, name it in the brief:
`"song_model": {"provider": "fal", "model": "mureka/v9.5/generate/song"}`. The router sends the
song there and nowhere else. Choose by listening, not by a model's reputation: open one job per
model with the same `song.json`, then hear them blind (below).

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

Several takes are made, and readings pick one. Tempo against what was asked, steadiness, how many words can be picked out, whether the chorus can be (`song.chorus_heard`: the share of its lines a listener picks out at least half of), and shape all warn and never reject. Only a wrong level on the finished file blocks, because a reading cannot judge a song. Listen to it.

You get `final.wav` at -14 LUFS, `final.m4a`, and `final.lrc` with captions, timed to what was heard when something can transcribe it and spread by length when not. Stems come out when a `separate` provider is listed. The vocal stem is then transcribed as well, kept beside the take as `<take>.vocals.heard.json`, and the finished song's lyric readings are read from it, since a transcriber hears far more of a voice without its band. That is a second paid call, so it needs its own allowance; when no one signed one off, the engine says so, the mix's transcript stands, and QA's `song.lyrics_heard_from` warns. Release files for a distributor (WAV, FLAC, MP3 with tags and a cover) are written beside them: see `docs/how-to/release-a-song.md`.

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
