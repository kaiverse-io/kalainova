# Where direction lives

The coding agent is the director. The engine is the toolset and the gates.

An engine that decides what a piece should look like would need a model of taste, and it would spend money on its own judgement. This engine does not. It makes shots, measures them, shows them to whoever is looking, records what that person found, and refuses what it must refuse. The deciding happens in a skill, which an agent follows, and the human gate stays where it is.

## What the engine does

- **Shows.** `kalainova sheet` gives the first and last frame of each shot. `--motion` gives several frames across each shot, in time order, so warping, flicker, and objects that change show. `--cuts` gives frames either side of each join with what the cut check measured.
- **Records.** What a look found goes in `findings.json`: per shot, what is wrong and what to say on the next attempt. The vision judge writes it when a model key exists. An agent writes the same file when none does. The engine never overwrites an agent's findings with the judge's.
- **Refuses.** A retake past the per-shot or per-job limit (`takes.retakes_per_shot`, `takes.retakes_per_job` in `config/studio.yaml`, and `brief.max_retakes`) is refused by the `retake` command, before any model is called. A skill that loops cannot spend past it.
- **Warns, never blocks.** Findings, a long shot with a character in it, and text outside a vertical profile's safe zone are warnings. A human decides (ADR 0011).

## What the skill does

The `make-a-piece` skill holds the loop: make, look, write findings, retake only the shots with findings, look again, and stop after two rounds or at a limit, handing over the open findings. The `review-a-piece` skill says what to look for. Neither approves a piece, raises a cap or a limit, or edits a kit.

## Why a loop is not in the engine

A loop in the engine has to decide when it is good enough, and that is the operator's call. Keeping the loop in a skill means it can change without a release, an operator can read it, and the engine's only loop is the one it can bound: the retake limit.
