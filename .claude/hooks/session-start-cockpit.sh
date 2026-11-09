#!/usr/bin/env bash
# SessionStart hook — refreshes the AI-usage cockpit and reminds the agent it exists.
# Whatever this script prints to stdout is added directly to the agent's context at
# session start (before the first prompt) — see chassis's docs/explanation/
# ai-usage-cockpit.md and design.md ("Coaching" / "Context Engineering" layers).
#
# Best-effort only: SessionStart hooks cannot block the session, so every step here
# is guarded to fail silently rather than surface a startup error for a bucket-C
# (on-demand, never-blocking) tool that may not even be installed in this project.
#
# Every line it prints must be true on this machine: a tool that is not installed is not
# mentioned, because the agent reads this as fact before the first prompt.
set -uo pipefail

lines=()

if command -v graphify >/dev/null 2>&1; then
  graphify update . >/dev/null 2>&1 || true
  if [ -f graphify-out/GRAPH_REPORT.md ]; then
    lines+=("- graphify: graphify-out/GRAPH_REPORT.md is current — check its God Nodes /"
            "  communities before exploring unfamiliar code, instead of re-grepping from scratch.")
  fi
fi

if command -v ctx >/dev/null 2>&1; then
  ctx setup >/dev/null 2>&1 || true
  lines+=("- ctx: run \`ctx search \"<topic>\"\` before starting non-trivial work — it searches full"
          "  past session transcripts, not just memory files, for prior decisions or corrections.")
fi

lines+=("- /dev-coach: run periodically, or right after a corrected mistake, to turn friction"
        "  into a durable AGENTS.md rule instead of relearning it next session.")

echo "AI-usage cockpit for this project (see docs/explanation/agent-harness-and-cockpit.md):"
printf '%s\n' "${lines[@]}"

exit 0
