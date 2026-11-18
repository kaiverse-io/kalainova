---
name: whole-frame-motion-is-not-a-performance
description: The frame's motion read the take whose head turned most as the stillest; judge a person apart from the background, and let preferences decide which readings rank
metadata:
  type: feedback
---
On a bench of one sung line, `shot_motion` read one take at 0.09 against 0.23-0.28 for the rest, and the agent called it static. A reviewer said it had the best head movement. A head-pose check agreed with the reviewer: the widest turn of all five takes (yaw 5th-95th percentile 9 degrees, full range 19). Its body and background barely moved, and those fill most of the frame. Another take had the most body and head movement (subject 0.044 of the frame's diagonal a second) and the worst lips.

`judges.performance` (`providers/runners/perform_run.py`) now reads the person apart from the frame:
- head turn, nod and tilt from the face's transformation matrix;
- eye travel and openness;
- the person's own movement inside a person mask, with the camera's median background flow taken out first.

Iris position is a weak reading at a normal framing. The first version measured it against the gap between the lids, and a nearly shut eye read 47 when the others read 0.3. Measured against the eye's width it reads 0.004-0.018 eye widths, about a pixel at that face size, which sits near the noise. So it is reported, not trusted.

**Why:** an agent read one number as "motion" and was wrong about the take a person liked for exactly that. The agent then assembled the evidence by hand with one-off scripts, a hand-made table and an unlabelled side by side. That is the work the engine exists to do.

**How to apply:**
- Measure what a person judges, aspect by aspect, as engine judges that run on every take (`takejudges.py`), not as scratch scripts.
- Rank takes only against the other takes of the same shot.
- Add a reading to `rank` only after `kalainova agreement` shows it follows people's preferences on that aspect across varied shots. Readings tuned on one bench fit that bench.
- Before trusting a face reading, check it on a take where the eyes are closed or the face turns away.
