# How to review a change an agent made

The session that wrote a change is the weakest reviewer of it: it shares the assumptions that
produced the change. A person owns what ships — design, blast radius, and the security boundary.

1. **Let the gates go first.** CI runs `just ci`. Don't spend review time on what it already
   checks; if it is red, the change is not ready.
2. **Review from a fresh context.** Use a second session, or a read-only subagent, that did not
   write the change. Give it the diff and the task, not the first session's reasoning.
3. **Check intent, not just code.** Does the change do what the task asked, and nothing else?
   Unrequested refactors, new dependencies and changed contracts need a reason — an ADR for a
   durable decision.
4. **Look hardest at one-way doors.** Data migrations, deleted data, changed public APIs, new
   credentials or network access, and anything under CODEOWNERS' gate files.
5. **Prefer regenerate over patch.** If the plan is right but the implementation went wrong,
   throw the draft away and regenerate from the plan on a fresh branch, rather than patching it
   round by round. Boundary tests (`tests/boundary/`) are what the new draft must still pass.

Same-session self-review is an exception: say so in the PR when it happened.
