# 0013. A shot is a set of takes, and a promise of motion is kept or refused

Status: accepted · 2026-11-07.

## Context

Generated video is a sample. The same prompt freezes on one seed and lives on the next, and vendors budget several attempts per usable shot. The engine held one clip per beat, seeded by a hash of its prompt, so asking again asked for the same clip. When a clip could not be made, the shot silently became a still and the job passed, and "slideshow" was the first reason a person rejected a piece.

Prompts spent their words on appearance. A clip that starts from a still already has the picture, and Runway's guide says to focus on motion, not appearance. LTX's guide says its prompts degrade past about 80 words.

## Decision

- **Takes.** Every attempt is kept with its seed and how it read, in `takes.json`. A failing reading asks for another attempt, up to a limit the brief can set. The piece uses one chosen take at a stable path.
- **A person's choice stands.** Readings choose until a person does, and then a later reading cannot overrule them.
- **The motion promise.** A beat written `visual_kind: video` that cannot move stops the job, unless the brief sets `allow_stills`. A plan asking for more moving shots than its budget is refused before any spend. A broken promise fails QA and cannot be approved.
- **Shots are written apart.** `shot.first_frame` is the still's prompt. `shot.camera`, `shot.action`, and `shot.environment` are the clip's, motion first. Stills are never mentioned to a video model.
- **Continuity is one block.** People, places, and props are described once in the packet and reused word for word.
- **Plans are reviewed first.** `shots.review` reads a plan before anything is spent.

## Consequences

Whether a motion-first prompt stops clips freezing is a hypothesis until a real run tests it, and the readings exist to answer it. A retake costs money or GPU time, so the default is one take and one retake. The reading that drives retakes is the same `source.shot_motion` that warns at QA, so its limit decides real spend: it needs checking against verdicts with `kalainova signals`.

## Amendment, 2026-11-11

- A shot whose chosen take never passed the motion reading now records a promise break, like a shot with no clip. The failing clip stays on disk for a person to look at. A person's own choice of a take, or `brief.allow_stills`, accepts it.
- A placeholder run no longer sets `allow_stills`, and QA no longer forgives a break because a placeholder made the assets. A fixture that needs stills sets `brief.allow_stills` itself.
- `source.shot_motion` stays a warning at QA, and `shot_motion_min` is not tuned: no human verdict exists to tune it against.
- A last frame is sent as an image, in the model's own field (`end_image_param` under `video_models`), when the model has one. When it has none, the frame is not written into the prompt, and the shot's record says it was not used.
- Lip sync pads the line with silence to the clip's length, so the vendor's cut to the shorter input no longer shortens the shot. The clip before the sync is kept beside the synced one. Regrading from a higher-quality mezzanine remains a known limit.
