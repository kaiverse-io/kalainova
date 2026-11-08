# Kalainova — task runner
# https://just.systems  |  run `just` to see all targets

set dotenv-load := true

default:
    @just --list

# ── CI gates (called by .github/workflows/ci.yaml) ───────────────────────────

ci: ci-contract ci-lint ci-test ci-docs ci-arch

# Engine contract: no media blobs, every job, kit, and stream honours the contract, and the
# fixtures under evals/contract pass or fail as they say.
ci-contract: check eval

# engine contract over jobs/, kits/, and streams/
check:
    uv run python scripts/check.py

# contract eval: fixtures that must pass or fail
eval:
    uv run python scripts/check.py --fixtures evals/contract

# Starts as exactly `just ci`; extend it with whatever "ran it like a user" means for this
# project (start the app and hit it, a smoke run, a browser check) — never with a second set of
# linters. AGENTS.md names this command.
# Run before saying a task is done: `ci`, plus this project's own end-to-end checks
verify: ci

ci-lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy src/
    @just _lint-imports
    gitleaks detect --source . --verbose
    opengrep scan --config .opengrep/rules/ . --error --severity ERROR
    @# shellcheck used to run only as a pre-commit hook, so CI (and any session without hooks
    @# installed) never saw it. Same pinned version as the old hook; uvx fetches it from PyPI.
    @files=$(find . -name '*.sh' -not -path './.venv/*' -not -path './.cache/*' -not -path './node_modules/*'); [ -z "$files" ] || uvx --from shellcheck-py==0.10.0.1 shellcheck $files
    @just _ci-file-size
    @just _ci-gate-integrity
    @just _ci-agents-size

ci-test:
    uv run pytest

# Engine docs stay subject-free, and every relative link in the repo's Markdown resolves.
# lychee --offline checks local files only, so it cannot flake on someone else's site. It is
# installed, pinned, by .devcontainer/post-create.sh and CI.
ci-docs:
    uv run python scripts/lint_docs.py
    @command -v lychee >/dev/null || { echo "lychee required — run .devcontainer/post-create.sh"; exit 1; }
    lychee --offline --no-progress --exclude-path .venv --exclude-path .cache --exclude-path node_modules --exclude-path graphify-out '**/*.md'

# Architecture coverage: every top-level src/kalainova/ component must have a
# matching ARCHITECTURE.md section and a box in its Component Diagram (see AGENTS.md
# "Architecture documentation"). Mechanical presence check only — semantic accuracy (are the
# arrows right? does the section still match the code?) is the /arch-review skill's job.
ci-arch:
    #!/usr/bin/env python3
    import pathlib, re, sys

    pkg_dir = pathlib.Path("src/kalainova")
    arch_doc = pathlib.Path("ARCHITECTURE.md")
    excluded = {"__init__.py", "__pycache__", "py.typed"}

    def normalize(name: str) -> str:
        return re.sub(r"[-_\s]+", " ", name).strip().lower()

    components = [
        item.stem if item.suffix == ".py" else item.name
        for item in sorted(pkg_dir.iterdir())
        if item.name not in excluded and not item.name.startswith(".")
        and (item.is_dir() or item.suffix == ".py")
    ]

    if not components:
        print("Architecture coverage: no top-level components under src/kalainova/ yet — nothing to check.")
        sys.exit(0)

    if not arch_doc.exists():
        print(f"::error::ARCHITECTURE.md is missing but src/kalainova/ has {len(components)} component(s): {', '.join(components)}", file=sys.stderr)
        sys.exit(1)

    headings = {
        normalize(m.group(1))
        for m in re.finditer(r"^#{2,3}\s+(.+)$", arch_doc.read_text(), re.MULTILINE)
    }

    missing = [c for c in components if normalize(c) not in headings]
    if missing:
        print("::error::ARCHITECTURE.md is missing a section for: " + ", ".join(missing), file=sys.stderr)
        print("::error::Add a '## <Name>' section (purpose, dependencies, ASCII diagram if non-trivial) — see AGENTS.md.", file=sys.stderr)
        sys.exit(1)

    # Component Diagram: every component must be named inside that section's fenced block(s),
    # so a new component cannot land without a box. Arrows are /arch-review's job, not this gate's.
    text = arch_doc.read_text()
    section = re.search(r"^## Component Diagram[ \t]*\n(.*?)(?=^## |\Z)", text, re.MULTILINE | re.DOTALL)
    if not section:
        print("::error::ARCHITECTURE.md has no '## Component Diagram' section — one box per top-level component, arrows for imports. See AGENTS.md.", file=sys.stderr)
        sys.exit(1)
    blocks = re.findall(r"^```[^\n]*\n(.*?)^```", section.group(1), re.MULTILINE | re.DOTALL)
    drawn = re.sub(r"<!--.*?-->", " ", "\n".join(blocks), flags=re.DOTALL)
    drawn = " " + re.sub(r"[^a-z0-9]+", " ", normalize(drawn)) + " "
    undrawn = [c for c in components if " " + re.sub(r"[^a-z0-9]+", " ", normalize(c)) + " " not in drawn]
    if undrawn:
        print("::error::ARCHITECTURE.md's Component Diagram has no box for: " + ", ".join(undrawn), file=sys.stderr)
        print("::error::Draw it in the '## Component Diagram' fenced block, with arrows for what it imports — see AGENTS.md.", file=sys.stderr)
        sys.exit(1)

    print(f"Architecture coverage: all {len(components)} component(s) documented in ARCHITECTURE.md and drawn in its Component Diagram.")

# import-linter >= 2.16 exits 1 on a config with no contracts; the template ships the slot empty
# ("No contracts = linter passes" — see .importlinter), so run it once one exists. Shared by
# ci-lint and the pre-commit hook, so the two cannot drift.
[private]
_lint-imports:
    @if grep -q '^\[importlinter:contract:' .importlinter; then uv run lint-imports; else echo "import-linter: no contracts in .importlinter yet — nothing to check"; fi

# Giant files invite more giant files. No hand-written Python file under src/ or tests/ may pass
# max_file_lines. Lower it as the code base allows; raising it is a reviewed change to this file
# (CODEOWNERS), never a quiet fix to a red build.
max_file_lines := "500"

[private]
_ci-file-size:
    #!/usr/bin/env python3
    import pathlib, sys
    limit = int("{{ max_file_lines }}")
    over = [
        (p, n)
        for root in ("src", "tests")
        for p in sorted(pathlib.Path(root).rglob("*.py"))
        if (n := len(p.read_text(errors="replace").splitlines())) > limit
    ]
    for p, n in over:
        print(f"::error file={p}::{p} has {n} lines (limit {limit}) — split it by responsibility", file=sys.stderr)
    sys.exit(1 if over else 0)

# Every session loads AGENTS.md before doing anything, so each line costs context on every task.
# Keep it an index that points at docs/, not the docs themselves. Raising the limit is a reviewed
# change (CODEOWNERS).
max_agents_lines := "200"

[private]
_ci-agents-size:
    #!/usr/bin/env python3
    import pathlib, sys
    limit = int("{{ max_agents_lines }}")
    n = len(pathlib.Path("AGENTS.md").read_text().splitlines())
    if n > limit:
        print(f"::error file=AGENTS.md::AGENTS.md has {n} lines (limit {limit}) — move detail into docs/ and link it", file=sys.stderr)
        sys.exit(1)

# The checks an agent runs locally and the checks CI runs must be the same list. Fails when
# .github/workflows/ci.yaml runs a `just` step that `ci` does not list, or skips one it does.
[private]
_ci-gate-integrity:
    #!/usr/bin/env python3
    import pathlib, re, sys
    justfile = pathlib.Path("justfile").read_text()
    wanted = re.search(r"^ci:([^\n]*)$", justfile, re.MULTILINE).group(1).split()
    workflow = pathlib.Path(".github/workflows/ci.yaml").read_text()
    ran = re.findall(r"^\s*run:\s*just\s+(\S+)\s*$", workflow, re.MULTILINE)
    if ran != wanted:
        print(f"::error::ci.yaml runs {ran} but `just ci` is {wanted} — keep them identical", file=sys.stderr)
        sys.exit(1)

# ── Dev helpers ───────────────────────────────────────────────────────────────

fmt:
    uv run ruff format .
    uv run ruff check --fix .

sync:
    uv sync

lint:
    pre-commit run --all-files

# engine tests only, without the coverage report
test:
    uv run pytest -q --no-cov

# ── On-demand (bucket C) ─────────────────────────────────────────────────────

# AI-usage cost/burn report — installed by .devcontainer/post-create.sh
metrics:
    @command -v codeburn >/dev/null || (echo "install codeburn first: npm install -g codeburn" && exit 1)
    codeburn

# Live session monitor (context %, tokens, rate limits) — install: cargo install abtop
monitor:
    @command -v abtop >/dev/null || (echo "install abtop first: cargo install abtop" && exit 1)
    abtop

# Run the dev-coach skill's analysis (also invokable as /dev-coach in Claude Code)
coach:
    @echo "Run '/dev-coach' in Claude Code, or see .agents/skills/dev-coach/SKILL.md"

# ── Code-quality gates for /ub-mode (bucket C, on-demand) ────────────────────
# unclebob/crapper, /dryer, /mutator — CRAP score, structural duplication, mutation testing.
# Pinned to a commit, not a release: upstream publishes none, so (like AEC_COMMIT) bumping a pin
# is a deliberate manual act — read what changed first. Fetched into .cache/ub-tools/ on first
# use; each tool builds its own .venv there. mutator reads crapper from ../crapper, which this
# layout satisfies. See .agents/skills/ub-mode/SKILL.md and chassis ADR-008.
ub_tools := ".cache/ub-tools"
crapper_commit := "6fd92c4c9bcc56efb64a2f8743d5a2993bcfd42d"
dryer_commit := "66ff6d21a42c04afcad89c78a80066176d1294b0"
mutator_commit := "a5a0cb803b66e0cdb8bf471b3b08af701d424a41"

# Fetch the pinned quality tools (idempotent; re-fetches only a tool whose pin moved)
ub-tools:
    #!/usr/bin/env bash
    set -euo pipefail
    fetch() {
        local name="$1" sha="$2" dir="{{ ub_tools }}/$1"
        [ "$(git -C "$dir" rev-parse HEAD 2>/dev/null || true)" = "$sha" ] && return 0
        rm -rf "$dir"
        git init -q "$dir"
        git -C "$dir" fetch -q --depth 1 "https://github.com/unclebob/$name" "$sha"
        git -C "$dir" checkout -q --detach FETCH_HEAD
    }
    fetch crapper {{ crapper_commit }}
    fetch dryer {{ dryer_commit }}
    fetch mutator {{ mutator_commit }}

# CRAP score per function; exits 2 when the worst is over 10 (default scope: src/)
crap *args="src": ub-tools
    # The tool's own coverage run reads empty here, because addopts already runs pytest-cov.
    mkdir -p target/coverage/python
    uv run pytest -q --cov-report=lcov:target/coverage/python/lcov.info
    {{ ub_tools }}/crapper/crapper --threshold 10 --use-existing-coverage {{ args }}

# Structural duplication; reports pairs scoring 0.8 or above (default scope: src/)
dry *args="src": ub-tools
    {{ ub_tools }}/dryer/dryer --threshold 0.8 {{ args }}

# Mutation testing — slow: pass the file you changed. Exits 3 when a mutant survives.
mutate +paths: ub-tools
    {{ ub_tools }}/mutator/mutator {{ paths }}
