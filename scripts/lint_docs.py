#!/usr/bin/env python3
"""Engine docs stay subject-free. Stdlib only.

Fails when an engine doc grows a worked example:
  1. it points at a job folder other than jobs/_template or a placeholder like jobs/<id>/
  2. jobs/_template carries a filled-in subject
  3. a fenced example in a doc fills in "subject" with a real value
  4. it contains a term from the operator's local denylist (.denylist.local, one term per line,
     gitignored, or $KALAINOVA_DENYLIST). The terms never enter the repo; the lint keeps them out.

CLAUDE_HANDOVER.md, real job folders, and evals/contract fixtures are not engine docs.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ["README.md", "AGENTS.md", "ARCHITECTURE.md", "NOTICE.md", "jobs/README.md", "evals/README.md"]
ENGINE_GLOBS = ["docs/**/*.md", "schemas/*.json", "jobs/_template/*", ".claude/skills/**/*.md"]
JOB_REF = re.compile(r"jobs/([A-Za-z0-9_.\-]+)/")
PLACEHOLDER = {"_template"}
FILLED_SUBJECT = re.compile(r'"subject"\s*:\s*"([^"]+)"')


def engine_files() -> list[Path]:
    files = {ROOT / f for f in ENGINE if (ROOT / f).exists()}
    for g in ENGINE_GLOBS:
        files.update(p for p in ROOT.glob(g) if p.is_file())
    return sorted(files)


def denylist() -> list[str]:
    src = Path(os.environ.get("KALAINOVA_DENYLIST", ROOT / ".denylist.local"))
    if not src.exists():
        return []
    return [t.strip() for t in src.read_text().splitlines() if t.strip() and not t.startswith("#")]


def main() -> int:
    problems: list[str] = []
    terms = denylist()
    for path in engine_files():
        rel = path.relative_to(ROOT)
        text = path.read_text(errors="replace")
        for m in JOB_REF.finditer(text):
            name = m.group(1)
            if name not in PLACEHOLDER and not name.startswith("<"):
                problems.append(f"{rel}: points at a job folder 'jobs/{name}/'; a worked example belongs in that job, not the engine docs")
        for m in FILLED_SUBJECT.finditer(text):
            if not m.group(1).startswith("<"):
                problems.append(f"{rel}: fills in a subject ({m.group(1)[:40]!r}); subjects live only in a job folder")
        low = text.lower()
        for term in terms:
            if term.lower() in low:
                problems.append(f"{rel}: contains a denylisted term (see your local denylist)")
    tpl = ROOT / "jobs" / "_template" / "job.json"
    if tpl.exists():
        brief = json.loads(tpl.read_text()).get("brief") or {}
        if any(isinstance(v, str) and v.strip() for v in brief.values()):
            problems.append("jobs/_template/job.json: the template carries a filled brief")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"docs ok ({len(engine_files())} engine files, {len(terms)} local terms)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
