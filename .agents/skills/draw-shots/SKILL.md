---
name: draw-shots
description: Make a piece's shots as drawn motion graphics (HyperFrames compositions rendered by the engine's graphics provider) at no cost and with no model. Use for exact type, title and end cards, charts, maps, and diagrams. Not for showing places, worlds, or people.
---

> **Know the ceiling.** Hand-drawn canvas scenes of places came back as flat shapes with mechanical drift, and a reviewer rejected them as "like an animated GIF". Draw what must be exact: type, cards, numbers, diagrams. Generate or film what must look real, and put drawn type around it.

# Draw shots

Each beat's `graphics` field names a composition folder in the job. The engine renders it with `npx hyperframes render` and cuts it like any clip. Nothing is generated, so text is exact and a render is repeatable.

## Build

1. Write one source, `graphics/src/`: a drawing library plus a small build script that writes `graphics/<beat>/index.html` for every beat. Fix the source and rebuild; never hand-edit a generated folder.
2. Size each composition to the profile (1080×1920 for vertical). Make its root `data-duration` one second longer than the beat, so a dissolve never runs out of picture and no frame is held.
3. Draw scenes on a canvas from the time in an `hf-seek` listener, using a seeded PRNG. No `Math.random`, clock, timers, or `requestAnimationFrame`.
4. Animate type with one paused GSAP timeline, registered last. Emit only the tweens a beat uses, so no two tweens share an element's property.
5. If you scaffold with `npx hyperframes init`, pass `--skip-skills`. Without it, init installs skills globally on the operator's machine.

## Rules the bar will hold you to

- **Every frame moves.** Keep a slow camera move, drift, or particles running under every hold, end titles included.
- **Grain reaches the shadows.** Overlay grain does nothing near black. Add a plain low-alpha noise pass, or dark gradients band after encoding.
- **No edge stays black for the whole clip.** The engine's letterbox detector crops an edge that never rises above luma 24. Give dark scenes a lit element that reaches each edge.
- **Type sits in the platform's safe band.** On 1080×1920 that is 168 to 1330 px from the top, with nothing under the right-hand buttons. Keep text at least 28 px, and the hook on screen in frame 0.
- **Draw what is real from its source.** A real place, product, or person is shown from its own imagery, not drawn.

## Check before the engine renders

1. In each folder, run `npx hyperframes check --json`. Fix errors. A warning about content at the canvas edge is expected for full-bleed scenes.
2. Run `npx hyperframes snapshot --at <times>` for every beat, then look at the frames. Does each one read as what the line says? Is anything drawn as a flat placeholder (pill clouds, beaded lines, seams between fills)?
3. Then run `uv run kalainova make <job>`. After a change, use `--from assets --force`.

HyperFrames sends anonymous telemetry unless `npx hyperframes telemetry disable` has been run. Mention it in the breakdown.
