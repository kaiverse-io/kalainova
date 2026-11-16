---
name: a-falling-test-count-is-a-failure
description: A new test file was written over an existing one with the same name; 26 tests vanished and CI stayed green; compare the collected count, not only pass/fail
metadata:
  type: feedback
---
A new `tests/test_prices.py` was written for a new module, but a file of that name already held 26 tests of the price table. Writing it replaced them. `just ci` stayed green: every remaining test passed and coverage held above the floor. What gave it away was the count: 1210 passed against 1225 before, after tests had been *added*.

**Why:** a test that no longer exists cannot fail, so pass/fail and the coverage floor never show tests that were lost.

**How to apply:**
- Before creating a file, check that the path is free (`ls`, or `git ls-files <path>`), and name new test files after the behaviour they cover.
- After any change that touches `tests/`, compare `pytest --collect-only -q | tail -1` with the count before. A drop with no deleted test is a defect.
- When a count drops, compare per-file counts against the last commit (`git stash`, collect, `git stash pop`) to find the file.

See [[drive-a-command-before-calling-it-done]].
