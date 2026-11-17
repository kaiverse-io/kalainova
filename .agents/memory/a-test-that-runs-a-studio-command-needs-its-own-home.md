---
name: a-test-that-runs-a-studio-command-needs-its-own-home
description: A test ran `kalainova limits` with no KALAINOVA_HOME, so every CI run wrote limits.json and gates.log.jsonl into the public repo root, and one PR committed them with a local path
metadata:
  type: feedback
---
`jobfs.home()` falls back to the repository when `KALAINOVA_HOME` is unset. A sign-off test passed its `tmp_path` to fixtures, but called `main(["limits", ...])`, which writes the studio's limits through `home()`. So every test run rewrote `limits.json` and appended to `gates.log.jsonl` in the repo root. A PR committed both, carrying a developer's absolute path into the public repo. Found 2026-11-17 because `git status` showed the two files changed after `just ci`.

**Why:** the repo is public, and studio state belongs only in a private home (ADR 0010). A test that writes there leaks quietly, and CI stays green.

**How to apply:** a test that runs a CLI command touching studio state sets `monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))` first. After `just ci`, check `git status` for files you did not edit. Related: [[a-test-fixture-can-leak-a-private-piece]].
