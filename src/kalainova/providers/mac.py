"""Open models on a Mac's GPU through MLX, at no cost per call.

Set KALAINOVA_MLX_PYTHON to the python of a separate environment that holds the model packages, and
list "mac" for a capability. docs/how-to/run-models-on-a-mac.md has the setup, measured speeds, and
each model's licence. Each call is its own process, so memory comes back between shots.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .. import media
from ..config import model_for
from .base import Provider, Result, register
from .local import estimate_words

PYTHON_ENV = "KALAINOVA_MLX_PYTHON"
LTX_RUNNER = Path(__file__).with_name("runners") / "ltx.py"
STILL_MOST_PIXELS = (
    2_200_000  # about 1080p; past this the still model takes minutes and gains little
)
STILL_STEPS = "9"
MUSIC_STEPS = "30"
VIDEO_SIZE = (1472, 832)  # holds 75% of a 1080p frame, which is what the bar asks of a source
VIDEO_FPS = 24
VIDEO_MARGIN_SEC = 0.6  # a clip runs past its shot, so the editor never has to freeze a frame


def _python() -> Path:
    return Path(os.environ[PYTHON_ENV])


def _seed(text: str) -> str:
    return str(int(hashlib.sha256(text.encode()).hexdigest()[:6], 16))


def _run(cmd: list[str]) -> str:
    """One model on the GPU at a time, across every process, with the machine kept awake.

    Two large models at once fight for unified memory and both slow down, so they queue here.
    """
    lock_path = _python().parents[1] / "gpu.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # an argument list built here, never a shell string
        proc = subprocess.run(  # noqa: S603
            ["/usr/bin/caffeinate", "-i", *cmd], capture_output=True, text=True
        )
    if proc.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name}: {(proc.stderr or proc.stdout)[-800:]}")
    return proc.stdout


def _heard(audio: Path) -> list[dict[str, Any]]:
    """Whisper's segments, each with its start, end, and text."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "t"
        _run(
            [
                str(_python()), "-m", "mlx_audio.stt.generate",
                "--model", model_for("mac", "transcribe"),
                "--audio", str(audio),
                "--output-path", str(out),
                "--format", "json",
                "--language", "en",
            ]
        )  # fmt: skip
        found = next(Path(tmp).glob("*.json"), None)
        return list(json.loads(found.read_text()).get("segments") or []) if found else []


def _timed_words(audio: Path, text: str) -> list[dict[str, Any]]:
    """Whisper gives a sentence's real start and end; the script's words are spread inside it."""
    segments = _heard(audio)
    if not segments:
        return estimate_words(text, media.duration(audio))
    start, end = float(segments[0]["start"]), float(segments[-1]["end"])
    words = estimate_words(text, max(end - start, 0.1), offset=start)
    return [{**w, "confidence": 0.85} for w in words]


@register
class Mac(Provider):
    name = "mac"
    capabilities = ("voice", "image", "video", "music", "transcribe")
    env_key = PYTHON_ENV
    free = True

    def voice(self, text: str, dst: Path, *, voice: str | None = None, **kw: Any) -> Result:
        name = voice or "am_michael"
        model = model_for("mac", "voice")
        with tempfile.TemporaryDirectory() as tmp:
            _run(
                [
                    str(_python()), "-m", "mlx_audio.tts.generate",
                    "--model", model,
                    "--text", text,
                    "--voice", name,
                    "--lang_code", name[0],
                    "--output_path", tmp,
                    "--file_prefix", "v",
                    "--join_audio",
                ]
            )  # fmt: skip
            raw = next(Path(tmp).glob("v*.wav"))
            media.run(["-i", str(raw), "-ar", "48000", "-ac", "1", str(dst)])
        return Result(path=dst, model=f"{model}:{name}", words=_timed_words(dst, text))

    def image(self, prompt: str, dst: Path, *, width: int, height: int, **kw: Any) -> Result:
        scale = min(1.0, STILL_MOST_PIXELS / (width * height)) ** 0.5
        w, h = int(width * scale) // 16 * 16, int(height * scale) // 16 * 16
        command = model_for("mac", "image")
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "i.png"
            _run(
                [
                    str(_python().with_name(command)),
                    "--prompt", prompt,
                    "--width", str(w),
                    "--height", str(h),
                    "--steps", STILL_STEPS,
                    "--seed", _seed(prompt),
                    "--quantize", "8",
                    "--output", str(raw),
                ]
            )  # fmt: skip
            # the output keeps its name for the file, and the router's temporary name has no type
            made = Path(tmp) / "out.png"
            media.run(["-i", str(raw), "-frames:v", "1", "-update", "1", str(made)])
            made.replace(dst)
        return Result(path=dst, model=command)

    def video(
        self,
        prompt: str,
        dst: Path,
        *,
        duration: float,
        aspect: str,
        image: Path | None = None,
        **kw: Any,
    ) -> Result:
        w, h = VIDEO_SIZE if aspect == "16:9" else (VIDEO_SIZE[1], VIDEO_SIZE[0])
        # the model takes 8n+1 frames
        frames = math.ceil((duration + VIDEO_MARGIN_SEC) * VIDEO_FPS / 8) * 8 + 1
        # a style line written for stills; "film still" asks a video model for no motion
        prompt = prompt.replace("film still, ", "")
        model = model_for("mac", "video")
        raw = dst.with_suffix(".raw.mp4")
        cmd = [
            str(_python()), str(LTX_RUNNER),
            "--prompt", prompt,
            "--width", str(w),
            "--height", str(h),
            "--num-frames", str(frames),
            "--seed", _seed(prompt),
            "--no-audio",
            "--model-repo", model,
            "--output-path", str(raw),
        ]  # fmt: skip
        if image:
            cmd += ["--image", str(image), "--image-strength", "1.0"]
        _run(cmd)
        raw.replace(dst)
        return Result(path=dst, model=model)

    def music(self, prompt: str, dst: Path, *, duration: float, **kw: Any) -> Result:
        model = model_for("mac", "music")
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "m.wav"
            _run(
                [
                    str(_python()), "-m", "mlx_audio.music.generate",
                    "--model", model,
                    "--caption", prompt,
                    "--lyrics", "[instrumental]",
                    "--duration", str(math.ceil(duration)),
                    "--steps", MUSIC_STEPS,
                    "--seed", _seed(prompt),
                    "--output", str(raw),
                ]
            )  # fmt: skip
            media.run(["-i", str(raw), "-ar", "48000", "-ac", "2", str(dst)])
        return Result(path=dst, model=model)

    def transcribe(self, src: Path, **kw: Any) -> Result:
        segments = _heard(src)
        words: list[dict[str, Any]] = []
        for seg in segments:
            start, end = float(seg["start"]), float(seg["end"])
            words += estimate_words(seg["text"].strip(), max(end - start, 0.1), offset=start)
        text = " ".join(seg["text"].strip() for seg in segments)
        return Result(model=model_for("mac", "transcribe"), words=words, text=text)
