# Agent harnesses and the AI-usage cockpit

Moved out of `AGENTS.md`, which every agent loads at the start of every session. What follows matters when you set up a harness or the devcontainer, not on every task. Both sections come from the chassis template, so keep them in step with the chassis on `copier update`.

## Harness-specific configuration

This project's safety and quality floor comes from two different places. One is universal: CI and git (Guardrails, Ratchet), which run whichever harness or human wrote the commit. The other is per-harness, via that harness's own config, and it only takes effect once a human explicitly trusts this project on their machine:

- **Claude Code**: `.claude/settings.json` (`permissions.allow`/`deny`). Active once you accept the workspace-trust dialog.
- **Codex CLI**: `.codex/config.toml` (`approval_policy`, `sandbox_mode`) and `.codex/rules/default.rules`. The rules deny `git commit --no-verify` and `git push --no-verify`, best-effort; see that file's own comment for the matching limitation. Active only once you mark this project trusted in Codex; Codex skips `.codex/` entirely for untrusted projects.
- **goose**: there is no project-level config file for goose (confirmed against block/goose's own docs). Instead, `GOOSE_MODE=smart_approve` is set for every process in the devcontainer via `.devcontainer/devcontainer.json`'s `containerEnv`. That is a coarser, session-wide posture, not a per-command allow/deny list, and a `goose` run outside the devcontainer does not inherit it.

None of the three is a substitute for the others, and none is a substitute for CI. Stamping a config file is necessary, never sufficient. See [chassis's docs/explanation/design.md](https://github.com/kaiverse-io/chassis/blob/main/docs/explanation/design.md#harness-neutrality-whats-guaranteed-vs-whats-harness-specific) for the full reasoning.

## AI-usage cockpit and coaching

Most of these are installed by `.devcontainer/post-create.sh`, so outside the devcontainer, check a tool exists before relying on it. The session-start hook mentions only the tools it finds.

- `just metrics` (codeburn: cost and burn by project, model, and task; one-shot rate) and `just monitor` (abtop: live context %, tokens, rate limits). Both read local session data; no OTEL is required.
- **AI Engineer Coach** (VS Code dashboard, [microsoft/ai-engineering-coach](https://github.com/microsoft/ai-engineering-coach)) is **opt-in** (`install_ai_coach`, default off). When enabled, `post-create.sh` builds it from source, pinned to a commit: 45 anti-pattern rules, practice scores, and skill mining. Open it via Cmd/Ctrl+Shift+P → "AI Engineer Coach: Open Dashboard". It is off by default because it builds upstream source unattended, and its **Claude Code session-log support is unconfirmed** (the project documents GitHub Copilot harnesses). If you enable it, verify what it actually surfaces for this project.
- **graphify** (`/graphify`, [Graphify-Labs/graphify](https://github.com/Graphify-Labs/graphify)) turns the repo into a queryable knowledge graph (`graphify-out/graph.json` and `GRAPH_REPORT.md`). `post-create.sh` installs it with `uv tool install graphifyy`. Where it exists, check the report's God Nodes and communities before exploring unfamiliar code.
- **ctx** ([ctxrs/ctx](https://github.com/ctxrs/ctx)) indexes full local session transcripts, not just memory files, for `ctx search "…"`. That lets `/dev-coach` find corrections the agent actually received, not only what a past session chose to write down. `post-create.sh` installs it with its own installer (a prebuilt binary, no Rust toolchain).
- OTEL telemetry is on and exports to the console locally (`.claude/settings.json`). It is the spine for a future OTLP collector and team dashboard (bucket D, which activates at more than one user).
- `/dev-coach` does anti-pattern detection and audits AGENTS.md, for Claude Code session and memory data. It complements AI Engineer Coach rather than replacing it, and draws on `ctx` when present. Run it periodically to close the loop between "the user corrected something" and "the rule is durable in AGENTS.md". See `.agents/skills/dev-coach/SKILL.md`.
- The cockpit is a chassis-level standard, not project-specific: every project stamped from the chassis gets it via `post-create.sh`. See [chassis's docs/explanation/ai-usage-cockpit.md](https://github.com/kaiverse-io/chassis/blob/main/docs/explanation/ai-usage-cockpit.md) for the full writeup, and [ADR-002](https://github.com/kaiverse-io/chassis/blob/main/docs/decisions/adrs/adr-002-ai-usage-cockpit.md).
