"""Text from a model on a subscription the studio already has, through its own command line, as
an `llm` provider: Claude Code (`claude -p`) or Codex (`codex exec`).

KALAINOVA_LLM_CLI names the command, or several separated by ":", tried in order: a subscription
that has hit its limit for the day passes the question to the next, so one vendor is never the
only writer. Each command's kind is read from its name (`claude` or `codex`), and
`models.cli.<kind>` names the model to ask, else the command's own default. The prompt goes in on
standard input; the command runs in an empty folder of its own with its tools off, so it reads
nothing of this machine; its answer is the text. It costs nothing beyond the subscription. What is
asked leaves this machine for that vendor, as anything asked of that subscription does, so a studio
lists "cli" under `preference.llm` only when it is content with that.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from ..config import model_for
from .base import Provider, register
from .contract import Context, Result, TextRequest

COMMAND_ENV = "KALAINOVA_LLM_CLI"
KINDS = ("claude", "codex")


def commands() -> list[str]:
    return [c for c in os.environ.get(COMMAND_ENV, "").split(os.pathsep) if c.strip()]


def kind_of(command: str) -> str:
    """Which command line this is, from its file name."""
    name = Path(command).name.casefold()
    found = next((k for k in KINDS if k in name), None)
    if found is None:
        raise ValueError(f"{command}: a cli command is one of {', '.join(KINDS)}, by its name")
    return found


def argv(kind: str, command: str, model: str, answer: Path) -> list[str]:
    """The command line for one question, the prompt to come on standard input."""
    if kind == "claude":
        return [command, "-p", "--output-format", "text", "--allowedTools", "",
                *(["--model", model] if model else [])]  # fmt: skip
    if kind == "codex":
        return [command, "exec", "--skip-git-repo-check", "-s", "read-only", "-o", str(answer),
                *(["-m", model] if model else []), "-"]  # fmt: skip
    raise ValueError(f"a cli command is one of {', '.join(KINDS)}, not {kind!r}")


def _ask(command: str, prompt: str, deadline: float | None) -> tuple[str, str]:
    kind = kind_of(command)
    model = model_for("cli", kind)
    with tempfile.TemporaryDirectory(prefix="kalainova-cli-") as tmp:
        answer = Path(tmp) / "answer.txt"
        proc = subprocess.run(  # noqa: S603 - a list, never a shell string
            argv(kind, command, model, answer),
            input=prompt, capture_output=True, text=True, cwd=tmp, timeout=deadline, check=False,
        )  # fmt: skip
        if proc.returncode != 0:
            raise RuntimeError(f"{kind}: {(proc.stderr or proc.stdout).strip()[-400:]}")
        text = answer.read_text() if kind == "codex" and answer.exists() else proc.stdout
    if not text.strip():
        raise RuntimeError(f"{kind} answered nothing")
    return text.strip(), f"{kind}:{model or 'default'}"


@register
class CommandLineModel(Provider):
    name = "cli"
    capabilities = ("llm",)
    env_key = COMMAND_ENV
    free = True  # the studio's subscription; a call costs nothing more

    def missing_env(self, capability: str = "") -> list[str]:
        missing = super().missing_env(capability)
        if not missing and not any(Path(c).is_file() for c in commands()):
            missing.append(f"{COMMAND_ENV} names no file")
        return missing

    def llm(self, req: TextRequest, ctx: Context) -> Result:
        if req.images:
            raise ValueError("the cli provider takes text only")
        prompt = f"{req.system}\n\n{req.prompt}".strip() if req.system else req.prompt
        failed = []
        for command in commands():
            if not Path(command).is_file():
                failed.append(f"{command}: no such file")
                continue
            try:
                text, model = _ask(command, prompt, ctx.deadline_sec)
            except (RuntimeError, subprocess.TimeoutExpired, OSError) as exc:
                failed.append(str(exc))  # a limit reached or a failure: the next one is asked
                continue
            return Result(model=model, text=text)
        raise RuntimeError("every cli command failed: " + " | ".join(failed))
