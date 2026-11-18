---
name: a-call-on-a-clip-just-bought-cannot-be-keyed-by-its-bytes
description: A package matches a request by the bytes of its inputs; a lip sync is made on the clip the same stage buys, so an exact entry refused it mid-run; sign such calls as a counted allowance
metadata:
  type: feedback
---
ADR 0022 packages match each paid request by its content key, which hashes the input files' bytes (`gates._entry`). A lip sync's input is the clip the motion stage has just bought. When the package is built, the dry run has only a stand-in clip, so the key it signed could never match the real one. Every on-camera lip sync, spoken or sung, would have been refused after its video was paid for.

Found on 2026-11-17 by rehearsing a song video with singing shots on a scratch copy of a studio. The same run found two price errors:
- the dry run's stand-in clip was the asked length, not the length the vendor returns;
- the estimate priced the lip sync at the asked length too.

A Kling "3 s" clip is 73 frames, 3.042 s, so even the correct price ($0.1521) sat just over a $0.15 ceiling.

**Why:** a package that cannot match a call it lists fails at the worst moment: after spend, mid-stage.

**How to apply:** a capability whose input is a file the same stage buys goes in `packages.MADE_ON_A_NEW_CLIP`. It is signed as an allowance counted per call, priced on the vendor's billed length (`Provider.billed_seconds`) plus `CLIP_MARGIN`. When you add a call made on a generated file, add it there, and rehearse a real job, not only a fake vendor. Related: [[rehearse-before-the-first-paid-run]].
