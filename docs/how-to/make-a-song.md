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

## Make it

```bash
uv run kalainova song <job>
uv run kalainova takes <job>           # every take, and how each read
uv run kalainova take <job> song <n>   # your choice stands
```

Several takes are made, and readings pick one. Tempo against what was asked, steadiness, how many words can be picked out, and shape all warn and never reject. Only a wrong level on the finished file blocks, because a reading cannot judge a song. Listen to it.

You get `final.wav` at -14 LUFS, `final.m4a`, and `final.lrc` with captions, timed to what was heard when something can transcribe it and spread by length when not. Stems come out when a `separate` provider is listed. Release files for a distributor (WAV, FLAC, MP3 with tags and a cover) are written beside them: see `docs/how-to/release-a-song.md`.

## Give it a picture

```bash
uv run kalainova song-video <job> <new id> --profile landscape
uv run kalainova make <new id> --from assets
```

This opens a job with a shot for each lyric line, starting on the beat, the track unchanged, and the lyrics as captions. Add `--stills` for stills instead of generated clips.

A track with few or no lyric lines is cut to its music instead. Bars are four beats. A phrase is 8 bars, or 4 where the energy is high (`--phrase-bars N` fixes it), a section that names its `bars` in `song.json` starts a shot, and the biggest rise in energy gets a cut where the drop lands. A shot with a character in it is split into whole bars from another angle (wide, close, medium) so it never runs past `character_shot_max_sec`. If the detector finds no steady pulse, the command says so and stops; it never cuts on a guess. With no clear energy peak it still cuts on phrases and says there is no drop.

For a short, `--excerpt SECONDS` takes the strongest stretch of that length, or `--start SECONDS` takes it from the nearest bar line. The stretch starts and ends on bar lines, is cut from the mastered file with a short fade at each end, and is levelled again for the profile. Shots, seconds and the estimated price are printed first; the command refuses if the estimate passes `cost_cap`. A track longer than 90 seconds defaults to stills with camera moves and a few moving shots, so the price stays inside a cap. Generated motion does not follow a tempo and is not promised to: the edit supplies the feel, and QA's `edit.cuts_on_beat` warns when cuts drift off the beat grid. `work/music_cuts.json` records each cut's distance from the nearest beat.
