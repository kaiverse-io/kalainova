---
name: drive-a-command-before-calling-it-done
description: Function-level tests passed while a retake a person asked for could go unused; a test that ran the commands in order, as a person would, found it
metadata:
  type: feedback
---
`takes.record` let readings choose among takes. Each function did what its tests said. Then a test ran `make`, `takes`, `retake "The light is wrong."`, and read the output: the person's retake was not in use, because a reading cannot see light and the first take read just as well. Someone who asks for a retake has already seen what no reading can.

The same run also proved that 17 new commands parse and reach their code, which no function-level test covers.

**Why:** a person's intent lives between the functions, in the order they run them.

**How to apply:** For each new set of commands, write one test that drives them through `__main__.main` in the order a person would, and read what they print. Keep it in `tests/test_production_cli.py` style. See [[a-conformance-score-flatters-any-file]].
