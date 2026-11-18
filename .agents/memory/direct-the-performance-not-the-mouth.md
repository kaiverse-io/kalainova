---
name: direct-the-performance-not-the-mouth
description: A sung shot's eyes, head and body follow its prompt and its mouth follows the voice; the engine directs the performance from one versioned prompt, and a cue that closes the eyes or shapes the mouth is warned
metadata:
  type: feedback
---
On a bench of one sung line, the same voice-driven model ran from the same still and line twice. Only the cue changed:
- **"Eyes half closed, head moving with the beat":** eyes open 37% of the time, eye travel 0.005, head turn range 4 degrees. A reviewer found it held back.
- **"Eyes open and alive, glancing out and back to camera, head turning and nodding, shoulders swaying":** eyes open 61%, eye travel 0.014, head turn 14 degrees, subject motion up 40%. The reviewer called it good, but said the mouth opened "too big and wide".

The agent had written both directions by hand, and the second added "mouth opening only as much as each word needs". Several practitioner guides for that model agree on the same points:
- describe breath and movement, not mouth shapes, and let the audio drive the lips;
- keep the prompt short, with one or two motions;
- prefer positive wording;
- start from a still with a calm, neutral mouth.

The model also takes at most 300 characters of prompt. Its host's schema does not say so, but reseller API references do.

**Fix, in the engine:**
- `perform.sing` (versioned in `prompts/directions.yaml`, pinned by `directions.lock`) is added to every sung shot's prompt by `shots.motion_prompt`, before the picture and the sound, so fitting a word limit keeps it.
- `shots.review` warns `performance_words` when a sung cue closes the eyes or names the mouth or lips. Its fix is in `readiness.FIXES`.
- `shots.MOUTH_CLEAR` asks the singing still for relaxed lips, not a mouth caught mid-note.
- `limits.prompt_chars` (a claim with its source, date and class) sits in each sing model's config row, and `fal_sing.payload` refuses a longer prompt before it is sent.

**Proved:** the eyes and head respond to the direction (the two takes above). **Unproved:** whether the shorter, positive direction and a relaxed-lip still calm the mouth. That needs the next take of the same line.

**Why:** a first take should already be directed the way verdicts have taught, not hand-tuned per job after a reviewer complains.

**How to apply:** change a performance only as a new version of its direction in `prompts/directions.yaml` (or a studio's override), never in a shot's cue. Keep shot cues to framing, action and setting. Check a model's prompt limit before writing for it.
