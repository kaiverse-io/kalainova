# How to release a song as audio files

A finished song leaves `kalainova song` as files a music distributor takes, with no video wrapper. Upload is by hand: the engine never sends anything to a distributor, and the distributor asks its own questions about AI-made music.

## What you get

In `<out>/<job>/release/`:

| File | What it is |
|---|---|
| `final.wav` | 16-bit, 44.1 kHz stereo, from the -14 LUFS master with a triangular dither |
| `final.flac` | The same, lossless, tagged, with the cover embedded |
| `final.mp3` | 320 kbps, ID3v2.3 tags, with the cover embedded |
| `lyrics.txt` | The words with their section tags |
| `lyrics.lrc` | The words timed to what was heard, or spread by length when nothing could transcribe |

`final.wav` in the job's output folder is still the 24-bit, 48 kHz master the checks and the human gate read. The release files are made from it and are not separately checked.

## Tags and a cover

Title and artist come from `title` and `byline` in `song.json`. Add an optional `release` block for the rest:

```json
"byline": "<artist name>",
"release": {"album": "<album>", "year": 2026, "track": 1, "cover": "cover.png"}
```

`cover` is a path inside the job folder. Use a square image of at least 3000 px a side. A smaller or non-square cover still goes in, with a warning in the output and in the asset record, because the distributor's current rule decides. Read it before uploading. Every file is tagged as containing AI-generated media.

## Stems

Stems cost money, so they are off by default. A job opts in by listing a provider that can split them:

```json
"providers": {"song": ["fal"], "separate": ["fal"]}
```

The result is `vocals.wav` and `instrumental.wav` next to the master, recorded in the asset record. The price is by the second of the mix, and the model's own terms need reading before stems are released.

## Length

Some song models state a longest track. When `config/studio.yaml` records it under `audio_models`, a song that asks for more is refused before any call. A model with no recorded limit is not checked, so confirm its limit before a long track.
