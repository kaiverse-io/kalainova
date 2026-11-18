"""Mouth against voice as a judge: does the mouth open and close with the line (judges.lipsync).

A second, plainer reading beside SyncNet, which was trained on speech. For each clip, MediaPipe's
face landmarker (Apache-2.0; its `face_landmarker.task` model) finds the face in every frame, and
the mouth's opening is the gap between the inner lips over the face's height. The clip's own sound
(the line, laid on it by the engine) gives a loudness envelope at the same frame rate. The two are
correlated at every lag up to LAG_MAX frames either way.

Writes {path: {"corr": best correlation, "lag": frames, "lag_sec": seconds, "corr_at_0": the
correlation with no lag, "aperture_sd": how far the mouth moves, "face_share": frames with a
face}}. A positive lag means the mouth moves after the sound. Loudness is not mouth shape, so a
held note reads low; compare takes of one line with each other, never against a pass mark.

    python mouth_run.py --model face_landmarker.task --out scores.json clip.mp4 [clip.mp4 ...]
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

LAG_MAX = 8  # frames either way: about a third of a second at 25 fps
RATE = 16000  # the sound is read at this rate, mono
UPPER, LOWER = 13, 14  # inner lip midpoints in MediaPipe's face mesh
BROW, CHIN = 10, 152  # the top of the forehead and the chin: the face's height
FACE_MIN = 0.6  # a clip with a face in fewer frames than this is not scored


def apertures(clip: Path, model: Path) -> tuple[np.ndarray, float]:
    """The mouth's opening in each frame, over the face's height (NaN with no face), and the fps."""
    import cv2  # the judge's own environment has these; the engine's does not
    import mediapipe as mp

    vision = mp.tasks.vision
    options = vision.FaceLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.VIDEO,
        num_faces=1,
    )
    cap = cv2.VideoCapture(str(clip))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 25.0)
    out: list[float] = []
    with vision.FaceLandmarker.create_from_options(options) as marker:
        n = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame[:, :, ::-1].copy())
            found = marker.detect_for_video(image, int(n * 1000 / fps))
            n += 1
            if not found.face_landmarks:
                out.append(float("nan"))
                continue
            p = found.face_landmarks[0]
            gap = abs(p[LOWER].y - p[UPPER].y)
            height = abs(p[CHIN].y - p[BROW].y) or 1.0
            out.append(gap / height)
    cap.release()
    return np.asarray(out, dtype=float), fps


def loudness(clip: Path, fps: float, frames: int) -> np.ndarray:
    """The sound's loudness in decibels, one value per video frame."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is not on PATH")
    read = [ffmpeg, "-v", "error", "-i", str(clip), "-ac", "1", "-ar", str(RATE), "-f", "f32le"]
    raw = subprocess.run([*read, "-"], capture_output=True, check=True).stdout  # noqa: S603
    sound = np.frombuffer(raw, dtype=np.float32)
    hop = RATE / fps
    env = []
    for i in range(frames):
        part = sound[int(i * hop) : int((i + 1) * hop)]
        rms = float(np.sqrt(np.mean(part**2))) if part.size else 0.0
        env.append(20 * np.log10(rms + 1e-5))
    return np.asarray(env, dtype=float)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    keep = ~(np.isnan(a) | np.isnan(b))
    if keep.sum() < 10 or np.std(a[keep]) == 0 or np.std(b[keep]) == 0:
        return float("nan")
    return float(np.corrcoef(a[keep], b[keep])[0, 1])


def best_lag(mouth: np.ndarray, voice: np.ndarray, fps: float) -> dict[str, float] | None:
    """The lag at which the mouth's opening best follows the voice's loudness, and how well."""
    found = {}
    for lag in range(-LAG_MAX, LAG_MAX + 1):  # positive: the mouth follows the sound
        if lag >= 0:
            found[lag] = _corr(mouth[lag:], voice[: mouth.size - lag])
        else:
            found[lag] = _corr(mouth[:lag], voice[-lag:])
    usable = {k: v for k, v in found.items() if not np.isnan(v)}
    if not usable:
        return None
    lag = max(usable, key=lambda k: usable[k])
    return {
        "corr": round(usable[lag], 4),
        "lag": float(lag),
        "lag_sec": round(lag / fps, 3),
        "corr_at_0": round(found[0], 4) if not np.isnan(found[0]) else float("nan"),
        "aperture_sd": round(float(np.nanstd(mouth)), 4),
        "face_share": round(float(np.mean(~np.isnan(mouth))), 3),
    }


def score(clip: Path, model: Path) -> dict[str, float] | None:
    """The best correlation of mouth and voice, and its lag; None when the face is seldom found."""
    mouth, fps = apertures(clip, model)
    if not mouth.size or np.mean(~np.isnan(mouth)) < FACE_MIN:
        return None
    return best_lag(mouth, loudness(clip, fps, mouth.size), fps)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--model", required=True, type=Path, help="MediaPipe face_landmarker.task")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("files", nargs="+", type=Path)
    a = ap.parse_args()
    found: dict[str, dict[str, float]] = {}
    for clip in a.files:
        scored = score(clip, a.model)
        if scored is not None:
            found[str(clip)] = scored
        else:
            print(f"{clip}: the face is not found in enough frames to score", file=sys.stderr)
    a.out.write_text(json.dumps(found, indent=2))


if __name__ == "__main__":
    main()
