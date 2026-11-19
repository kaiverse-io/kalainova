"""A mix matched to a reference track by Matchering 2.0 (GPL-3.0), with its limiter off.

Runs in an environment with the matchering package, not the engine's:

    python matchering_run.py --target MIX --reference REF --out OUT.wav --report OUT.json

Matchering matches the target's RMS, its frequency response (a mid/side EQ, which is also what
moves its stereo width), and its peak amplitude to the reference. Its own limiter (Hyrax) holds
sample peaks only, so it is off here, and so is its peak normalisation. OUT.wav is 32-bit float
and may run past full scale: the engine's oversampled limiter sets the level and the true peak
afterwards. Matchering works at 44.1 kHz inside, so OUT.wav is at 44.1 kHz.

REPORT gets `{"warnings": [...], "info": [...]}`, Matchering's own messages with their codes, such
as a clipped or already limited target. They are kept with the take, so a person can see what
the tool said.

This file is not named after a package it imports: a script's own folder comes first on its
import path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import matchering as mg


def main() -> None:
    ask = argparse.ArgumentParser()
    ask.add_argument("--target", type=Path, required=True)
    ask.add_argument("--reference", type=Path, required=True)
    ask.add_argument("--out", type=Path, required=True)
    ask.add_argument("--report", type=Path, required=True)
    args = ask.parse_args()
    said: dict[str, list[str]] = {"warnings": [], "info": []}
    mg.log(
        warning_handler=lambda text: said["warnings"].append(str(text)),
        info_handler=lambda text: said["info"].append(str(text)),
        show_codes=True,
    )
    mg.process(
        target=str(args.target),
        reference=str(args.reference),
        results=[mg.Result(str(args.out), subtype="FLOAT", use_limiter=False, normalize=False)],
    )
    args.report.write_text(json.dumps(said, indent=2) + "\n")


if __name__ == "__main__":
    main()
