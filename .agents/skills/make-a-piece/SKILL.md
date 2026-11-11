---
name: make-a-piece
description: Take one prompt to a finished, reviewed candidate, such as a short, intro, reel, clip, or explainer. Choose a route the budget allows, plan it, make it, review and fix it, write its breakdown, and stop at the human gate. Use when the operator names only what to create and wants the rest done.
---

# Make a piece from one prompt

The operator says what to make. Everything else is yours until the gate. Ask at most one question, before any work, and only when the answer changes what money is spent.

## 1. Read what is already decided

- Read the operator's standing decisions from their private agent memory or notes: the budget and cap, which providers are allowed, whether local models are ruled out, any hold on generating, and the platforms. These are personal and never live in this repo. When none are recorded, assume a $0 cap until step 2 says otherwise.
- Run `uv run kalainova providers` with the private environment loaded. A missing key is a fact about the route, not a reason to stop.
- If the piece belongs to a channel or character with kits, use the `run-a-stream` skill instead.

## 2. Choose the route

| Route | Needs | Cost | Use when |
|---|---|---|---|
| Drawn | `hyperframes ready` | $0 | The piece is type, diagrams, charts, maps, or cards. Never for showing places, worlds, or people: drawn scenes of those were rejected at review as looking like an animated GIF |
| Generated | a video key and a cap above $0 | per second of video | The piece needs photoreal worlds or people |
| Mixed | both | per generated shot | Generated shots inside drawn titles, cards, and stamps |
| Footage | the operator's own files | $0 | They gave you material (`docs/how-to/edit-your-footage.md`) |

- Never route to a local model the operator ruled out, and never fall back to one quietly.
- If the piece shows places, worlds, or people, only generated video or real footage will meet the bar. With no cap recorded, that is your one question: ask for a cap, and offer a one-shot test first. Do not draw the scenes instead to stay at $0.
- Take the drawn route without asking only when the piece is type, diagrams, or cards.

## 3. Open and pin the job

1. Run `uv run kalainova new <id> --strategy generated --identity <label> --subject "<brief>" --media video,audio --rights owned --duration <sec> --cost-cap <cap>`. It lands in `$KALAINOVA_HOME`, never in this repo.
2. In `job.json`, set `profile` (`short-9x16` for vertical), and pin `providers` to the route: list only services you mean to use, with no `local` or `mac` unless allowed. A $0 cap makes every paid call refuse, which is the safety you want on the drawn route.
3. For music only, set `brief.narration: false`. For a supplied track, set `brief.track` (a file in the job's out folder) and `brief.track_model`.

## 4. Write the plan yourself

- Write `script_packet.json` directly. No LLM key is needed, because you are the writer. Give every beat an `id`, a `role`, its `text`, and a `duration_sec`.
- A vertical piece has a beat every 4 to 6 seconds, at most five words per line, and the hook on screen in frame 0.
- Any fact goes in `claims` with a source (`research-a-piece` skill). Invented worlds, people, and backstory are marked as fiction in `continuity`.
- Run `uv run kalainova shotplan <job>` and fix what it reports.
- For any job with a cap and moving shots, set `brief.animatic_gate` to true. Then `uv run kalainova animatic <job>` makes a rough cut from stills and the voice, with no video paid for, and prints what the video would cost. Give the operator the file. Video stays held until they have watched it and said so (`kalainova verdict <job> accept --animatic --reviewer NAME`, a person's name, never yours). See `docs/how-to/watch-a-rough-cut.md`.

## 5. Make the picture and the sound

- Drawn shots: the `draw-shots` skill. Generated shots: `docs/how-to/direct-a-shot.md`.
- Sound, in order of preference within the cap:
  - a narrator, if a voice key exists and the piece speaks;
  - generated music;
  - a score written as code. One chord per beat, changes on the cuts, a build toward the payoff, no digital silence, and a fade so the ending drops at least 12 dB. Measure loudness per second, and tell the operator it was measured, not heard.

## 6. Render, review, fix

1. Run `uv run kalainova make <job>`. Read every line that is not a pass.
2. Review with the `review-a-piece` skill, including comparing a source frame with the same moment in the final.
3. Fix at the root and re-run from the earliest stage that changed. Use `--from assets --force` when the shots changed; drawn shots take seconds, generated ones cost money.
4. Repeat until QA passes and your own look finds nothing you can fix. Stop after three rounds, and report what remains. Never weaken a gate, a limit, or a kit to pass.

## 7. Hand over

1. Write the breakdown with the `break-down-a-piece` skill.
2. Give the operator the final path, the contact sheet, what the bar and QA said, what you could not check (listening, taste), the money spent, and two or three specific questions.
3. Stop. Never run `approve` or `publish`, and never write `approval.json`. Record their answer with `uv run kalainova verdict`, naming them.
4. Save what the next run should know, in the right place:
   - The operator's decisions, keys, budget, and anything about their pieces go to their private agent memory, outside this repo.
   - A lesson about the engine that any operator would hit goes to `.agents/memory/`, written without the piece's subject. This repo is public.
