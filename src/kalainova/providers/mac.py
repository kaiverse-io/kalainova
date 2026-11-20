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
from . import song_text
from .base import Provider, register
from .contract import (
    Context,
    ImageRequest,
    Inputs,
    MotionRequest,
    MusicRequest,
    Result,
    Sent,
    SeparateRequest,
    SongRequest,
    TranscribeRequest,
    VideoRequest,
    VoiceRequest,
    Word,
)
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


def _made_by(repo: str) -> dict[str, Any]:
    revision = _weights_revision(repo)
    return {"weights_revision": revision} if revision else {}


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


def _timed_words(audio: Path, text: str) -> list[Word]:
    """Whisper gives a sentence's real start and end; the script's words are spread inside it."""
    segments = _heard(audio)
    if not segments:
        return estimate_words(text, media.duration(audio))
    start, end = float(segments[0]["start"]), float(segments[-1]["end"])
    words = estimate_words(text, max(end - start, 0.1), offset=start)
    for w in words:
        w["confidence"] = 0.85
    return words


def _song_options(req: SongRequest) -> list[str]:
    """What a song asks of its engine beyond the words, in the runners' shared flags."""
    asked = (("--bpm", req.bpm), ("--key", req.musical_key), ("--language", req.language))
    options = [arg for flag, value in asked if value for arg in (flag, str(value))]
    return [*options, "--instrumental"] if req.instrumental else options


@register
class Mac(Provider):
    name = "mac"
    capabilities = ("voice", "image", "video", "motion", "music", "song", "separate", "transcribe")
    env_key = PYTHON_ENV
    free = True
    self_timed = True

    def inputs(self, capability: str, model: str | None = None) -> Inputs:
        if capability == "song":
            return Inputs(repaint=(model or model_for("mac", "song")) == "ace-step")
        return super().inputs(capability, model)

    def missing_env(self, capability: str = "") -> list[str]:
        missing = super().missing_env(capability)
        if capability == "song" and not os.environ.get(SONG_PYTHON_ENV):
            if SONG_PYTHON_ENV not in missing:
                missing.append(SONG_PYTHON_ENV)
        if capability == "separate" and not missing:
            tool = _python().with_name("audio-separator")
            if not tool.is_file():  # its stems need the tool in the same environment
                missing.append(f"audio-separator beside {PYTHON_ENV}")
        return missing

    def voice(self, req: VoiceRequest, ctx: Context) -> Result:
        text, dst = req.text, req.dst
        name = req.voice or "am_michael"
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
                ctx.deadline_sec,
            )  # fmt: skip
            raw = next(Path(tmp).glob("v*.wav"))
            media.run(["-i", str(raw), "-ar", "48000", "-ac", "1", str(dst)])
        return Result(
            path=dst, model=f"{model}:{name}", words=_timed_words(dst, text), meta=_made_by(model)
        )

    def image(self, req: ImageRequest, ctx: Context) -> Result:
        prompt, dst, width, height = req.prompt, req.dst, req.width, req.height
        scale = min(1.0, STILL_MOST_PIXELS / (width * height)) ** 0.5
        w, h = int(width * scale) // 16 * 16, int(height * scale) // 16 * 16
        command = model_for("mac", "image")
        seed = req.seed if req.seed is not None else int(_seed(prompt))
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
                ctx.deadline_sec,
            )  # fmt: skip
            # the output keeps its name for the file, and the router's temporary name has no type
            made = Path(tmp) / "out.png"
            media.run(["-i", str(raw), "-frames:v", "1", "-update", "1", str(made)])
            made.replace(dst)
        return Result(path=dst, model=command, seed=int(seed), meta=_made_by(command))

    def video(self, req: VideoRequest, ctx: Context) -> Result:
        prompt, dst, duration, aspect, image = (
            req.prompt,
            req.dst,
            req.duration,
            req.aspect,
            req.start,
        )
        w, h = VIDEO_SIZE if aspect == "16:9" else (VIDEO_SIZE[1], VIDEO_SIZE[0])
        # the model takes 8n+1 frames
        frames = math.ceil((duration + VIDEO_MARGIN_SEC) * VIDEO_FPS / 8) * 8 + 1
        # a style line written for stills; "film still" asks a video model for no motion
        prompt = prompt.replace("film still, ", "")
        model = model_for("mac", "video")
        seed = req.seed if req.seed is not None else int(_seed(prompt))
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
        if not req.sound:
            cmd.append("--no-audio")
        if image:
            cmd += ["--image", str(image), "--image-strength", "1.0"]
        needed = frames * SECONDS_PER_VIDEO_FRAME * DEADLINE_MARGIN
        limit = ctx.deadline_sec
        _run(cmd, max(float(limit), needed) if limit else None)
        raw.replace(dst)
        return Result(
            path=dst,
            model=model,
            seed=int(seed),
            sent=Sent(start_frame=image is not None, end_frame=False, seeded=True),
            meta=_made_by(model),
        )

    def motion(self, req: MotionRequest, ctx: Context) -> Result:
        character_image, driving_video, dst = req.character, req.driving, req.dst
        model = model_for("mac", "motion")
        _run(
            [
                str(_python().with_name(model)),
                "--source",
                str(character_image),
                "--driving",
                str(driving_video),
                "--output",
                str(dst),
            ],
            ctx.deadline_sec,
        )
        return Result(path=dst, model=model, meta={"character_image": character_image.name})

    def music(self, req: MusicRequest, ctx: Context) -> Result:
        prompt, dst, duration = req.prompt, req.dst, req.duration
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
                ctx.deadline_sec,
            )  # fmt: skip
            media.run(["-i", str(raw), "-ar", "48000", "-ac", "2", str(dst)])
        return Result(path=dst, model=model, meta=_made_by(model))

    def song(self, req: SongRequest, ctx: Context) -> Result:
        """A song through the engine named in config, in its own environment, with its own seed."""
        lyrics, dst, style, duration = req.lyrics, req.dst, req.style, req.duration
        style = song_text.styled(style, req.sections)  # its tags read no notes on lyric tags
        engine = model_for("mac", "song") or "heartmula"
        python = os.environ.get(SONG_PYTHON_ENV)
        checkpoint = os.environ.get(SONG_CHECKPOINT_ENV)
        if not python or not checkpoint or engine not in SONG_RUNNERS:
            raise RuntimeError(
                f"a song on this machine needs {SONG_PYTHON_ENV}, {SONG_CHECKPOINT_ENV}, and a "
                f"models.mac.song in {sorted(SONG_RUNNERS)}"
            )
        seed = int(req.seed) if req.seed is not None else int(_seed(lyrics + style))
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
            if req.repaint is not None:
                if engine != "ace-step":
                    raise ValueError(f"{engine} cannot repaint a span of a take")
                cmd += [
                    "--task-type",
                    "repaint",
                    "--src-audio",
                    str(req.repaint.source),
                    "--repainting-start",
                    str(req.repaint.start_sec),
                    "--repainting-end",
                    str(req.repaint.end_sec),
                ]
            _run([*cmd, *_song_options(req)], ctx.deadline_sec)
            media.run(["-i", str(raw), "-ar", "48000", "-ac", "2", str(dst)])
        return Result(path=dst, model=engine, seed=seed)

    def separate(self, req: SeparateRequest, ctx: Context) -> Result:
        """Split a mix with audio-separator, installed in the model environment."""
        src, vocals, rest = req.src, req.vocals, req.rest
        with tempfile.TemporaryDirectory() as tmp:
            _run(
                [
                    str(_python().with_name("audio-separator")), str(src),
                    "--output_dir", tmp,
                    "--output_format", "WAV",
                ],
                ctx.deadline_sec,
            )  # fmt: skip
            found = sorted(Path(tmp).glob("*.wav"))
            sung = next((f for f in found if "vocals" in f.name.lower()), None)
            other = next((f for f in found if "instrumental" in f.name.lower()), None)
            if not sung or not other:
                raise RuntimeError(f"audio-separator left {[f.name for f in found]}")
            for stem, dst in ((sung, vocals), (other, rest)):
                media.run(["-i", str(stem), "-ar", "48000", "-ac", "2", "-f", "wav", str(dst)])
        return Result(path=vocals, model="audio-separator")

    def transcribe(self, req: TranscribeRequest, ctx: Context) -> Result:
        segments = _heard(req.src, ctx.deadline_sec)
        words: list[Word] = []
        for seg in segments:
            start, end = float(seg["start"]), float(seg["end"])
            words += estimate_words(seg["text"].strip(), max(end - start, 0.1), offset=start)
        text = " ".join(seg["text"].strip() for seg in segments)
        return Result(model=model_for("mac", "transcribe"), words=words, text=text)
