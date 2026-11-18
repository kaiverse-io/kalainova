# 0025. A singing shot is sung in the call that makes it

Status: accepted · 2026-11-18. Builds on 0023 (the engine speaks to models in its own terms) and 0024 (learned judges rank takes, and never block).

## Context

A `Sings:` shot used to be made in two passes. A video model made the clip from its still, and a second model then repainted the mouth to the song's vocal stem. Neither pass heard the other. The video model never heard the song, because the character video models on our routes cannot take an audio input. On fal, Kling's reference and image-to-video models take only an on/off switch for sound they make themselves. The second pass could only patch a mouth onto motion that never followed the voice.

Other models make the shot from the voice itself. They take a picture and an audio line, and the face, the mouth and the body move with the voice in one call. These are OmniHuman 1.5, Kling AI Avatar v2, Seedance 2.0 reference-to-video with reference audio, and Wan 2.6 image-to-video with an audio file. There is no published comparison of them on singing.

## Decision

1. **A singing shot is one call.**
   - `SingRequest` in the provider contract carries the shot's still, its line of the vocal stem, its prompt, its aspect, and the kit for a model that takes more pictures.
   - The shot runs as long as its line. A model that makes set lengths is asked for the next one up, as a plain clip is.
   - Nothing is lip-synced afterwards. `lipsync` stays for a line spoken on camera.
2. **Each model's field names are config.**
   - `sing_models.<provider>.<model>` names a model's picture and audio fields. A model that takes several pictures also names how its prompt refers to each picture and to the line.
   - `models.<provider>.sing` is the default, and `preference.sing` lists the providers.
   - Adding a model is a config row.
3. **A `Sings:` span with no voice in the stem is made as a plain clip.** There is nothing for a model to sing.
4. **A sung take is judged on its own line.**
   - With `judges.lipsync` set, the line is laid on the take's picture, and the judge scores how the lips follow it. `providers/runners/syncnet_run.py` runs SyncNet (MIT), which gives a confidence, a distance, and the offset between picture and sound in frames.
   - The score ranks takes and never blocks (0024).
5. **A sung take is slipped onto its line.**
   - Every model on the first bench returned lips a few frames behind or ahead of the voice: Kling Avatar 2 frames late, Wan 2.7 3 frames late, OmniHuman 2 frames early.
   - Slipping the picture by the measured offset brought each to 0, with the same lip-match score.
   - So the lip judge also reports `offset_sec`. Once a sung take is placed, its picture starts that far in when the lips are late, or holds its first frame when they are early (`singing.slip`). The clip keeps its length, and nothing in it is redrawn, as an editor slips picture against sound.
6. **The model is chosen by a bench.** `kalainova bench <job> <shot> --models a,b` on a singing shot gives every model the same still and the same line, and the judge scores each one, so the choice rests on the same evidence for every model.

## Consequences

- A singing shot costs one call, not a clip and a sync. The estimate prices it so.
- A voice-driven model holds the character through its still alone, unless it takes the kit too. Each take's identity check still applies.
- SyncNet was trained on speech. Its scores compare takes of the same sung line; they are not a pass mark for singing. Its offset says plainly whether picture and sound line up.
- Two of the four models are unconfirmed: fal's schema calls Wan 2.6's audio background music, and Seedance's reference audio may guide the video without driving the lips. The bench settles both.
