# 0024. Learned judges rank takes, and never block

Status: accepted · 2026-11-17. Builds on 0016 (layered QA) and 0023 (the engine speaks to models in its own terms).

## Context

A take's readings check what the brief asked for: tempo, length, how many of the words can be picked out, and level. They cannot say whether a song is good. Until now, a person chose between takes that passed their readings, and a person ranked models blind.

Open models now exist that are trained to agree with people about quality. MuQ-Eval scores musical impression, with a clip-level Spearman of 0.838 against expert ratings (arXiv 2603.22677). Audiobox Aesthetics scores four axes of production. Each needs its own environment and weights, and neither belongs inside the engine.

The first blind test of three song models, on one brief, showed what each kind of evidence misses:

- the take the judge liked best sang 13 of the song's words in three minutes;
- the take that met every reading was the judge's least favourite.

## Decision

1. **A judge is a command, configured by the kind of file it reads.**
   - `judges.<kind>` in `config/studio.yaml` lists judges by name. Each command takes `--out FILE` and file paths, and writes `{path: {score: number}}`.
   - The engine imports no judge's code and ships no model, the same as `identity.face_command`.
   - `providers/runners/` holds one script per tool. Swapping a judge, or adding one, is a config change.
2. **`bar/judges.py` is the only reader.** It runs each judge once over a batch and keeps its scores under `<judge>.<score>`. It reports a judge that fails or says nothing of a file, and the piece goes on.
3. **A judge's score ranks, and never blocks.**
   - Each take keeps its scores (`judged`), plus the first judge's `rank_by` score as its `rank`.
   - Of the takes that pass their readings, the highest rank stands (`takes._best`). With no judge set, the first take that passes stands, as before.
   - When no take passes, the one closest to passing stands, by readings alone, so a judge never lifts a take that misses the brief.
4. **Takes already made are judged together.** `kalainova review <job>... --judge` scores every song take across the jobs it names, keeps the scores, and lists them best first, each with what its readings missed.

## Consequences

- An agent can choose among takes, and between models, without asking a person to rank. The evidence is written on each take, where a person can check it.
- Judge and readings can disagree. The listing puts them side by side, and a choice between models still names its reason.
- No judge is calibrated against this studio's own verdicts yet. When blind rankings by people accumulate, their agreement with the judges is measured, and a judge that disagrees is dropped or demoted.
- Each judge's licence travels with its weights. MuQ-Eval is MIT, and Audiobox Aesthetics is CC-BY-4.0. SongEval is non-commercial, so it is not listed.
- Video judges (lip sync, consistency) plug in the same way, under their own kind.
