---
name: a-video-file-is-not-motion
description: A reading that checks a file's type cannot see a frozen shot; take the camera's pan and zoom out, and test a new reading on real pieces
metadata:
  type: feedback
---
A generated film scored 1.0 on `edit.moving_share` with a frozen sea, and a vertical short scored 18/18 when the operator called it motionless. The reading only asked whether each source was a video file.

The first fix, lining frames up by translation, passed its synthetic tests and was still wrong. Run against videos already on disk, stills under a camera move read up to 0.116, and one short shot read 0.103 when it was a 5.7% a second zoom over a frozen scene. The synthetic zoom had used nearest-pixel sampling, which hid this. `source.shot_motion` now fits pan and zoom from block matches, starting from the median, because an average let a large moving object throw the fit (0.70 on a shot that should read about 0.2).

Measured 2026-11-07, limit 0.05: stills under a camera 0.008-0.020, shots the operator called still 0.001-0.027, shots not flagged 0.081-0.447. The limit was chosen on these same clips, so this is not independent proof. Real talking heads read 0.01-0.057 and a rocket flame reads low, so this measures how much of the frame moves, not whether a shot is alive. Stairs running the wrong way still need eyes.

**Why:** the bar was trusted as evidence that a piece moved, and it took a human review to find out it did not. Then the synthetic tests were trusted, and it took real footage to find out they were too kind.

**How to apply:** When a reading passes something a human rejects, check what it actually reads before tuning its limit. Before trusting a new picture reading, run it on real pieces with a known answer, including cases that must read zero. Sample synthetic test media the way a renderer does.

Open as of 2026-11-07: why clips freeze. Nearly the same wording read 0.081 in landscape and 0.001 in portrait, so wording alone does not explain it. Test before building a fix on either theory.
