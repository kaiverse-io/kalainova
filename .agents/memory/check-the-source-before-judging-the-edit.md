---
name: check-the-source-before-judging-the-edit
description: Probe source resolution and frame rate before reading anything into a render's softness or judder
metadata:
  type: feedback
---
Early footage tests used 320x180 15 fps preview copies, upscaled to 1080x1920. Softness and judder reviewers saw came partly from the sources, and no editor can fix that.

**Why:** a whole round of review feedback was read as editor faults before anyone ran ffprobe on the inputs.

**How to apply:** Run ffprobe on sources first. `direct.run` now names sources too small for the frame in its note, and the bar reads `source.scale`.
