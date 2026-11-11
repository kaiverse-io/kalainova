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
