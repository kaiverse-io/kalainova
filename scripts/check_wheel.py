"""Build the wheel, install it alone in a fresh environment in an empty folder, and run the engine
from there with no checkout and no studio settings (ADR 0027). `just ci-wheel` runs this.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SMOKE = REPO / "scripts" / "wheel_smoke.py"


def run(args: list[str], cwd: Path, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=cwd, env=env, check=True)  # noqa: S603 - fixed argument lists


def main() -> int:
    uv = shutil.which("uv")
    if not uv:
        print("uv is required", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="kalainova-wheel-") as tmp:
        root = Path(tmp)
        dist, venv, empty = root / "dist", root / "venv", root / "empty"
        empty.mkdir()
        run([uv, "build", "--wheel", "--out-dir", str(dist)], cwd=REPO)
        wheel = next(dist.glob("kalainova-*.whl"))
        run([uv, "venv", "--quiet", "--python", sys.executable, str(venv)], cwd=root)
        python = venv / "bin" / "python"
        run([uv, "pip", "install", "--quiet", "--python", str(python), str(wheel)], cwd=root)
        env = {
            k: v for k, v in os.environ.items() if not k.startswith(("KALAINOVA_", "VIRTUAL_ENV"))
        }
        env["KALAINOVA_HOME"] = str(root / "home")  # nothing is written to this user's own folder
        run([str(python), "-I", str(SMOKE)], cwd=empty, env=env)
        run([str(venv / "bin" / "kalainova"), "--help"], cwd=empty, env=env)
    return 0


if __name__ == "__main__":
    sys.exit(main())
