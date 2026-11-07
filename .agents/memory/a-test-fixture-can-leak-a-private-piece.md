---
name: a-test-fixture-can-leak-a-private-piece
description: Wording copied from private work into test fixtures and examples is still private work in a public repo; choose neutral text, and scrub unpushed commits before the first push
metadata:
  type: feedback
---
While building features against real reviewed pieces, a test's sample lyric, a shot description, and a how-to's example of a fault each picked up words from the private work that prompted them. `scripts/lint_docs.py` reads engine docs, not tests, so nothing caught it. Grepping the branch's additions for the private subject's own words did.

**Why:** the repo is public (ADR 0010). A fixture is checked in as surely as a doc, and a commit that is pushed stays in history after the file is fixed.

**How to apply:** Write fixtures from bland, invented text from the start. Before the first push of a branch, list the private jobs' subjects and titles, grep `git diff origin/main` and untracked files for them, then rewrite any unpushed commit that carries them. Brand and platform names get the same check. Name a metric by its own name, not the company that made it.
