"""Four aesthetic axes of a recording, scored by Meta's Audiobox Aesthetics (CC-BY-4.0).

Runs in an environment with the audiobox_aesthetics package and soundfile, not the engine's:

    python aesthetics_run.py [--checkpoint FILE] --out FILE audio [audio ...]

With no --checkpoint, the package fetches facebook/audiobox-aesthetics from Hugging Face as
safetensors. Audio is read here and handed over as samples, so the package needs no decoder of
its own. It scores ten-second windows on a 1-10 scale and weights them into one number per axis.
FILE gets `{audio path: {"enjoyment", "usefulness", "complexity", "quality"}}`. These are the
paper's content enjoyment, content usefulness, production complexity and production quality.
They describe speech, sound and music alike, so they say more about production than about a
song, rank takes, and pass nothing. The engine reads them (`bar/judges.py`).

This file is not named after a package it imports: a script's own folder comes first on its
import path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import soundfile
import torch
from audiobox_aesthetics.infer import initialize_predictor

AXES = {"CE": "enjoyment", "CU": "usefulness", "PC": "complexity", "PQ": "quality"}


def main() -> None:
    ask = argparse.ArgumentParser()
    ask.add_argument("--checkpoint", default=None)
    ask.add_argument("--out", type=Path, required=True)
    ask.add_argument("audio", nargs="+")
    args = ask.parse_args()
    predictor = initialize_predictor(args.checkpoint)
    out = {}
    for name in args.audio:
        samples, rate = soundfile.read(name, dtype="float32", always_2d=True)
        row = predictor.forward([{"path": torch.from_numpy(samples.T.copy()), "sample_rate": rate}])
        out[name] = {AXES[k]: round(float(v), 4) for k, v in row[0].items() if k in AXES}
    args.out.write_text(json.dumps(out))


if __name__ == "__main__":
    main()
