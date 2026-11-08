---
name: a-conformance-score-flatters-any-file
description: About half of the bar's readings are format checks the renderer controls, so an X/Y total rewards a placeholder; compare craft readings with human verdicts instead
metadata:
  type: feedback
---
A film-profile piece gets 29 readings. The 14 that block are format checks: colour tags, pixel format, clipping, and the master's codec, size, rate, and levels. The renderer controls nearly all of them, so they pass on anything it makes. The 15 craft readings only warn.

Measured 2026-11-07: a numpy gradient read 26/30 (87%). A piece a person rejected as motionless read 18/18 (100%). A piece a person passed read 13/16 (81%). The denominator changes with the profile, so these totals do not compare, and here they ran against the verdicts.

Three kinds of fault have no reading at all: geometry that runs the wrong way, a costume that changes between shots, and a place that does not fit the story. `source.shot_motion` now flags frozen shots, but it warns and its limit was chosen on the clips it was tested on.

**Why:** ADR 0011 keeps a signal only if it separates good from bad on reviewed samples. The total was being read as evidence of quality, and it does not pass that test.

**How to apply:** Do not quote an X/Y total as evidence that a piece is good. Report conformance and craft apart. Before trusting or adding a reading, check it against shots with a human verdict. A first-and-last-frame sheet of every shot finds faults the readings cannot. See [[a-video-file-is-not-motion]].
