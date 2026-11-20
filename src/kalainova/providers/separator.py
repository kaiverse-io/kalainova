"""Stems on this machine, from the `audio-separator` command (python-audio-separator), as a
`separate` provider beside fal's.

The tool runs as its own program in its own environment, named by KALAINOVA_AUDIO_SEPARATOR, and
nothing of it is here. The checkpoint is `models.separator.separate` in config/studio.yaml, and the
tool downloads it on first use into KALAINOVA_SEPARATOR_MODELS when that is set. It runs on Apple
Silicon's GPU (MPS): a 3-minute take took 28 s on an M5 Pro with the Mel-RoFormer vocal model.

Both stems are written at the source's own sample rate. The tool resamples to 44.1 kHz unless it
is told the rate, and a stem at another rate cannot be laid back on its mix sample for sample.
List "separator" under `preference.separate` to use it. It costs nothing.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from .. import media
from ..config import model_for
from .base import Provider, register
from .contract import Context, Result, SeparateRequest

COMMAND_ENV = "KALAINOVA_AUDIO_SEPARATOR"
MODELS_ENV = "KALAINOVA_SEPARATOR_MODELS"
DEFAULT_MODEL = "vocals_mel_band_roformer.ckpt"
OTHER_NAMES = ("(other)", "(instrumental)", "(no vocals)")


def stems_in(folder: Path) -> tuple[Path, Path]:
    """The vocal and the other stem the tool left, by the stem name it writes into each file."""
    found = sorted(folder.glob("*.wav"))
    sung = next((f for f in found if "(vocals)" in f.name.lower()), None)
    other = next(
        (f for f in found if f is not sung and any(k in f.name.lower() for k in OTHER_NAMES)), None
    )
    if sung is None or other is None:
        raise RuntimeError(
            f"audio-separator left {[f.name for f in found]}, not a vocal and a rest"
        )
    return sung, other


@register
class Separator(Provider):
    name = "separator"
    capabilities = ("separate",)
    env_key = COMMAND_ENV
    free = True
    synthetic = False  # a split of the audio it is given; that audio's record says how it was made

    def missing_env(self, capability: str = "") -> list[str]:
        missing = super().missing_env(capability)
        if not missing and not Path(os.environ[COMMAND_ENV]).is_file():
            missing.append(f"{COMMAND_ENV} names no file")
        return missing

    def separate(self, req: SeparateRequest, ctx: Context) -> Result:
        model = ctx.model or model_for("separator", "separate") or DEFAULT_MODEL
        rate = int(media.stream_info(req.src, "audio").get("sample_rate") or 48000)
        with tempfile.TemporaryDirectory() as tmp:
            cmd = [
                os.environ[COMMAND_ENV], str(req.src),
                "--model_filename", model,
                "--output_dir", tmp,
                "--output_format", "WAV",
                "--sample_rate", str(rate),
            ]  # fmt: skip
            if os.environ.get(MODELS_ENV):
                cmd += ["--model_file_dir", os.environ[MODELS_ENV]]
            proc = subprocess.run(  # noqa: S603 - a list, never a shell string
                cmd, capture_output=True, text=True, timeout=ctx.deadline_sec, check=False
            )
            if proc.returncode != 0:
                raise RuntimeError(f"audio-separator: {(proc.stderr or proc.stdout)[-800:]}")
            sung, other = stems_in(Path(tmp))
            for stem, dst in ((sung, req.vocals), (other, req.rest)):
                media.run(["-i", str(stem), "-ar", str(rate), "-ac", "2", "-c:a", "pcm_s24le",
                           "-f", "wav", str(dst)])  # fmt: skip
        return Result(path=req.vocals, model=f"audio-separator:{model}")
