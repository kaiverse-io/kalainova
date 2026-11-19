"""Text from a model on a subscription the studio already has, through its own command line, as
an `llm` provider: Claude Code (`claude -p`) or Codex (`codex exec`).

KALAINOVA_LLM_CLI names the command. `models.cli.kind` says which it is (`claude` by default) and
`models.cli.llm` the model to ask, else the command's own default. The prompt goes in on standard
input, the command runs in an empty folder of its own with its tools off, so it reads nothing of
this machine, and its answer is the text. It costs nothing beyond the subscription. What is asked
leaves this machine for that vendor, as anything asked of that subscription does, so a studio lists
"cli" under `preference.llm` only when it is content with that.
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


def argv(kind: str, command: str, model: str, answer: Path) -> list[str]:
    """The command line for one question, the prompt to come on standard input."""
    if kind == "claude":
        return [command, "-p", "--output-format", "text", "--allowedTools", "",
                *(["--model", model] if model else [])]  # fmt: skip
    if kind == "codex":
        return [command, "exec", "--skip-git-repo-check", "-s", "read-only", "-o", str(answer),
                *(["-m", model] if model else []), "-"]  # fmt: skip
    raise ValueError(f"models.cli.kind is one of {', '.join(KINDS)}, not {kind!r}")


@register
class CommandLineModel(Provider):
    name = "cli"
    capabilities = ("llm",)
    env_key = COMMAND_ENV
    free = True  # the studio's subscription; a call costs nothing more

    def missing_env(self, capability: str = "") -> list[str]:
        missing = super().missing_env(capability)
        if not missing and not Path(os.environ[COMMAND_ENV]).is_file():
            missing.append(f"{COMMAND_ENV} names no file")
        return missing

    def llm(self, req: TextRequest, ctx: Context) -> Result:
        if req.images:
            raise ValueError("the cli provider takes text only")
        kind = model_for("cli", "kind") or "claude"
        model = ctx.model or model_for("cli", "llm")
        prompt = f"{req.system}\n\n{req.prompt}".strip() if req.system else req.prompt
        with tempfile.TemporaryDirectory(prefix="kalainova-cli-") as tmp:
            answer = Path(tmp) / "answer.txt"
            proc = subprocess.run(  # noqa: S603 - a list, never a shell string
                argv(kind, os.environ[COMMAND_ENV], model, answer),
                input=prompt, capture_output=True, text=True, cwd=tmp,
                timeout=ctx.deadline_sec, check=False,
            )  # fmt: skip
            if proc.returncode != 0:
                raise RuntimeError(f"{kind}: {(proc.stderr or proc.stdout)[-800:]}")
            text = answer.read_text() if kind == "codex" and answer.exists() else proc.stdout
        if not text.strip():
            raise RuntimeError(f"{kind} answered nothing")
        return Result(model=f"{kind}:{model or 'default'}", text=text.strip())
