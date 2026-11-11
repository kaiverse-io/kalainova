---
name: review-a-piece
description: Check a rendered Kalainova piece by looking and listening before a human reviews it. Use when a film, short, reel, comic, book, or audio piece is rendered, or when asked whether a piece is ready.
---

# Review a piece

Gates catch craft faults. Reading the piece catches the rest: a balloon tail across a face, a title that swallowed an instruction, and a film cut from the wrong assets all passed every check first.

0. **Compare a source with the final.** Take one frame from a source clip and the same moment from the final. Framing that differs means the engine cropped or scaled it, for example a dark edge taken for a letterbox.
1. **Confirm what was cut.** Read `edit_manifest.json`. Do the cuts name the assets you expect, and does the duration match? A stale edit looks like a success.
2. **Probe the inputs.** Size and frame rate of every source, with `ffprobe`. Do not blame the edit for a small source.
3. **Run `kalainova bar <job>`, and read the numbers,** not just ok or MISS. A value far past its limit in the passing direction is a fault too. Conformance passing says little: the renderer checked its own work.
4. **Look at it.**
   - Picture: `kalainova sheet <job>` for the first and last frame of every shot, then two or three frames at full size.
   - Cuts: `kalainova cutcheck <job>`, then `kalainova filmstrip` on anything it flags.
   - Motion: `kalainova sheet <job> --motion` puts several frames across every shot in one row, in time order. Read each row for warping or melting, flicker between neighbouring frames, limbs or objects that change, and whether the named action happened. Face and hands fail first. Open one shot at full size with `kalainova filmstrip` when a row looks wrong.
   - Cuts, in motion: `kalainova sheet <job> --cuts` shows two frames either side of each join with what the cut check measured.
   - Action: compare the first and last frame of every shot. Did each thing the cue says moves actually move, including water and sky behind a moving person? Regenerate a shot under `source.shot_motion` before showing it.
   - Geometry: does the action fit the place? Check that a person stands on the steps they climb and that the steps rise the way they travel. No number catches this.
   - Comic: read every page. Check tails, overlaps, and lettering against the art.
   - Book: view every page. Check stranded lines and near-empty pages.
5. **Check continuity between shots:** same place, same clothes, same object. Does the place fit the story? Is everything where the last shot left it?
6. **Check the sound.** Whisper on the final mix confirms the words. Per-second levels of the voice and music stems show whether the music can be heard. You cannot judge taste this way, so say so.
7. **Write what you found to `findings.json`** (shape: `schemas/findings.schema.json`; check it with `kalainova findings <job>`), the same file the vision judge writes when a model key exists. Then **fix a bad shot with `kalainova retake <job> <shot> "what was wrong"`,** or with no note to use the finding. The engine refuses retakes past its limits; do not work around that. Fix an engine fault at the root, with a test. Re-render from the earliest stage that changed. Never `--force` an assets stage that took hours.
8. **Say what you could not check,** and ask the operator specific questions. Write down what they say with `kalainova verdict`, naming them. Never approve a piece, and never claim an outside platform would accept it.
