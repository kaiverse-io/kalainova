---
name: ub-mode
description: >
  Disciplined engineering when writing or changing code: First Make it Work, then
  Make it Right, then Follow Practice — with crapper, dryer and mutator as the
  deterministic quality gates. Use only when the user runs /ub-mode or asks for it.
---

# ub-mode

> Adapted from [unclebob/ub-mode](https://github.com/unclebob/ub-mode) (MIT, © 2026 Robert C.
> Martin; licence text at the end of this file), itself loosely based on
> [@poteto](https://github.com/poteto)'s rules. Changes from upstream are listed under
> **Adaptations** at the end — chiefly: no direct push to `main`, no unattended deletion, and
> the quality tools run through pinned `just` recipes. Invoke with `/ub-mode`. Opt-in: it is
> never loaded unless asked for.

Every time you are asked to make a change, follow:

* First Make it Work.
* Then Make it Right.
* Follow Practice.

`AGENTS.md` still wins. Where a rule here conflicts with it (Forbidden Patterns, the coverage
ratchet, the ADR rule, the commit convention), follow `AGENTS.md`.

# First Make it Work

## Laziness Protocol

* One decision lives in one place.
* Ship the smallest edit that solves the problem.

## Foundational Thinking

* Get the data shape right before you write the logic.
* Do first whatever helps every later phase.
* If a concurrent writer would matter, do not share state.

## TDD

* Write the failing test before you change the code.
* See it fail for the reason you expect.
* Make the smallest change that makes it pass.
* If an honest test is impractical, do not write a bad one — say so instead.

## Redesign From First Principles

* When a new requirement changes the model, do not bolt it onto the old design.
* Ask what you would have built if it had been there from the start, think that through, and
  deliver it in pieces.
* When it does not change the model, the Laziness Protocol wins: smallest edit.
* A redesign that changes a boundary, a contract or a dependency direction is a significant
  decision — write the ADR first (`docs/decisions/adrs/`).

## Attack the Premise

* When two fixes that share one assumption both fail the same gate, stop fixing.
* Write that assumption down in one sentence and test it directly.
* If it is false, drop it and every change built on it before starting another fix.

## Subtract Before You Add

* Take complexity out before you add anything.

## Outcome-Oriented Execution

* Aim at the end state you can check.
* A break in the middle is allowed when you planned it and can undo it.

## Build the Lever

* When the same mechanical change has to be made in many places, build the tool that makes it.
* Do one unit by hand, then make the tool match that unit.
* Do not build a tool for work you could finish by hand in less time.

## Architecture

### Model the Domain

* Put the domain in a structure that makes the illegal states impossible.
* Maintain a glossary of domain terms.
* If the code is already clear and local, leave it.

### Boundary Discipline

* Check the data where it enters.
* Inside, trust it.
* Keep the business logic in a pure function.
* Keep `.importlinter`'s contracts and `ARCHITECTURE.md`'s Component Diagram true to the
  boundaries you draw.

### Type System Discipline

* Make the illegal value impossible to write.
* Parse outside data once, where it comes in.
* Do not silence the type checker — no bare `# type: ignore`.

### Make Operations Idempotent

* Running it twice, or running it after a crash halfway through, ends in the same state.

### Separate Before Serializing Shared State

* If they do not need the same mutable thing, give each its own.
* If they do, allow one writer, and enforce that in the structure.

# Then Make it Right

## Fix Root Causes

* Reproduce it.
* Fix the cause.
* A guard that only hides the crash is not a fix.

## Sequence Work into Verifiable Units

* Finish one small unit and check it.
* Then start the next.

## Test Behavior, Not Implementation

* The test calls the code the way its user does and checks the result that user would see.
* If the test would still pass when every function returned nothing, throw it out.

## Crapper — `just crap`

* Run `just crap` (CRAP = CC² × (1 − coverage)³ + CC, per function, threshold 10).
* Bring each function under CRAP 10 by splitting it, by testing it, or both.
* Consider whether a `match`/`if` chain is worth reducing before splitting it.

## Dryer — `just dry`

* Run `just dry` and eliminate duplication that scores 0.8 or above.
* A pair the tool flags is a candidate, not a verdict: merge only when both copies change for
  the same reason.

## Mutator — `just mutate <path>`

* Run `just mutate` on the file you changed, not the whole tree — every covered mutant runs.
* Cover the uncovered.
* Kill the survivors.
* Delete dead code.

## Refactoring

* Pin what the code does.
* Change the structure.
* Prove the behavior did not change.

# Practice

## Keep a Log

* Keep a log of every action you take and the reason you took it.
* Report that log upon completion.
* A learning worth keeping goes to `.agents/memory/`, per AGENTS.md.

## Guard the Context Window

* Keep the main thread small.
* Send the bulk elsewhere, and keep the summary.

## Worktree Cleanup

* Find what is safe to remove and confirm nothing still in use needs it.
* Ask before deleting anything you did not create in this task.
* Uncommitted work waits for a decision.

## Commit and Push

* Commit often, in small ordered Conventional Commits.
* Each commit says why, what changed, and how you proved it.
* Never `--no-verify`: fix the violation instead.
* Push to a branch and open a pull request. Never push to `main`: `main` moves only when CI is
  green and the change is reviewed.

---

## Adaptations from upstream

| Upstream rule | Here | Why |
|---|---|---|
| "Push to the main line at the end" | Branch + pull request | `AGENTS.md` forbids committing to `main` without CI green |
| Worktree Cleanup: "reclaim the disk" | Ask before deleting what you did not create | Deletion is not reversible |
| Attack the Premise: "count which actors hold the imbalance. Remove the assignment" | Name the assumption, test it, drop it if false | Upstream wording does not map to an action an agent can take |
| Redesign From First Principles (unconditional) | Only when the requirement changes the model; ADR if it moves a boundary | Otherwise it contradicts the Laziness Protocol and invites unrequested refactors |
| Build the Lever: "if the work is not obvious at a glance" | Only for repeated mechanical change | Unbounded, it becomes tool-building instead of the task |
| `crapper` / `dryer` / `mutator` installed ad hoc | `just crap` / `just dry` / `just mutate`, pinned to commits | Chassis pins every third-party install (ADR-004); see ADR-008 |

## Licence (upstream ub-mode)

MIT License

Copyright (c) 2026 Robert C. Martin

Permission is hereby granted, free of charge, to any person obtaining a copy of this software
and associated documentation files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use, copy, modify, merge, publish,
distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or
substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING
BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
