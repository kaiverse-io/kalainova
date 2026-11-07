---
kind: reference
status: active
last_reviewed: 2026-11-06
---

# The studio bar

The goal: **a finished piece a premium streaming platform could ingest, and a viewer could not tell from a good human edit.** That has three layers, and only the first two are measurable here.

| Layer | Who decides | How |
|---|---|---|
| Delivery | A tool | `kalainova bar <job>` against published ingest requirements |
| Craft | A tool, then a human | `kalainova bar`, then watching it |
| Taste and acceptance | A human, then the platform | First review, then the platform's own editorial review |

A perfect score shows no measured defect. It does not show the piece is good.

## Run it

```bash
kalainova bar <job or file>
```

It reads any file, including one the engine did not make, so outside work is held to the same numbers. Limits are in `config/studio.yaml` under `bar:`. QA includes these readings, and only a reading that `blocks` stops approval.

It reports two numbers, because they mean different things. **Conformance** is mostly the renderer checking its own work, so it passes on anything it makes. **Craft** is what can go wrong in a piece. A single total would flatter a flat gradient above real footage, which is what it did. A clean sheet shows no measured defect, not that the piece is good.

`kalainova signals` holds every reading against the verdicts people gave. A reading that does not separate good from bad gets deleted (ADR 0011).

## Picture

| Reading | What it catches |
|---|---|
| `picture.banding` | Contours in gradients and dark skies |
| `picture.cambi_peak` | The same fault by the CAMBI banding index, when this ffmpeg has `libvmaf`. About 5 reads as slightly annoying |
| `picture.stutter` | Judder: frames that barely change next to frames that do |
| `picture.detail` | Softness from upscaling or over-compression |
| `picture.repetition` | Shots that look like other shots in the piece |
| `picture.corner_mark`, `source.corner_mark` | A logo or watermark that stays put across shots |
| `edit.moving_share` | Too much of the runtime on stills, which reads as a slideshow. It reads the file type only |
| `source.shot_motion` | A generated clip where almost nothing moves once the camera's pan and zoom are taken out. Names the worst shot. Real footage is not measured, because a quiet shot is a choice. It reads how much of the frame moves, so a generated talking head can miss it, and frozen water behind a moving person only misses it if the person is small. Look at the shot before regenerating it |
| `edit.cuts_per_min` | Choppy cutting |
| `source.scale` | A source too small for the delivery size |

## Sound

| Reading | What it catches |
|---|---|
| `audio.voice_to_music_db` | Music competing with the words |
| `audio.music_audible` | Music too far under the words to hear |
| `audio.hard_cuts_per_min` | Sound stopping dead instead of decaying |
| `audio.digital_silence_sec` | Gaps that drop to digital zero |
| `audio.ending_drop_db` | A hard stop at the end of a piece |
| `audio.clipping`, `audio.dc_offset`, `audio.mono_safe` | Distortion, offset, and channels that cancel |

## Delivery

Web profiles deliver H.264 with BT.709 tags. The `film-hd` and `film-uhd` profiles also deliver a master:

| Reading | Requirement |
|---|---|
| `master.codec` | ProRes 422 HQ in QuickTime |
| `master.pixels` | 10-bit 4:2:2 |
| `master.size` | HD or 4K |
| `master.color` | BT.709, tagged |
| `master.frame_rate` | The timeline's native rate |
| `master.atoms` | `fiel` and `colr` present |
| `master.black_head_tail` | Begins and ends on a black frame |
| `master.duplicate_frames` | No held or repeated frames |
| `master.audio` | 24-bit LPCM stereo at 48 kHz |
| `master.lkfs`, `master.true_peak` | At most -18 LKFS and -1 dBTP, measured per BS.1770 |

Captions leave the picture on film profiles and ship as SRT, WebVTT, and iTunes Timed Text files.

## Comics and books

| Reading | What it catches |
|---|---|
| `comic.lettering_size` | Lettering below 7.5 pt, which is hard to read in print |
| `story.epub` | An EPUB container a reader would reject |

Art for a comic or a cover is requested with no words in it, because models garble text. A human reads every page.

## Songs

These warn and choose among takes. Only a wrong level on the finished file blocks (ADR 0014).

| Reading | What it catches |
|---|---|
| `song.loudness`, `song.true_peak` | The finished file off its target level |
| `song.tempo` | A take far from the tempo asked for, counting half and double time as the same |
| `song.tempo_drift` | A tempo that wanders |
| `song.words_found` | Lyrics a listener cannot pick out. Lyric error rate is not used: it ran against reviewed verdicts |
| `song.shape` | No difference in level between sections |
| `song.length` | Far from the length asked for |

## What only eyes can catch

No reading sees that a door opens the wrong way or that a coat became a jacket. `kalainova sheet` shows the first and last frame of each shot for that reason, and the vision judge reads the same sheet when a model is listed.

## Known gaps

- Stereo only. An honest 5.1 needs a real multichannel mix, and an upmix from stereo does not count.
- SDR only.
- The bar cannot judge writing, performance, or whether a generated shot looks real. A human does.
