---
name: audit-a-review
description: Check an outside review of Kalainova against the code, the stored QA, and the pieces themselves before acting on it. Use when asked to review a review, an issue that scores the project, or a model's verdict on the repo.
---

# Audit a review

A review of the code alone cannot see a frame. Treat its claims as leads, and its score as one reading of its own rubric.

1. **Pin the commit.** Fetch `origin/main` and compare it with the commit the review read. Mark any claim that later commits changed.
2. **Name its rubric.** What would earn a 10? Does that match the operator's target? A review can be right on its rubric and still point at the wrong work.
3. **Check each claim at a line.** Mark it right, stale, wrong, or not a defect. A test fixture is not a production path. Behaviour an ADR chose is a disagreement with that ADR, so say so.
4. **Read what it could not see.** In `$KALAINOVA_HOME`, read `jobs/*/qa.json`, any `approval.json`, and the operator's verdicts. Put each score beside each verdict.
5. **Look at the pieces.** Use `edit_manifest.json` to build a sheet of the first and last frame of every shot, then view two frames at full size. Follow `review-a-piece`. Say what you could not hear or watch.
6. **Check outside claims.** Stars, licences, and links with `gh api`. A tool's providers from its own source tree. Vendor fields and prices from the vendor's docs.
7. **Test its advice against decisions already made:** budget, holds, and the kill checks in `docs/explanation/`.
8. **Stay inside the audit.** Run no model and publish nothing unless asked. Operator verdicts and real briefs stay private, so scrub the audit before posting it to a public issue.
