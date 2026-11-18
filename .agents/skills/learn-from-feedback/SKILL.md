---
name: learn-from-feedback
description: Turn a person's correction, a verdict with a reason, or a disappointing paid result into engine behaviour or an agent instruction, so the mistake is not made twice. Use every time an operator says what is wrong with a take, a piece or how the work was done, and before planning the next paid call after one.
---

# Learn from feedback

The point is a first take that already follows every lesson. A fix that lives in one job's files, or in an agent's head, is gone by the next job.

## 1. Record it

- **A take or a piece:**
  - run `uv run kalainova verdict <job> accept|fix|reject --reviewer NAME --shot <id> --take <n> --note "<their words>"`;
  - for a preference, use `--best N --among a,b,c --aspect <lips|head|eyes|body|picture|overall>`.
- **How the agent worked:** write it in the harness's private memory (it is not about a piece).
- Quote the person. Do not paraphrase a verdict into something kinder or more certain than they said.

## 2. Find the root cause

Ask what produced the result, not how to patch this one:
- the prompt's wording, and who wrote it (the plan, a shot list, the engine, or an agent by hand);
- a default (a style, a limit, a model choice);
- the input (the still, the line, a reference);
- the model itself;
- a check that should have caught it;
- how the agent worked (asked too much of the operator, spent serially, hand-tuned).

Read the request that was sent (`out/<job>/rehearsal*.json`, `trace.jsonl`) before guessing.

## 3. Research before changing anything

- **Look up what the model reads:**
  - its schema, from the vendor's OpenAPI;
  - its prompt limit (a reseller's API reference often states what the host's schema omits);
  - its own prompt guide;
  - what it decides by itself.
- **Look for independent tests.** Mark each piece of evidence as the vendor's claim, independent, our own takes, or inference.
- **Check the decisions already made:**
  - `docs/decisions/`;
  - the operator's standing preferences;
  - the kill checks in `docs/explanation/`.

## 4. Fix it where every later job gets it

| The cause | Where the fix lives |
|---|---|
| How a person on camera performs | a direction in `prompts/directions.yaml`: a new text is a new version, pinned in `directions.lock` (a studio overrides one in its own config) |
| A look or a default | `config/studio.yaml` (for example `visual_style`) |
| What a model takes, and its limits | its row in config: `limits` claims with a source, date and class (`kalainova guide <model>`, `kalainova models refresh`), `min_audio_sec`, `short_side` |
| A plan that invites the mistake | a check in `shots.review` with its fix in `readiness.FIXES` |
| A take that should have been caught | a judge (`judges.*`), ranked only once `kalainova agreement` backs it |
| How an agent works | `AGENTS.md`, or the skill that covers the task |

- Add a test that fails on the old behaviour.
- A hand edit to one job's files is only a stopgap. Say so, and still make the engine change.

## 5. Prove it

1. **The free check first.** `kalainova rehearse` shows the new prompt and that it fits the model. Readiness or `shotplan` flags the old mistake on the job that made it.
2. **Then the smallest real test, as one package.**
   - Change one thing, and keep the still and the line fixed.
   - Ask the operator to sign it off. Say what to look for, and what result would prove or disprove the fix.
3. **After the take:**
   - record the new verdict;
   - say whether the lesson held.

## 6. Log it

Add one file to `.agents/memory/` and its line in `MEMORY.md`:
- what happened;
- the root cause;
- where the fix lives (file and function);
- the evidence;
- proved or unproved.

Write it without the piece's subject, because this repo is public. The operator's own decisions go to the harness's private memory.

## Before the next paid call

Read the lessons that touch it. Readiness enforces the mechanical ones; the rest are yours to apply:
- reuse stills and takes that already exist;
- send one request per model with every direction in it;
- test at the lowest resolution first;
- keep judges local unless the operator says otherwise.
