# 0020. A short's animatic is cut from its rented stills

Status: proposed · 2026-11-16. Amends 0016 (the short and reel row of the ladder).

## Context

ADR 0016's ladder for a short or reel has three steps:

1. A free animatic of the shot plan, which is locked.
2. A cheap stage of two or three rented stills per shot, from which one per shot is locked.
3. Paid motion for each accepted still.

The engine does something else. `kalainova animatic` makes one rented still per shot, with the stream's pinned image model and the kit's references (`assets._sketch_pictures`, then `_new_still`). It cuts the animatic from those stills. After the animatic is accepted, the paid motion starts from the same stills. So the free draft and the cheap stage are one step, its stills cost cents, and no shot has candidates.

Doing it this way has reasons:

- **The face is held from the first picture.** A free local still has no kit references, so it would show someone else, and the animatic would lock timing on pictures that are thrown away.
- **Identity is checked where it first exists.** The face check runs on each still at the animatic (rule 1 of 0016's checks), before anything is paid for.
- **Nothing is paid for twice.** The still a person accepts in the animatic is the one the paid motion starts from, by hash.

The cost is cents per still, before the gate. A rejected animatic loses its stills.

## Decision

The short and reel row of 0016's ladder becomes:

| Kind | Free stages | Cheap stage | Paid step, once | Settled before paying |
|---|---|---|---|---|
| Short or reel | Shot plan against the locked audio | One still per shot, rented with the kit's references and the pinned image model. **Lock: the animatic**, cut from those stills, which locks the timing and every first frame together | Motion for each accepted still | Timing, order, first frame, end frame, identity, which shots exist at all |

- The animatic is still the lock before any video spend, and the gate on it is unchanged.
- One still per shot is the default. A brief may later ask for two or three candidates per shot. That is not built, and it is built only if accepted animatics show that first stills miss often.
- The stills are cheap calls under the job's cap, quoted before they are made (`kalainova rehearse` shows each request and its price).

## Consequences

- 0016's rule that a stage is cheaper to redo than the one after it still holds. A still costs cents, and a moving shot costs dollars.
- An operator who wants a draft with no spend at all can set `brief.max_video_beats` to 0 and judge the plan as stills. No free still-making stage is added.
- If candidates per shot are built later, they belong to this same step, before the animatic, so a person picks among them as they lock the cut.

## Alternatives considered

- **Keep 0016 as written and build its order:** a free local still draft, then two or three rented stills per shot. It adds a stage and a second set of pictures, and the draft's faces are not the kit's. Its one gain, an animatic with no spend, can already be had from the plan.
- **Candidates now:** three stills per shot triples the cheap stage before any evidence that one still is not enough.
