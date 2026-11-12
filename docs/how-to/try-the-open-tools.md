# Try the open beat and word-time tools

Two optional adapters call programs that live outside this repo: `beat_this` for beats and
downbeats, and `whisper-cli` (whisper.cpp) for word times. Both cost nothing and run on the
machine. This page says how to install them, how to point the engine at them, and what was
measured when they were tried on real audio (macOS, Apple silicon, 2026-11-12).

## Install

Keep both outside the repo.

```sh
# beat_this, in its own Python 3.12 environment
uv venv --python 3.12 ~/tools/beat_this-env
uv pip install --python ~/tools/beat_this-env/bin/python \
    https://github.com/CPJKU/beat_this/archive/main.zip soundfile

# whisper.cpp and a ggml model (base.en is 148 MB; small.en is better and slower)
brew install whisper-cpp
mkdir -p ~/models/whisper-cpp
curl -L -o ~/models/whisper-cpp/ggml-base.en.bin \
    https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin
```

`soundfile` is not a declared dependency of `beat_this`, and without it the tool fails with
"Could not load audio" on a plain wav (torchaudio then wants torchcodec). The first run also
downloads the `beat_this` checkpoint into the torch cache.

## Select them

Use a private copy of the config; do not edit a shared one in place.

```yaml
# $KALAINOVA_CONFIG, a copy of config/studio.yaml with these changed
adapters:
  beats: {use: beat_this, command: /Users/you/tools/beat_this-env/bin/beat_this}
preference:
  transcribe: [whispercpp]
```

```sh
export KALAINOVA_CONFIG=~/private/studio.yaml
export KALAINOVA_WHISPER_CPP_MODEL=~/models/whisper-cpp/ggml-base.en.bin
```

The tests marked "real" run when `beat_this` is on PATH and the whisper variables are set.

## What was measured

Beats, `beat_this` against the in-house grid, on two generated songs (a 62 s rap and a 60 s sung
track):

| Track | beat_this | in-house | Reading |
|---|---|---|---|
| sung | 103.45 BPM, 78 beats, 21 downbeats | 102.03 BPM, 77 beats | Same tempo; 82% of in-house beats within 70 ms of a beat_this beat |
| rap | 68.18 BPM, 62 beats, 21 downbeats | 134.85 BPM, 101 beats | An octave apart: the in-house grid ticks twice per beat_this beat; 61% within 70 ms |

The `.beats` file is `<seconds>\t<beat in bar>`, with 1 as a downbeat and 2, 3, 4 counting up,
as the reader assumes. `beat_this` ran in about a second for a 23 s clip. It reads wav, flac,
ogg and mp3 only: an `.m4a` fails with "Could not load audio", so the adapter now decodes every
input to a mono wav first. On a synthetic click track the tool itself crashes ("Not all
downbeats are beats"); the adapter reports that as a contract error naming the command.

Words, `whisper-cli` with `ggml-base.en` on a 62 s narration (180 words) and a rapped verse:

- The JSON fields match the reader: `transcription[].offsets.from/to` in milliseconds and `text`
  with a leading space. Accented words (`Tomás`) and contractions (`day's`) come through whole.
- Times are monotonic, none are zero or negative length, and the last end (61.16 s) is inside the
  clip. Every entry is one word.
- A pause is an empty-text entry, which the reader drops. The pause time is then absorbed by the
  word before it, so a word's end can run late across a pause. The first word is short
  (10 ms) because the leading empty entry takes its start. Treat ends as soft, starts as good.
- Singing and rapping are heard as words. Music markers such as `(soft music)` are dropped.
