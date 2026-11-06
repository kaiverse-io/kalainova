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

ci-lint:
    uv run ruff check .
    uv run ruff format --check .
    uv run mypy src/
    @# import-linter >= 2.16 exits 1 on a config with no contracts; the template ships the slot
    @# empty ("No contracts = linter passes" — see .importlinter), so run it once one exists.
    @if grep -q '^\[importlinter:contract:' .importlinter; then uv run lint-imports; else echo "import-linter: no contracts in .importlinter yet — nothing to check"; fi
    gitleaks detect --source . --verbose
    opengrep scan --config .opengrep/rules/ . --error --severity ERROR

ci-test:
    uv run pytest

# Engine docs stay subject-free. A link check can join this when linkchecker is installed.
ci-docs:
    uv run python scripts/lint_docs.py

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
