"""Operator host capability check and hardware support detection.

Decides whether a host environment has the prerequisites to run the engine (Python, ffmpeg, ffprobe,
hardware accelerators, and configured adapters).
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from typing import Any

from . import config


def _tool_version(name: str) -> str | None:
    bin_path = shutil.which(name)
    if not bin_path:
        return None
    try:
        out = subprocess.check_output(  # noqa: S603 - checked tool version
            [bin_path, "-version"], text=True, stderr=subprocess.STDOUT
        ).splitlines()
        return out[0] if out else "present"
    except Exception:
        return "present"


def _accelerator() -> str:
    system = platform.system()
    machine = platform.machine()
    if system == "Darwin" and machine in ("arm64", "aarch64"):
        return "mps"
    if shutil.which("nvidia-smi"):
        return "cuda"
    return "cpu"


def _total_memory_gb() -> float | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return round((pages * page_size) / (1024**3), 2)
    except Exception:
        return None


def check_host() -> dict[str, Any]:
    """Check the current system capabilities and prerequisite tools."""
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 11)

    ffmpeg_ver = _tool_version("ffmpeg")
    ffprobe_ver = _tool_version("ffprobe")

    accel = _accelerator()
    ram = _total_memory_gb()

    # Check configured adapters
    cfg = config.studio()
    adapters_cfg = cfg.get("adapters") or {}
    adapter_status: dict[str, Any] = {}
    for name, spec in adapters_cfg.items():
        if isinstance(spec, dict) and spec.get("use") != "inhouse":
            cmd = spec.get("command", name)
            present = bool(shutil.which(cmd))
            adapter_status[name] = {"use": spec.get("use"), "present": present}
        else:
            adapter_status[name] = {"use": "inhouse", "present": True}

    missing: list[str] = []
    if not py_ok:
        missing.append(f"Python >= 3.11 required (current: {py_ver})")
    if not ffmpeg_ver:
        missing.append("ffmpeg missing on PATH")
    if not ffprobe_ver:
        missing.append("ffprobe missing on PATH")

    supported = len(missing) == 0

    return {
        "status": "supported" if supported else "unsupported",
        "python": {"version": py_ver, "supported": py_ok},
        "ffmpeg": {"present": bool(ffmpeg_ver), "version": ffmpeg_ver},
        "ffprobe": {"present": bool(ffprobe_ver), "version": ffprobe_ver},
        "accelerator": accel,
        "memory_gb": ram,
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "release": platform.release(),
        },
        "adapters": adapter_status,
        "missing": missing,
    }


def cli() -> int:
    """Print the host verification report."""
    host = check_host()
    print(f"Host status: {host['status']}")
    py_status = "ok" if host["python"]["supported"] else "too old"
    print(f"  Python:      {host['python']['version']} ({py_status})")
    print(f"  ffmpeg:      {'present' if host['ffmpeg']['present'] else 'missing'}")
    print(f"  ffprobe:     {'present' if host['ffprobe']['present'] else 'missing'}")
    print(f"  Accelerator: {host['accelerator']}")
    if host["memory_gb"]:
        print(f"  RAM:         {host['memory_gb']} GB")
    print(f"  Platform:    {host['platform']['system']} {host['platform']['machine']}")
    for name, ad in host["adapters"].items():
        state = "inhouse" if ad["use"] == "inhouse" else ("ready" if ad["present"] else "missing")
        print(f"  Adapter {name}: {state}")
    if host["missing"]:
        print("\nMissing requirements:")
        for m in host["missing"]:
            print(f"  - {m}")
        return 1
    return 0
