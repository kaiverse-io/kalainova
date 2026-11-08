"""ACE-Step 1.5 with a seed. Runs in the model's own environment, not the engine's.

The checkpoint argument is the ACE-Step project folder. On a Mac the project's own scripts set its
MLX backend, so set ACESTEP_LM_BACKEND=mlx in the environment that runs this.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path

from acestep.handler import AceStepHandler
from acestep.inference import GenerationConfig, GenerationParams, generate_music

DIT = "acestep-v15-turbo"
TURBO_STEPS = 8


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
    params = GenerationParams(
        caption=Path(args.tags).read_text()[:500],
        lyrics=Path(args.lyrics).read_text()[:4000],
        instrumental=args.instrumental,
        bpm=int(args.bpm) if args.bpm else None,
        keyscale=args.key or "",
        vocal_language=args.language.split("-")[0],
        duration=args.seconds,
        inference_steps=TURBO_STEPS,
        seed=args.seed,
        task_type="text2music",
        thinking=False,
    )
    config = GenerationConfig(
        batch_size=1, use_random_seed=False, seeds=[args.seed], audio_format="wav"
    )
    with tempfile.TemporaryDirectory() as tmp:
        result = generate_music(handler, None, params, config, save_dir=tmp)
        if not result.success or not result.audios:
            raise SystemExit(f"ace-step made nothing: {result.error}")
        shutil.copy(result.audios[0]["path"], args.out)


if __name__ == "__main__":
    main()
