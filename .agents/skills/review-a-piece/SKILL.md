---
name: review-a-piece
description: Check a rendered Kalainova piece by looking and listening before a human reviews it. Use when a film, short, reel, comic, book, or audio piece is rendered, or when asked whether a piece is ready.
---

# Review a piece

Gates catch craft faults. Reading the piece catches the rest: a balloon tail across a face, a title that swallowed an instruction, and a film cut from the wrong assets all passed every check first.

1. **Confirm what was cut.** Read `edit_manifest.json`. Do the cuts name the assets you expect, and does the duration match? A stale edit looks like a success.
2. **Probe the inputs.** Size and frame rate of every source, with `ffprobe`. Do not blame the edit for a small source.
3. **Run `kalainova bar <job>`, and read the numbers,** not just ok or MISS. A value far past its limit in the passing direction is a fault too. Conformance passing says little: the renderer checked its own work.
4. **Look at it.**
   - Picture: `kalainova sheet <job>` for the first and last frame of every shot, then two or three frames at full size.
   - Cuts: `kalainova cutcheck <job>`, then `kalainova filmstrip` on anything it flags.
   - Motion: step through 8 frames of any shot with people. Limbs, hands, and faces fail first.
   - Action: compare the first and last frame of every shot. Did each thing the cue says moves actually move, including water and sky behind a moving person? Regenerate a shot under `source.shot_motion` before showing it.
   - Geometry: does the action fit the place? Check that a person stands on the steps they climb and that the steps rise the way they travel. No number catches this.
   - Comic: read every page. Check tails, overlaps, and lettering against the art.
   - Book: view every page. Check stranded lines and near-empty pages.
5. **Check continuity between shots:** same place, same clothes, same object. Does the place fit the story? Is everything where the last shot left it?
6. **Check the sound.** Whisper on the final mix confirms the words. Per-second levels of the voice and music stems show whether the music can be heard. You cannot judge taste this way, so say so.
7. **Fix a bad shot with `kalainova retake <job> <shot> "what was wrong"`,** and an engine fault at the root, with a test. Re-render from the earliest stage that changed. Never `--force` an assets stage that took hours.
8. **Say what you could not check,** and ask the operator specific questions. Write down what they say with `kalainova verdict`, naming them. Never approve a piece, and never claim an outside platform would accept it.
