"""ACE-Step 1.5 with a seed. Runs in the model's own environment, not the engine's.

The checkpoint argument is the ACE-Step project folder. On a Mac the project's own scripts set its
MLX backend, so set ACESTEP_LM_BACKEND=mlx in the environment that runs this.

The defaults are the fast setting: the turbo model, 8 steps, and no language model. Quality is set
in the same environment, so a job never names a model:

    ACESTEP_DIT=acestep-v15-sft            the diffusion model; sft and base need CFG and more steps
    ACESTEP_STEPS=32                       8 for turbo, 32 to 100 for sft and base
    ACESTEP_LM_MODEL=acestep-5Hz-lm-1.7B   plans structure and vocal timing; unset to skip

This file is not named acestep.py: a script's own folder comes first on its import path, so that
name would shadow the package it imports.
"""

from __future__ import annotations

import argparse
import os
import shutil
import tempfile
from pathlib import Path

from acestep.handler import AceStepHandler
from acestep.inference import GenerationConfig, GenerationParams, generate_music

DIT = os.environ.get("ACESTEP_DIT", "acestep-v15-turbo")
STEPS = int(os.environ.get("ACESTEP_STEPS", "8"))
LM_MODEL = os.environ.get("ACESTEP_LM_MODEL", "")
LM_BACKEND = os.environ.get("ACESTEP_LM_BACKEND", "mlx")


def _language_model(checkpoint: str):  # type: ignore[no-untyped-def]  # the package ships no types
    """The planning model, or None when the job asks for the fast setting."""
    if not LM_MODEL:
        return None
    from acestep.llm_inference import LLMHandler

    handler = LLMHandler()
    status, ok = handler.initialize(
        checkpoint_dir=str(Path(checkpoint) / "checkpoints"),
        lm_model_path=LM_MODEL,
        backend=LM_BACKEND,
        device="auto",
    )
    if not ok:
        raise SystemExit(f"ace-step language model did not start: {status}")
    return handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--lyrics", required=True)
    parser.add_argument("--tags", required=True)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", required=True)
    parser.add_argument("--bpm", type=float)
    parser.add_argument("--key")
    parser.add_argument("--language", default="en")
    parser.add_argument("--instrumental", action="store_true")
    args = parser.parse_args()
    handler = AceStepHandler()
    handler.initialize_service(project_root=args.checkpoint, config_path=DIT, device="auto")
    planner = _language_model(args.checkpoint)
    params = GenerationParams(
        caption=Path(args.tags).read_text()[:500],
        lyrics=Path(args.lyrics).read_text()[:4000],
        instrumental=args.instrumental,
        bpm=int(args.bpm) if args.bpm else None,
        keyscale=args.key or "",
        vocal_language=args.language.split("-")[0],
        duration=args.seconds,
        inference_steps=STEPS,
        seed=args.seed,
        task_type="text2music",
        thinking=planner is not None,
    )
    config = GenerationConfig(
        batch_size=1, use_random_seed=False, seeds=[args.seed], audio_format="wav"
    )
    with tempfile.TemporaryDirectory() as tmp:
        result = generate_music(handler, planner, params, config, save_dir=tmp)
        if not result.success or not result.audios:
            raise SystemExit(f"ace-step made nothing: {result.error}")
        shutil.copy(result.audios[0]["path"], args.out)


if __name__ == "__main__":
    main()
