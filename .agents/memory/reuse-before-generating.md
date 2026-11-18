---
name: reuse-before-generating
description: Before any package, say which existing stills and takes can serve each shot and why each new one is needed; fix an existing take with one pass before paying for a new one
metadata:
  type: feedback
---
An operator asked twice why a short needed new stills when many images already existed. The answer was mixed:
- Most existing images could not serve: they were rejected cast candidates (other people) or posed identity references below the size floor.
- Two shots could have reused what existed. One matched an earlier still's framing exactly. The other was the same shot as another in the same piece.
- The engine noticed neither. It reuses a still only when the request is byte-identical, and it cannot start a shot from an existing image.

The operator also asked to fix an existing take ("11 is good, fix just the mouth") rather than run more experiments. When a model can't edit a take, say so plainly: a retake from the same still and line is a new take, not the old one fixed.

**Fix:** the agent instructions (`make-a-piece`, `learn-from-feedback`) say to reuse first. Still open in the engine:
- a shot that starts from a named existing image;
- one picture for two identical shots;
- a pass on an existing take (lip, upscale) as a bench row.

**Why:** a paid call that remakes something already bought reads as waste, and it is.

**How to apply:** list the reusable stills and takes for each shot before building a package. Prefer one measured pass on an existing take over a new take when the fault is one the pass can fix.
