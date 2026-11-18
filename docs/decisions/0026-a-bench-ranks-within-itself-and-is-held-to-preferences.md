# 0026. A bench ranks its takes within itself, and is held to a person's preferences by aspect

Status: accepted · 2026-11-18. Builds on 0017 (an autonomy level per review gate) and 0024 (learned judges rank takes and never block).

## Context

A bench of one sung line on five models was decided by hand. The agent:

- pulled frames;
- measured head movement with a one-off script;
- copied every reading into a table;
- read the table to choose.

The person watching could not tell which panel was which model, because the side by side was unlabelled. Three of their observations were about different aspects of different takes: one take's picture, another's lips and head, a third's eyes and body.

The engine's only movement reading covered the whole frame. It read the take whose head turned most as the stillest, because its body and background did not move.

Two independent reviews of the design agreed on four points:

- rank takes only against the other takes of the same shot;
- set no weights or floors per kind of shot while there is a single labelled example, because they would fit that one shot;
- record a person's preferences as pairs;
- measure agreement before trusting an automatic pick.

## Decision

1. **Every bench writes its own report.** The report has three parts:
   - a side by side with a strip naming each panel's take and model;
   - a table of every reading;
   - the engine's pick with its place on each ranking reading, or the reason it gives none.

   `kalainova bench-report` writes it again at no cost, for chosen takes in a chosen order, after judging what a take was not yet read by.
2. **The ranking readings are config.** `rank.<capability>` lists readings, each with which way is better and an optional weight.
   - Each reading is scaled within the takes compared, so a rule says only which of these takes reads best, never whether a take passes a fixed mark. That is what lets one rule carry from a quiet close-up to a loud wide shot.
   - A take that missed its floor, or that a ranking judge did not read, is listed and not ranked.
   - A character take under the profile's size floor is ranked and not picked.
   - When the first two are within `rank.close`, the report says a person decides.
3. **How a person moves is a judge of its own** (`judges.performance`), run on every take with a character in it. It reads:
   - head turn, nod and tilt;
   - eye travel, openness and blinks;
   - the person's movement apart from the camera's and the background's.

   These are properties, not taste. None of them ranks until rule 4 shows it follows what people see.
4. **A preference names its aspect.** `kalainova verdict --best N --among a,b,c --aspect lips` records a preference for one take over each of the others, on one aspect from `review_aspects`.
   - `kalainova agreement` reports, for each aspect and each reading, how often the preferred take read higher, together with the engine's own picks.
   - A reading joins `rank` once it agrees on at least `PAIRS_ENOUGH` pairs spread across varied shots: singing and speech, close and wide framing, more than one character. A reading that stops agreeing leaves `rank`.
   - The bar for moving a gate's autonomy (ADR 0017) is measured the same way.
5. **Guards before spend.**
   - A bench row identical to one already made (same model, same prompt) is refused unless asked for with `--again`.
   - A model known to make a character shot under the size floor is said before the estimate.
   - A bench rehearsal prices the stills only when the shot has no still or length yet.
6. **An AI vision judge comes in the same way.** It is a judge kind with a versioned prompt, a pinned model, fixed frame sampling and repeated votes. Its scores rank only once rule 4 shows they follow a person's reads on the aspects nothing else measures: realism, a flat or painted look, physical mistakes.

## Consequences

- A bench is decided by the engine's report, and an agent no longer assembles evidence by hand. The pick is advice, and the evidence behind it is written down.
- Nothing is tuned on one shot. The ranking readings start as the lip judges alone. Movement and picture readings wait for preferences across varied shots.
- People now record preferences as pairs per aspect. Those pairs become the labels every new judge, including a learned or AI one, is measured against before it ranks.
