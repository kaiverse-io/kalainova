"""Word timings from the `whisper-cli` command of whisper.cpp, as a second `transcribe` provider.

The `mac` provider's call returns segments only, so its words are spread by estimate. This one asks
the tool for one word per segment (`-ml 1 -sow`) and reads the times it reports. The tool runs as
its own program: it needs a ggml model file, named by KALAINOVA_WHISPER_CPP_MODEL, and nothing is
downloaded here. List "whispercpp" under `preference.transcribe` in config/studio.yaml to use it.
It has been tested against a fake of the command only.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .. import media
from .base import Provider, Result, register

COMMAND = "whisper-cli"
MODEL_ENV = "KALAINOVA_WHISPER_CPP_MODEL"


def parse_words(doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Words from whisper.cpp's JSON: each entry of `transcription` carries offsets in ms."""
    words: list[dict[str, Any]] = []
    for seg in doc.get("transcription") or []:
        text = str(seg.get("text", "")).strip()
        if not text or (text.startswith("[") and text.endswith("]")):
            continue  # a sound marker such as [BLANK_AUDIO], not a word
        off = seg.get("offsets") or {}
        words.append(
            {
                "start_sec": off.get("from", 0) / 1000,
                "end_sec": off.get("to", 0) / 1000,
                "text": text,
                "confidence": 0.9,  # timed by the model, not estimated
            }
        )
    return words


@register
class WhisperCpp(Provider):
    name = "whispercpp"
    capabilities = ("transcribe",)
    env_key = MODEL_ENV
    free = True
    synthetic = False  # a reading of real audio

    def missing_env(self) -> list[str]:
        missing = super().missing_env()
        if shutil.which(COMMAND) is None:
            missing.append(f"{COMMAND} on PATH")
        elif not missing and not Path(os.environ[MODEL_ENV]).is_file():
            missing.append(f"{MODEL_ENV} names no file")
        return missing

    def transcribe(self, src: Path, **kw: Any) -> Result:
        exe = shutil.which(COMMAND) or COMMAND
        model = os.environ[MODEL_ENV]
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "in.wav"
            media.run(["-i", str(src), "-ar", "16000", "-ac", "1", str(wav)])
            stem = Path(tmp) / "out"
            proc = subprocess.run(  # noqa: S603 - a list, never a shell string
                [exe, "-m", model, "-f", str(wav), "-ml", "1", "-sow", "-oj", "-of", str(stem)],
                capture_output=True,
                text=True,
                timeout=kw.get("deadline_sec"),
                check=False,
            )
            out = stem.with_suffix(".json")
            if proc.returncode != 0 or not out.exists():
                raise RuntimeError(f"{COMMAND}: {(proc.stderr or proc.stdout)[-800:]}")
            words = parse_words(json.loads(out.read_text()))
        return Result(
            model=f"whisper.cpp:{Path(model).name}",
            words=words,
            text=" ".join(w["text"] for w in words),
        )
