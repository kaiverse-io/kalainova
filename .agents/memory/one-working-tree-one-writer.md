---
name: one-working-tree-one-writer
description: A research agent writing into the repo while another agent commits gets its notes swept into an unrelated commit and pushed; give each agent its own folder or worktree
metadata:
  type: feedback
---
One agent delegated a research brief to a second CLI agent that ran in the same working tree. The second agent wrote report and notes folders into the repo. Meanwhile a third agent made a small fix commit on that tree, and the commit took in the notes: about 1,000 lines, including absolute paths from the operator's machine. The branch was pushed to an open PR on this public repo before anyone looked. The commit message named only the fix.

**Why:** the repo is public (ADR 0010). A broad `git add` takes in whatever another process has written, and a pushed commit's files stay visible in the PR after they are removed.

**How to apply:** point a research or delegated agent at a folder outside the repo (the private home in `$KALAINOVA_HOME`), or give it its own worktree. Before committing, stage named paths, not everything. Read `git diff --cached --stat` and question any file the change didn't make. If notes were already pushed, remove them on the branch before a squash merge so they stay out of `main`.
