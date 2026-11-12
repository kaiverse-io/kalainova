"""Beats and downbeats from the `beat_this` command (CPJKU/beat_this), as an adapter beside
`beats.py`. The tool is run as its own program in its own environment; nothing of it is here.

`beat_this <audio> -o <out.beats>` writes one line per beat: the time in seconds, then a tab and
the beat's place in its bar, where 1 is a downbeat. The reader accepts a bare time, a 0 or a blank
as "a beat, not a downbeat". It was tried against the real tool (docs/how-to/try-the-open-tools.md).
The tool reads only what soundfile reads (wav, flac, ogg, mp3), so any input is decoded to wav.
"""

from __future__ import annotations

import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .. import media
from ..jobfs import ContractError

COMMAND = "beat_this"


def available(command: str | None = None) -> bool:
    return shutil.which(command or COMMAND) is not None


def _is_one(col: str) -> bool:
    try:
        return float(col) == 1.0
    except ValueError:
        return False


def parse(text: str) -> tuple[list[float], list[float]]:
    beats: list[float] = []
    downbeats: list[float] = []
    for line in text.splitlines():
        cols = line.strip().split("\t") if "\t" in line else line.split()
        if not cols or not cols[0]:
            continue
        try:
            t = float(cols[0])
        except ValueError:
            continue  # a header or a comment
        beats.append(t)
        if len(cols) > 1 and _is_one(cols[1]):
            downbeats.append(t)
    return beats, downbeats


def beat_grid(
    path: Path, duration: float | None = None, command: str | None = None
) -> dict[str, Any]:
    cmd = command or COMMAND
    exe = shutil.which(cmd)
    if exe is None:
        raise ContractError(
            f"adapters.beats is beat_this, but `{cmd}` is not on PATH. Install it in its own "
            "environment (docs/how-to/try-the-open-tools.md) or set adapters.beats.use to inhouse"
        )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "grid.beats"
        wav = Path(tmp) / "in.wav"
        media.run(["-i", str(path), "-vn", "-ac", "1", "-ar", "44100", str(wav)])
        proc = subprocess.run(  # noqa: S603 - the configured command, run as a list
            [exe, str(wav), "-o", str(out)], capture_output=True, text=True, check=False
        )
        if proc.returncode != 0 or not out.exists():
            raise ContractError(f"`{cmd}` failed on {path.name}: {proc.stderr.strip()[-300:]}")
        beats, downbeats = parse(out.read_text())
    if duration:
        beats = [b for b in beats if b < duration]
        downbeats = [b for b in downbeats if b < duration]
    if len(beats) < 2:
        raise ContractError(f"`{cmd}` found fewer than two beats in {path.name}")
    gaps = [b - a for a, b in zip(beats, beats[1:], strict=False)]
    mid = statistics.median(gaps)
    # the tool reports no confidence; how even the gaps are is the nearest honest stand-in
    spread = statistics.median(abs(g - mid) for g in gaps) / mid if mid else 1.0
    return {
        "bpm": round(60 / mid, 2),
        "beats": [round(b, 3) for b in beats],
        "downbeats": [round(b, 3) for b in downbeats],
        "confidence": round(max(0.0, 1 - spread * 5), 3),
    }
