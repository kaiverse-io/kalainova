# Consolidated feedback — 2026-11-05

For the next agent. Read this before `CLAUDE_HANDOVER.md` section 7 and before treating `docs/studio.md` as the state of the engine.

Two reviews exist. They answer different questions. `PREMORTEM.md` judged the plan. This file adds the judgement of the code that has since landed on `main`, and it replaces the "only change the checker, then stop" order in `PREMORTEM.md`.

Reviewed tree: `91387f4`.

## 1. What the plan review already said

Nine models read the handover and the engine at `6ac72b1`. Four said NO (Grok 4.7, Grok 4.6, GPT 5.6, Muse). Four said YES-IF, and the IF was a real job, not more cockpit files (Claude Fable, Claude Sonnet, Claude Opus, Composer). Gemini said NO to section 7, and YES-IF only if that section was cut and the checker was fixed.

What still holds:

- The shape stays. One job folder. Three ways in: `funded-clip`, `owned-derivative`, `generated`. One distribution identity per way. A human publishes. Rent the tool. Own the job folder and the log.
- `text-pack`, `audio-native`, `procedural`, `downstream-sku`, and `client` are not the first proof.
- Day 14 still has no operator-named start date. The studio premortem's 2026-11-19 date was written by an agent. Do not invent a start date, an hour cap, a brief, or a money cap.
- Another review is not a piece.

What no longer holds, so do not "fix" it as if it were still true:

- Section 7 was built anyway. `main` has the compiler, CI, ADRs 0001–0007, a devcontainer, pre-commit, a skill, and `docs/studio.md`. Do not add another cockpit plane to catch up with the handover.
- `scripts/check.py` now requires `cost_cap` on a generated job once it leaves `draft`. It still allows eight strategy ids. `check_measure` still only checks shape. A measure file can exist without a URL or a submission id.
- `ARCHITECTURE.md` saying CI is a gate is no longer the false sentence. `.github/workflows/ci.yml` is on `main`.
- ADR 0003 says no compiler before a real unit. ADR 0007 owns the compile path and is merged. The handover still says no compiler. The binding rule is the one in this file: the compiler stays, and it does not count as proof.

## 2. What the implementation review found

Four models read the code at `91387f4` (Grok 4.7, GPT 5.6, Gemini 4, Claude Sonnet). They scored the claim in `docs/studio.md`: a one-line brief becomes media a paying client accepts on first review.

| | Content engine | AI-native | Apple-level |
|---|---|---|---|
| Grok 4.7 | PARTIAL | PARTIAL | NO |
| GPT 5.6 | PARTIAL | PARTIAL | NO |
| Gemini 4 | PARTIAL | NO | NO |
| Claude Sonnet | PARTIAL | NO | NO |

Content engine, partial. `python3 -m kalainova make` can run plan, assets, edit, compile, render, and QA, and `approve` in `kalainova/publish/__init__.py` refuses a file whose sha256 is not the one QA checked. Tests pass on that path. `jobs/` contains only `_template`.

AI-native, partial or no. Remote adapters exist for Anthropic, ElevenLabs, and fal. They have not produced a committed asset. The creative edit is a fixed ffmpeg treatment. The same local field stands in for different briefs.

Apple-level, no. The only output the repo can prove is the local fallback. `kalainova/providers/local.py` says so itself: those providers are not the quality bar. QA still marks a local proof passed, and `docs/studio.md` offers that pass as where the engine is. `approve` takes the reviewer as a string. Nothing in the tree is a person accepting a real picture without a re-render.

Per-model writeups stay in the operator workspace: `RESEARCH/kalainova-studio-implementation-review-2026-11-05/`. They are not copied into this repo.

## 3. What to do, in order

Do these. Do not open a new lane, a new ADR, or a sample job while you do them.

1. One code change. A job whose picture, voice, or music came from `provider == "local"` (models `local-studio-field`, `flite-*`, `local-pad`, `local-whoosh`, `local-typecard`) is a placeholder. `approve` refuses it. QA may still record a technical pass for CI, and that pass must not be writable as `approved`. The local provider's own comment is the rule. The gate has to enforce it.

2. Stop. The operator names a brief and a money cap, and runs one job on his machine with the paid picture and voice models. The job folder keeps the provider names, a non-zero ledger, and the file. An agent does not invent the subject or open that job to have something to commit.

3. After that file exists, QA fails closed. A missing vision check, or a vision check that says fix, fails the job. Captions match the word times from the voice provider. A check of the estimator against itself does not count.

4. Then the model looks at the rendered frames and can send a shot back. Then a short run of pieces the operator accepts or sends back. The bar already written in `docs/studio.md` is 60% accepted on first review, on the order of ten pieces, with at least six `approval.json` files bound to the sha256 QA passed. Until that number is in the repo, Apple-level stays no.

`docs/studio.md` describes that local proof as the current engine. After step 1, change that section so it calls the local file a placeholder. Leave the 30-day and 90-day numbers as the bar, not as a result.

## 4. What not to merge

- A fifth strategy, a stock-reel identity, or a client vertical, as the first proof.
- A made-up job, a made-up URL, or an approval whose reviewer is the agent that rendered the file.
- Another premortem, theme, skill, or workflow whose only new fact is that the local mp4 still passes loudness.
- A rewrite of `CLAUDE_HANDOVER.md` section 7 into a new build list. That section stays frozen. This file is the order that replaces it.

Writeups of the plan review, if you have the operator workspace: `RESEARCH/kalainova-engine-premortem-2026-11-05/`.
