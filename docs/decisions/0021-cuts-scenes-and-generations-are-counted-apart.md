# 0021. Cuts, scenes and generations are counted apart, and code packs the paid ones

Status: proposed · 2026-11-16

## Context

A song video's shot list makes one beat per line. Each beat then gets its own cut, its own start still and its own paid generation, so the three move together. They have very different prices:

- **A cut** is editing, and costs nothing.
- **A start still** costs cents.
- **A generation** is billed by the second at a model's own minimum. Kling O3 bills at least 3 s, so a 1.9 s cut pays for 3.

For a 30 s performance short on Kling O3, at the prices then in the table:
- one generation per 1.9 s beat cost $7.78, a third of it for seconds nobody sees;
- two 15 s multi-shot generations with the same cuts cost $3.66.

Kling O3's `multi_prompt` takes up to six shots, each 1–15 s, totalling up to 15 s, in one generation that shares its references across the cuts. Wan 3.0 Prime makes up to 30 s as one continuous take.

What a piece needs varies with its kind:
- a beat-synced travel reel changes place on nearly every cut, so it needs many stills;
- a performance short changes angle within one place;
- an ambient loop barely changes at all.

Published editing norms are a starting point, not a rule. A sample of ten Billboard music videos measured a mean shot of 1.72 s, ranging from 0.92 to 9.04 s by video. In performance videos the longest shot tracks the bar length. Short-form guides suggest 2–3 s, without controlled studies.

Codex and Cursor reviewed the design independently and agreed with it. Their refinements are folded in below.

## Decision

1. **Five counts are kept apart:**
   - editorial cuts;
   - continuity scenes (place, time, situation);
   - setups (an angle or look within a scene, which needs a start still only when its first frame must be locked);
   - paid generations and their billed seconds;
   - the retake unit (how much is redone when one part fails).
2. **A pacing prior per kind of piece** lives in `config/studio.yaml` (`pacing`). It gives the cut length (beats or bars when the piece is music-led, seconds otherwise), the setups expected per 30 s, the largest group of cuts per generation, and the chance one shot fails review (`shot_fail_rate`). Every value is an ESTIMATE until human verdicts move it, through `calibration`.
3. **The planner only labels.** Each beat may carry:
   - `scene`;
   - `setup`;
   - `changes`, one of nothing, subject or place, saying what changes from the previous beat.

   It never chooses how many generations to pay for.
4. **A pure function packs and prices** (`packing.py`). It turns the beats, the pacing row and each model's limits into candidate plans:
   - one generation per beat;
   - multi-shot groups, which need the same lane, the same cast and the model's limits;
   - one take cut up, for beats that share a setup and change nothing.

   It prices each plan with the engine's own estimate and adds the expected cost of a retake: a group of n shots fails with probability 1 − (1 − p)ⁿ. It picks the lowest expected cost that passes the constraints.
5. **Cuts land on the beat at frame precision.** A generation's whole seconds never move a cut: each shot is generated a little long, up to the next whole second, and trimmed in the edit.
6. **`kalainova rehearse` prints the comparison** of the candidate plans before anything is spent.

## Consequences

- A performance short pays for about half the seconds, and for one still per generation instead of one per cut.
- Retakes get coarser. Remaking one cut inside a multi-shot generation remakes the generation. The expected-cost rule prices that, and `max_cuts_per_generation` caps it until verdicts show how often a shot fails.
- A multi-shot generation has one start frame. A setup inside it is held by the prompt and the shared references, not by a locked still. Whether a face holds across many cuts is unmeasured: one 5 s O3 shot held, median 0.66. The first paid multi-shot test reads every segment.
- The prices the packer compares are the engine's corrected estimates (`providers/prices.py`), so a stale table does not tilt the choice.

## Alternatives considered

- **Keep one generation per cut.** It is the simplest and the most expensive. For one-second-scale cuts on a 3 s minimum, it wastes about a third of the spend.
- **Let a model choose the counts.** It is not repeatable, and it cannot be audited against a bill.
- **Learn the pacing from reference edits** (OTIO, EDL imports). It is useful later for calibrating the priors, once there are enough edits; not as the planner now.
- **Shot-boundary models** (TransNet, AutoShot) and **director-agent frameworks** (ViMax, MovieAgent). They analyse finished film or replace the planner; neither allocates spend.
