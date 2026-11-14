"""Open models on a Mac's GPU, at no cost per call.

Set KALAINOVA_MLX_PYTHON to the python of a separate environment that holds the model packages, and
list "mac" for a capability. docs/how-to/run-models-on-a-mac.md has the setup, measured speeds, and
each model's licence. Each call is its own process, so memory comes back between shots.

A deadline starts once a call holds the GPU, because waiting in the queue is not a slow model. A
call that runs out is really stopped, along with everything it started.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .. import media
from ..config import model_for
from .base import Provider, Result, register
from .local import estimate_words

PYTHON_ENV = "KALAINOVA_MLX_PYTHON"
SONG_PYTHON_ENV = "KALAINOVA_SONG_PYTHON"  # song engines keep their own environment
SONG_CHECKPOINT_ENV = "KALAINOVA_SONG_CHECKPOINT"
RUNNERS = Path(__file__).with_name("runners")
LTX_RUNNER = RUNNERS / "ltx.py"
SONG_RUNNERS = {"heartmula": RUNNERS / "heartmula.py", "ace-step": RUNNERS / "acestep_run.py"}
STILL_MOST_PIXELS = (
    2_200_000  # about 1080p; past this the still model takes minutes and gains little
)
STILL_STEPS = "9"
MUSIC_STEPS = "30"
VIDEO_SIZE = (1472, 832)  # holds 75% of a 1080p frame, which is what the bar asks of a source
VIDEO_FPS = 24
VIDEO_MARGIN_SEC = 0.6  # a clip runs past its shot, so the editor never has to freeze a frame
SECONDS_PER_VIDEO_FRAME = 6.0  # measured at VIDEO_SIZE on a 64 GB machine
DEADLINE_MARGIN = 1.5  # a long shot needs more than a flat deadline allows


def _python() -> Path:
    return Path(os.environ[PYTHON_ENV])


def _seed(text: str) -> str:
    return str(int(hashlib.sha256(text.encode()).hexdigest()[:6], 16))


def _run(cmd: list[str], timeout: float | None = None) -> str:
    """One model on the GPU at a time, across every process, with the machine kept awake.

    Two large models at once fight for unified memory and both slow down, so they queue here.
    """
    lock_path = _python().parents[1] / "gpu.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # an argument list built here, never a shell string
        proc = subprocess.Popen(  # noqa: S603
            ["/usr/bin/caffeinate", "-i", *cmd],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            os.killpg(proc.pid, signal.SIGKILL)  # the model is caffeinate's child, so take both
            proc.wait()
            raise TimeoutError(f"{Path(cmd[0]).name}: no result after {timeout:g}s") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"{Path(cmd[0]).name}: {(err or out)[-800:]}")
    return out


def _weights_revision(repo: str) -> str | None:
    """The exact weights on disk, from the local cache. A repo name alone can change under you."""
    root = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface")
    ref = root / "hub" / f"models--{repo.replace('/', '--')}" / "refs" / "main"
    return ref.read_text().strip() if ref.is_file() else None


def _made_by(repo: str, seed: int | str | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {}
    revision = _weights_revision(repo)
    if revision:
        meta["weights_revision"] = revision
    if seed is not None:
        meta["seed"] = int(seed)
    return meta


def _heard(audio: Path, timeout: float | None = None) -> list[dict[str, Any]]:
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
            ],
            timeout,
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


def _song_options(kw: dict[str, Any]) -> list[str]:
    """What a song asks of its engine beyond the words, in the runners' shared flags."""
    options = [
        arg
        for flag, key in (("--bpm", "bpm"), ("--key", "key"), ("--language", "language"))
        if kw.get(key)
        for arg in (flag, str(kw[key]))
    ]
    return [*options, "--instrumental"] if kw.get("instrumental") else options


@register
class Mac(Provider):
    name = "mac"
    capabilities = ("voice", "image", "video", "music", "song", "separate", "transcribe")
    env_key = PYTHON_ENV
    free = True
    self_timed = True

    def missing_env(self, capability: str = "") -> list[str]:
        missing = super().missing_env(capability)
        if capability == "song" and not os.environ.get(SONG_PYTHON_ENV):
            if SONG_PYTHON_ENV not in missing:
                missing.append(SONG_PYTHON_ENV)
        return missing

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
                ],
                kw.get("deadline_sec"),
            )  # fmt: skip
            raw = next(Path(tmp).glob("v*.wav"))
            media.run(["-i", str(raw), "-ar", "48000", "-ac", "1", str(dst)])
        return Result(
            path=dst, model=f"{model}:{name}", words=_timed_words(dst, text), meta=_made_by(model)
        )

    def image(self, prompt: str, dst: Path, *, width: int, height: int, **kw: Any) -> Result:
        scale = min(1.0, STILL_MOST_PIXELS / (width * height)) ** 0.5
        w, h = int(width * scale) // 16 * 16, int(height * scale) // 16 * 16
        command = model_for("mac", "image")
        seed = kw.get("seed") if kw.get("seed") is not None else _seed(prompt)
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "i.png"
            _run(
                [
                    str(_python().with_name(command)),
                    "--prompt", prompt,
                    "--width", str(w),
                    "--height", str(h),
                    "--steps", STILL_STEPS,
                    "--seed", str(seed),
                    "--quantize", "8",
                    "--output", str(raw),
                ],
                kw.get("deadline_sec"),
            )  # fmt: skip
            # the output keeps its name for the file, and the router's temporary name has no type
            made = Path(tmp) / "out.png"
            media.run(["-i", str(raw), "-frames:v", "1", "-update", "1", str(made)])
            made.replace(dst)
        return Result(path=dst, model=command, meta=_made_by(command, seed))

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
        seed = kw.get("seed") if kw.get("seed") is not None else _seed(prompt)
        raw = dst.with_suffix(".raw.mp4")
        cmd = [
            str(_python()), str(LTX_RUNNER),
            "--prompt", prompt,
            "--width", str(w),
            "--height", str(h),
            "--num-frames", str(frames),
            "--seed", str(seed),
            "--model-repo", model,
            "--output-path", str(raw),
        ]  # fmt: skip
        if not kw.get("audio"):
            cmd.append("--no-audio")
        if image:
            cmd += ["--image", str(image), "--image-strength", "1.0"]
        needed = frames * SECONDS_PER_VIDEO_FRAME * DEADLINE_MARGIN
        limit = kw.get("deadline_sec")
        _run(cmd, max(float(limit), needed) if limit else None)
        raw.replace(dst)
        return Result(path=dst, model=model, meta=_made_by(model, seed))

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
                ],
                kw.get("deadline_sec"),
            )  # fmt: skip
            media.run(["-i", str(raw), "-ar", "48000", "-ac", "2", str(dst)])
        return Result(path=dst, model=model, meta=_made_by(model))

    def song(
        self,
        lyrics: str,
        dst: Path,
        *,
        style: str = "",
        duration: float | None = None,
        **kw: Any,
    ) -> Result:
        """A song through the engine named in config, in its own environment, with its own seed."""
        engine = model_for("mac", "song") or "heartmula"
        python = os.environ.get(SONG_PYTHON_ENV)
        checkpoint = os.environ.get(SONG_CHECKPOINT_ENV)
        if not python or not checkpoint or engine not in SONG_RUNNERS:
            raise RuntimeError(
                f"a song on this machine needs {SONG_PYTHON_ENV}, {SONG_CHECKPOINT_ENV}, and a "
                f"models.mac.song in {sorted(SONG_RUNNERS)}"
            )
        seed = int(kw["seed"]) if kw.get("seed") is not None else int(_seed(lyrics + style))
        with tempfile.TemporaryDirectory() as tmp:
            words, tags, raw = (Path(tmp) / name for name in ("lyrics.txt", "tags.txt", "s.wav"))
            words.write_text(lyrics)
            tags.write_text(style)
            cmd = [
                python, str(SONG_RUNNERS[engine]),
                "--checkpoint", checkpoint,
                "--lyrics", str(words),
                "--tags", str(tags),
                "--seconds", str(math.ceil(duration or 120)),
                "--seed", str(seed),
                "--out", str(raw),
            ]  # fmt: skip
            _run([*cmd, *_song_options(kw)], kw.get("deadline_sec"))
            media.run(["-i", str(raw), "-ar", "48000", "-ac", "2", str(dst)])
        return Result(path=dst, model=engine, meta={"seed": seed})

    def separate(self, src: Path, vocals: Path, rest: Path, **kw: Any) -> Result:
        """Split a mix with audio-separator, installed in the model environment."""
        with tempfile.TemporaryDirectory() as tmp:
            _run(
                [
                    str(_python().with_name("audio-separator")), str(src),
                    "--output_dir", tmp,
                    "--output_format", "WAV",
                ],
                kw.get("deadline_sec"),
            )  # fmt: skip
            found = sorted(Path(tmp).glob("*.wav"))
            sung = next((f for f in found if "vocals" in f.name.lower()), None)
            other = next((f for f in found if "instrumental" in f.name.lower()), None)
            if not sung or not other:
                raise RuntimeError(f"audio-separator left {[f.name for f in found]}")
            for stem, dst in ((sung, vocals), (other, rest)):
                media.run(["-i", str(stem), "-ar", "48000", "-ac", "2", "-f", "wav", str(dst)])
        return Result(path=vocals, model="audio-separator")

    def transcribe(self, src: Path, **kw: Any) -> Result:
        segments = _heard(src, kw.get("deadline_sec"))
        words: list[dict[str, Any]] = []
        for seg in segments:
            start, end = float(seg["start"]), float(seg["end"])
            words += estimate_words(seg["text"].strip(), max(end - start, 0.1), offset=start)
        text = " ".join(seg["text"].strip() for seg in segments)
        return Result(model=model_for("mac", "transcribe"), words=words, text=text)
