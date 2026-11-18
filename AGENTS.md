---
kind: agent-context
status: active
last_reviewed: 2026-11-06
---

# Kalainova — Agent Context

Content generation engine for any subject. Video, audio, stills, songs, and text. Stamped from `kaiverse-io/chassis` (ADR 0008). `CLAUDE.md` imports this file, and Codex reads it directly. Update here only.

The current verdict and kill checks are in `docs/explanation/premortem-2026-11-05-studio.md`. Decisions are in `docs/decisions/`.

## This repo is public

The engine, schemas, prompts, and docs live here. Real jobs, kits, streams, and media live in a private directory named by `$KALAINOVA_HOME` (ADR 0010). Never add a character, a brand, an account handle, or a real brief to this repo.

## What you are building

A piece belongs to a stream. Read `docs/how-to/run-a-stream.md`. `docs/strategies.md` explains the peer ways a piece starts. The goal is `docs/studio-goal.md`.

- **Kit.** What stays the same: face, voice, persona, places, style, music. Frozen by version.
- **Stream.** Where it goes: one identity, one strategy, its kits, its generators, its limits.
- **Job.** One piece, locked to exact kit versions.

The operator names a stream and a brief with `kalainova request`. The engine works out the rest and refuses before spending if it cannot hold what the kits promise.

The quality target is `docs/studio-bar.md`. `kalainova bar <job or file>` measures any piece against it.

## Project structure

```
src/kalainova/      engine; ARCHITECTURE.md covers every top-level module
schemas/            the job, kit, stream, and lock contracts
prompts/            versioned prompts and directions, loaded at runtime; ship in the package
config/studio.yaml  model and price table; which models take references; the studio bar's limits
fonts/              vendored open fonts, so every machine sets the same type
scripts/            the contract and docs gates (stdlib)
evals/contract/     fixtures that must pass or fail
tests/              pytest; tests/boundary/ holds behaviour contracts that survive a rewrite
docs/               how-to, explanation, reference, tutorials, decisions
docs/feature-map.md feature to entry point to code to tests; start here to find where to change
.mcp.json           the only MCP servers agents may use here; reviewed (CODEOWNERS)
.agents/skills/     agent skills; .claude/skills links here
.agents/memory/     agent memory, tracked
```

## Planes

- **Guardrails.** `just ci`: contract, lint, types, secrets, semantic rules, tests, docs, architecture coverage.
- **One strategy per stream, one identity per stream.** A funded-clip post never goes out on an identity used for owned or generated work.
- **Humans gate publish.** A human approves every piece (`kalainova approve`). Agents never write `approval.json`, and they never submit a campaign URL. `kalainova publish` posts only the approved, QA-checked bytes (ADR 0007).
- **Humans sign off spend.** No paid call runs without a package a person signed off (ADR 0022). Agents build packages (`kalainova package`), fix what their readiness findings say, and never sign them off: never run `kalainova sign-off` or set `kalainova limits`, never write a `.signoff.json`, never edit `limits.json` or `packages/spent.jsonl`. A refusal names what a person must sign off; report it and stop.
- **Humans attest kits.** Agents never run `kit freeze`, never set `origin.attested_by`, and never add canon on their own. Each of those names a human.
- **Rent the models, own the line.** Models are swapped in `config/studio.yaml`. Procedural formats and SKUs still wait for a proof.

## Hard rules

- Committing `mp3`, `mp4`, `wav`, `m4a`, `mov`, or `webm`, or any reference image.
- Naming a vertical, niche, brand, creator, or topic in the engine docs, schemas, or prompts.
- Checking in a sample subject "to show how it works."
- A real person's face, voice, or name in a kit. Every character is invented, fictional, and an adult.
- Inventing a factual claim. A fact in a script carries a source in `script_packet.json`. Backstory and canon are fiction, and are marked so.
- Using source material not covered by `rights`: `funded-brief`, `owned`, or `licensed`.
- Rendering a schedule up front. A slot renders when requested, and passes the human gate like any job.
- Credentials in a kit, a stream, a job, or a prompt.
- Comment-bait or a course funnel. That is not a strategy in this engine.
- Adding a file to the lint or typing debt lists in `pyproject.toml`. They only shrink.

## How to work here

- `just ci` after each logical change. It is exactly what CI runs: contract, lint, types, import boundaries, shell lint, file size, gate integrity, tests, docs links, and architecture coverage. Fix what it reports rather than running a second linter.
- `just verify` before saying a task is done. It starts as `just ci`, and this project can extend it with what "ran it like a user" means here.
- `just fmt` to format. `just sync` after changing `pyproject.toml`.
- Conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`.
- Significant decisions get an ADR in `docs/decisions/`, numbered flat.
- Coverage ratchet: `fail_under` and `--cov-fail-under` in `pyproject.toml` only rise, together.

## The learning loop

The engine and the agent that runs it get better with every piece. A mistake a person had to point out is not made twice. Each time a person corrects a result, gives a verdict with a reason, or a paid call disappoints, follow `.agents/skills/learn-from-feedback/SKILL.md`:

1. **Record it.** Put the person's words in `kalainova verdict ... --note`.
2. **Find the root cause.** It could be a prompt's wording, a default, the still, the model, a missing check, or how the agent worked.
3. **Research before changing anything.** Read the vendor's docs and prompt guides, and mark the evidence as vendor, independent, our own takes, or inference.
4. **Fix it where every later job gets the fix:**
   - a versioned prompt in `prompts/`;
   - a config default or limit;
   - a plan or readiness check;
   - a judge;
   - a test;
   - or, when it is about how an agent works, this file or a skill.

   A hand edit to one job's files is only a stopgap. Name it as one.
5. **Prove it.** Run a free check first: a dry run shows the new prompt, or readiness flags the old mistake. Then run the smallest real test.
6. **Log it.** Add one file to `.agents/memory/`: what happened, the root cause, where the fix lives, and whether it is proved.

Know what a model reads before writing for it: its prompt field and limit, its guide, and what it decides itself. A first take should already follow every lesson.

## Architecture documentation

Every top-level module or package directly under `src/kalainova/` needs a
matching `## <Name>` section in `ARCHITECTURE.md`: purpose, public interface, dependencies, and
— if its internal flow isn't obvious from the name — a small ASCII/Unicode box diagram in a
plain (untagged) fenced code block. Hand-drawn, not Mermaid: a diagram you redraw in the same PR
as the code change, not a separate rendering step.

`ARCHITECTURE.md` carries two diagrams above the per-component sections: the **System
Overview** (runtime view — data/control flow, external services included) and the **Component
Diagram** (static view — one box per top-level component, an arrow wherever one imports
another; it should agree with `.importlinter`). Redraw the Component Diagram in the same PR that
adds, removes or re-wires a component.

- `just ci-arch` blocks CI if a component has no section, or no box in the Component Diagram —
  mechanical presence only.
- It does **not** verify the content still matches the code. Run `/arch-review`
  (`.agents/skills/arch-review/SKILL.md`) periodically, or after a PR that changes a documented
  component's behavior, to catch drift the coverage check can't see.
- Add the component's section and its Component Diagram box in the **same PR** that adds the
  component — don't defer it.

## Agent-memory convention

After a significant multi-step task, save reusable lessons about the engine to `.agents/memory/`.
It is git-tracked, so it survives a devcontainer rebuild and travels with the repo. One file per
insight; `MEMORY.md` index (one line per entry). This prevents knowledge loss across sessions
and feeds the coaching loop (Factor 2/3 of 12-factor-agents).

This repo is public, and other operators use it. `.agents/memory/` holds lessons any operator
would hit, never one operator's decisions, budgets, keys, paths, or pieces: those belong in the
harness's private memory. Inside the devcontainer, `post-create.sh` links Claude Code's project
memory (`~/.claude/projects/<project-slug>/memory/`) to `.agents/memory/`, so a personal note
written there would land in the public repo; keep it out. Outside the devcontainer the two are
separate folders.

## Harness configuration and the AI-usage cockpit

Per-harness safety config (Claude Code, Codex, goose) and the devcontainer's AI-usage tools
(codeburn, abtop, graphify, ctx, `/dev-coach`) are in
`docs/explanation/agent-harness-and-cockpit.md`. None of them replaces CI. Most of the cockpit
exists only inside the devcontainer, so check a tool is installed before relying on it.

## Forbidden patterns — never do these

- `git commit --no-verify` — fix the violation, never skip the gate.
- Inline prompt literals (200+ chars) — move to `prompts/` and load at runtime.
- Bare `# noqa` or `# type: ignore` without a specific code and reason.
- Hardcode secrets — use `.env` (gitignored) and `.env.example` as the template.
- Lower the coverage floor (`fail_under` or `--cov-fail-under`) — raise both together.
  On `copier update`, keep `coverage_fail_under` in `.copier-answers.yml` at the current
  floor so a default of `0` cannot silently rewrite a raised ratchet.
- `continue-on-error: true` in CI to silence a failing step.
- `pre-commit uninstall` — the hooks are the guardrails, not obstacles.
- Commit to `main` without CI green.
- `Co-authored-by` / `Co-Authored-By` trailers in commits (AI, Cursor account, or
  otherwise). Commits are authored solely as the GitHub credential owner that pushes.
