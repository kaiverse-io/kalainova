"""HeartMuLa with a seed. Runs in the model's own environment, not the engine's.

The package's example has no seed, so two takes of one song could not be told apart or repeated.
"""

from __future__ import annotations

import argparse

import torch
from heartlib import HeartMuLaGenPipeline


def _device() -> torch.device:
    return torch.device("mps" if torch.backends.mps.is_available() else "cpu")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--lyrics", required=True)
    parser.add_argument("--tags", required=True)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", required=True)
    parser.add_argument("--bpm")
    parser.add_argument("--key")
    parser.add_argument("--language")
    parser.add_argument("--instrumental", action="store_true")
    args = parser.parse_args()
    torch.manual_seed(args.seed)
    device = _device()
    pipe = HeartMuLaGenPipeline.from_pretrained(
        args.checkpoint,
        device={"mula": device, "codec": device},
        # bf16 is the package's default and is not available on every Metal build
        dtype={"mula": torch.float16, "codec": torch.float32},
        version="3B",
        lazy_load=True,
    )
    with torch.no_grad():
        pipe(
            {"lyrics": args.lyrics, "tags": args.tags},
            max_audio_length_ms=args.seconds * 1000,
            save_path=args.out,
            topk=50,
            temperature=1.0,
            cfg_scale=3.0,
        )


if __name__ == "__main__":
    main()
