"""A composition folder rendered to a file by HyperFrames, for graphics a model should not draw.

Charts, diagrams, and kinetic type stay exact this way: no model invents a number or garbles a word.
The render runs through npx, so it needs Node 22 or newer.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from .base import Provider, Result, register

FORMATS = {".mp4": "mp4", ".mov": "mov", ".webm": "webm"}


@register
class HyperFrames(Provider):
    name = "hyperframes"
    capabilities = ("graphics",)
    free = True
    synthetic = False  # drawn from a composition, not generated

    def missing_env(self, capability: str = "") -> list[str]:
        return [] if shutil.which("npx") else ["npx (Node 22 or newer)"]

    def graphics(self, folder: Path, dst: Path, **kw: Any) -> Result:
        npx = shutil.which("npx") or "npx"
        render_format = FORMATS.get(dst.suffix.lower(), "mp4")
        rate = ["--fps", f"{float(kw['fps']):g}"] if kw.get("fps") else []
        # an argument list built here, never a shell string
        proc = subprocess.run(  # noqa: S603
            [
                npx, "--yes", "hyperframes", "render",
                "--format", render_format,
                "--output", str(dst.resolve()),
                *rate,
            ],
            cwd=folder,
            capture_output=True,
            text=True,
        )  # fmt: skip
        if proc.returncode != 0:
            raise RuntimeError(f"hyperframes: {(proc.stderr or proc.stdout)[-800:]}")
        return Result(path=dst, model="hyperframes")
