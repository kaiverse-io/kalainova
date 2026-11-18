"""Engine and configuration fingerprinting.

Pins a job to the engine version, git commit, prompts hash, and studio config hash that ran it.
Approve and runtime gates verify this fingerprint against the stream's pinned engine version.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from functools import cache
from typing import Any

from . import __version__, resources
from .jobfs import ContractError

ROOT = resources.root()  # the engine's own files: a checkout's root, or the package's data


def engine_version() -> str:
    """The declared version of the kalainova engine."""
    return str(__version__)


def git_sha() -> str:
    """The current git commit SHA, or 'untracked' if git is unavailable or outside a repository.

    An installed copy is never asked: the folder around it may be someone's own repository, whose
    commit says nothing about the engine. Its version is engine_version()."""
    git_bin = shutil.which("git")
    if not git_bin or not resources.in_checkout():
        return "untracked"
    try:
        out = subprocess.check_output(  # noqa: S603 - fixed git argument list
            [git_bin, "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return out if out else "untracked"
    except Exception:
        return "untracked"


@cache
def code_stamp() -> str:
    """The commit the running engine came from, marked `+dirty` when tracked files have changed
    since it, so a paid call made on uncommitted code says so. Read once per process."""
    sha = git_sha()
    git_bin = shutil.which("git")
    if sha == "untracked" or not git_bin:
        return sha if resources.in_checkout() else f"v{engine_version()}"
    try:
        changed = subprocess.check_output(  # noqa: S603 - fixed git argument list
            [git_bin, "status", "--porcelain", "--untracked-files=no"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return sha[:12]
    return sha[:12] + ("+dirty" if changed else "")


def prompts_hash() -> str:
    """SHA-256 hash of all files in prompts/, sorted deterministically by path."""
    prompts_dir = resources.path("prompts")
    if not prompts_dir.is_dir():
        return hashlib.sha256(b"").hexdigest()
    hasher = hashlib.sha256()
    for path in sorted(prompts_dir.rglob("*")):
        if path.is_file():
            rel = str(path.relative_to(prompts_dir)).replace("\\", "/")
            hasher.update(rel.encode("utf-8"))
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def config_hash() -> str:
    """SHA-256 hash of config/studio.yaml."""
    cfg = resources.path("config", "studio.yaml")
    if not cfg.is_file():
        return hashlib.sha256(b"").hexdigest()
    return hashlib.sha256(cfg.read_bytes()).hexdigest()


def fingerprint(models: list[str] | None = None) -> dict[str, Any]:
    """Complete engine fingerprint dictionary."""
    data: dict[str, Any] = {
        "engine_version": engine_version(),
        "git_sha": git_sha(),
        "prompts_hash": prompts_hash(),
        "config_hash": config_hash(),
    }
    if models is not None:
        data["models"] = sorted(set(models))
    return data


def verify(job_data: dict[str, Any], pinned_version: str | None = None) -> None:
    """Verify that a job's recorded engine version matches the pinned version if required."""
    if not pinned_version:
        return
    fp = job_data.get("fingerprint") or {}
    job_ver = fp.get("engine_version") or job_data.get("engine_version")
    if job_ver != pinned_version:
        msg = (
            f"job engine version {job_ver!r} does not match "
            f"stream pinned version {pinned_version!r}"
        )
        raise ContractError(msg)
