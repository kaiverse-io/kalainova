"""How a piece of music strikes an expert listener, scored by MuQ-Eval (MIT).

Runs in an environment with torch, torchaudio, librosa, omegaconf and muq, not the engine's:

    python muqeval_run.py --repo DIR --checkpoint DIR --out FILE audio [audio ...]

--repo is a checkout of github.com/dgtql/MuQ-Eval, whose `src` package holds the model.
--checkpoint holds its A1 files, config.yaml and model_state_dict.pt, from the Hugging Face repo
zhudi2825/MuQ-Eval-A1; the weights are read as tensors only, never as pickled code. The MuQ
encoder it builds on is fetched by the muq package the first time.

The model scores ten-second clips on a 1-5 scale of musical impression; against expert ratings
of generated music its clip-level Spearman is 0.838 (arXiv 2603.22677). A whole track is scored
window by window. FILE gets `{audio path: {"mi": mean, "mi_min": lowest window}}`. Its authors
found it misses faults of structure, and it was not trained on this studio's genres, so a score
ranks takes and passes nothing. The engine reads it (`bar/judges.py`).

This file is not named after a package it imports: a script's own folder comes first on its
import path.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import librosa
import numpy as np
import torch
from omegaconf import OmegaConf

RATE = 24000
WINDOW = 10 * RATE  # the length the model was trained on


def load(repo: Path, checkpoint: Path) -> torch.nn.Module:
    sys.path.insert(0, str(repo))
    from src.model import MusicQualityModel  # the checkout's package, not this engine's

    own = OmegaConf.load(checkpoint / "config.yaml")  # names the checkout's configs it builds on
    bases = [OmegaConf.load(repo / "configs" / f"{name}.yaml") for name in own.get("defaults", [])]
    model = MusicQualityModel(OmegaConf.merge(*bases, own))
    state = torch.load(checkpoint / "model_state_dict.pt", map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    return model.eval()


def windows(path: Path) -> list[np.ndarray]:
    wav, _ = librosa.load(path, sr=RATE, mono=True)
    found = [wav[i : i + WINDOW] for i in range(0, len(wav) - WINDOW + 1, WINDOW)]
    return found or [np.pad(wav, (0, WINDOW - len(wav)))]


def main() -> None:
    ask = argparse.ArgumentParser()
    ask.add_argument("--repo", type=Path, required=True)
    ask.add_argument("--checkpoint", type=Path, required=True)
    ask.add_argument("--out", type=Path, required=True)
    ask.add_argument("audio", nargs="+")
    args = ask.parse_args()
    model = load(args.repo.expanduser(), args.checkpoint.expanduser())
    out = {}
    with torch.no_grad():
        for name in args.audio:
            scores = [
                float(model(torch.from_numpy(np.ascontiguousarray(w)).float()[None])["MI"][0])
                for w in windows(Path(name))
            ]
            out[name] = {"mi": round(float(np.mean(scores)), 4), "mi_min": round(min(scores), 4)}
    args.out.write_text(json.dumps(out))


if __name__ == "__main__":
    main()
