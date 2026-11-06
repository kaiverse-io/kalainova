---
name: a-zero-exit-is-not-a-picture
description: A model can exit 0 and return nothing; decode what comes back and probe each stage for the first NaN
metadata:
  type: feedback
---
A local video model ran for minutes at full GPU, exited 0, and returned 89 black frames. All of its text embeddings were NaN, because a fully masked padding row in the text encoder's attention produced NaN, and the next layer spread it to the real tokens. The same model's frame writer then crushed clean frames to about 1.3 Mbps, which looked like softness from the model.

**Why:** the first black clip went unnoticed until someone looked at it. The engine would have made a whole black film and failed only at final QA.

**How to apply:** Decode what a model returns before trusting it; the router now refuses a flat picture. To find a fault in a pipeline you do not own, wrap each stage and report NaN counts, and find the first one. Check the writer too: a tiny output file is the tell. Do not edit an installed package: patch from a small runner, and say why in its docstring.
