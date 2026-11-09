---
name: a-drawn-shot-is-not-letterboxed
description: mediascan.picture_box cropped and enlarged a drawn graphics shot whose edges stayed dark; compare a source clip with the final frame
metadata:
  type: project
---

On 2026-11-08 a HyperFrames graphics shot had a dark interior wall at both side edges. `mediascan.picture_box` found every column there under `BAR_LEVEL` (24) for the whole clip and called it pillarboxing. It cropped 7.5% and 8.4% from the sides, and `op_scale` enlarged the rest 1.19×. QA and the studio bar passed it. The only sign was text pressed against the left edge in the final contact sheet.

**Why:** the detector exists for footage. A composition rendered at the profile's size never has bars, but a dark drawn scene can look like it does.

**How to apply:**
- After a render, compare a source clip's frame with the same moment in `final.mp4`. Framing that differs is a crop.
- The engine fix is to skip `picture_box` for graphics sources (provider `hyperframes`), with a boundary test. Not yet made.
- Until then, keep something above luma 24 reaching each frame edge at some point in the clip.

Related: [[check-the-source-before-judging-the-edit]], [[grain-must-reach-the-shadows]].
