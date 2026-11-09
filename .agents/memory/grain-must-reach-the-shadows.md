---
name: grain-must-reach-the-shadows
description: Overlay-blended grain leaves near-black gradients undithered, so they band after encoding; add a plain low-alpha pass
metadata:
  type: project
---

On 2026-11-08 a drawn piece with canvas grain in `overlay` mode read 0.049 on `picture.banding` (limit 0.03), with CAMBI 5.4. Per-shot measurement put the banding in the darkest scenes. Overlay barely changes values near black, so those gradients reached the encoder smooth and came out stepped.

Adding a second grain pass in `source-over` at alpha 0.04 (about ±5 levels, ~3 px grain) took banding to 0.001 and CAMBI to 0.09.

**Why:** a grain that looks right in the mid-tones can still leave the shadows unprotected. The bar only catches it after a full render.

**How to apply:**
- Dither darks explicitly in any drawn or generated gradient.
- When banding misses, measure it per shot and per half-frame with `bar.picture.banding_score` to find where it is before changing anything.
- The cost is bitrate: 30 s at 1080×1920 came to 206 MB.

Related: [[a-drawn-shot-is-not-letterboxed]].
