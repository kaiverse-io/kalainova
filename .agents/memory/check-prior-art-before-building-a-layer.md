---
name: check-prior-art-before-building-a-layer
description: Most gaps found in the engine already had working code in open projects; check them before building a layer, and rewrite rather than copy anything under AGPL
metadata:
  type: feedback
---
A review on 2026-11-07 compared the engine with open projects layer by layer. About 40% of its lines duplicated something adoptable or were built before anything needed them, and no ADR had weighed any of those projects.

Where each idea already lives:

| Need | Project | Licence |
|---|---|---|
| Refuse a silent fall from motion to stills | OpenMontage `lib/delivery_promise.py` | AGPL, rewrite the idea |
| Score a scene plan for slideshow risk | OpenMontage `lib/slideshow_risk.py` | AGPL, rewrite the idea |
| Estimate, reserve, reconcile, refund | OpenMontage `tools/cost_tracker.py` | AGPL, rewrite the idea |
| Vendor connectors, seeds, signed manifests, replay | genblaze | MIT |
| Agent editing that checks every cut of its own render | video-use | MIT |
| First-frame chaining and choosing among candidate images | ViMax | MIT |
| Export a cut to an editor's timeline | auto-editor | Public domain |
| ProRes HQ export and HTML overlays | HyperFrames | Apache 2.0 |
| Banding | CAMBI, through ffmpeg's `libvmaf` filter | check before use |

No project checked had video takes for a shot, retakes driven by a reading, or an approval bound to a master's hash. Those are worth building.

**Why:** building a layer by default costs more than the lines. The gaps it leaves stay open while the same fix sits in another project.

**How to apply:** Before adding a layer, look for it in these projects and record the choice in an ADR. This engine is Apache 2.0, so AGPL and non-commercial code cannot be copied in. A code licence does not cover a model's weights, so read those separately. See [[a-conformance-score-flatters-any-file]].
