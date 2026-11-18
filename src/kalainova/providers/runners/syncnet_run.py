"""SyncNet as a judge: how well the lips in a clip match its sound (judges.lipsync, ADR 0024).

SyncNet is joonson/syncnet_python (MIT). Run this in its own environment, with its checkout and its
two weight files (data/syncnet_v2.model, detectors/s3fd/weights/sfd_face.pth). For each clip the
authors' own two steps run in the checkout: run_pipeline.py finds and crops the face tracks, and
run_syncnet.py scores each one. Nothing of SyncNet is imported here.

Writes {path: {"confidence": LSE-C, "distance": LSE-D, "offset": frames}} for the face track it is
surest of. Higher confidence and lower distance mean the lips follow the sound more closely; an
offset of 0 means picture and sound line up, at 25 frames a second; `offset_sec` is how late the
lips run behind the sound, in seconds. It was trained on speech, so
read the scores of takes of one sung line against each other, not as a pass mark.

    python syncnet_run.py --repo <checkout> --out scores.json clip.mp4 [clip.mp4 ...]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TRACK = re.compile(
    r"AV offset:\s*(-?\d+).*?Min dist:\s*(-?[\d.]+).*?Confidence:\s*(-?[\d.]+)", re.DOTALL
)
FPS = 25.0  # SyncNet reads every clip at 25 frames a second
MIN_TRACK = 40  # frames at 25 fps: a sung shot is 3 to 4 s, under the authors' default of 100


def score(repo: Path, clip: Path, min_track: int = MIN_TRACK) -> dict[str, float] | None:
    """The face track SyncNet is surest of, or None when it finds no face to score."""
    with tempfile.TemporaryDirectory() as work:
        common = ["--videofile", str(clip.resolve()), "--reference", "take", "--data_dir", work]
        steps = (
            ["run_pipeline.py", *common, "--min_track", str(min_track)],
            ["run_syncnet.py", *common],
        )
        said = ""
        for step in steps:
            done = subprocess.run(  # noqa: S603 - the authors' two scripts, by fixed name
                [sys.executable, *step], cwd=repo, capture_output=True, text=True, check=True
            )
            said = done.stdout + done.stderr
    tracks = [(int(o), float(d), float(c)) for o, d, c in TRACK.findall(said)]
    if not tracks:
        return None
    offset, distance, confidence = max(tracks, key=lambda t: t[2])
    late = round(offset / FPS, 3)  # positive: the lips run behind the sound
    return {
        "confidence": confidence,
        "distance": distance,
        "offset": float(offset),
        "offset_sec": late,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", required=True, type=Path, help="a syncnet_python checkout")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--min-track", type=int, default=MIN_TRACK)
    ap.add_argument("files", nargs="+", type=Path)
    a = ap.parse_args()
    found: dict[str, dict[str, float]] = {}
    for clip in a.files:
        scored = score(a.repo, clip, a.min_track)
        if scored is not None:
            found[str(clip)] = scored
        else:
            print(f"{clip}: no face track long enough to score", file=sys.stderr)
    a.out.write_text(json.dumps(found, indent=2))


if __name__ == "__main__":
    main()
