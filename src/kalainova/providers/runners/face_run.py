"""Every face in each picture, as an embedding: OpenCV's YuNet detector and SFace recognizer.

Runs in an environment with opencv-python 4.8 or later, not the engine's:

    python face_run.py --models DIR [--arcface FILE] --out FILE image [image ...]

DIR holds face_detection_yunet_2023mar.onnx (MIT) and face_recognition_sface_2021dec.onnx
(Apache-2.0) from the OpenCV model zoo. YuNet finds each face and SFace aligns it. The embedding
is SFace's, or with --arcface an ArcFace ONNX file's (such as insightface's buffalo_l
w600k_r50.onnx, whose weights are for non-commercial research), which told a character from
look-alikes made by the same image model where SFace did not. Embeddings from the two are not
comparable, and each needs its own limit. FILE gets one JSON object, `{image path: [face, ...]}`,
each face `{"box": [x, y, w, h], "score": s, "embedding": [floats, unit length]}`, boxes in
the picture's own pixels. A picture with no face maps to []. This script only describes faces;
the engine compares them (`bar/identity.py`).

This file is not named after a package it imports: a script's own folder comes first on its
import path.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np

DETECTOR = "face_detection_yunet_2023mar.onnx"
RECOGNIZER = "face_recognition_sface_2021dec.onnx"
LONGEST_SIDE = 1280  # detection runs at this size or less; boxes are given back at full size


def arcface_embedder(path: Path) -> Any:
    """ArcFace through OpenCV's DNN module: a 112x112 aligned face, scaled to [-1, 1], RGB."""
    net = cv2.dnn.readNetFromONNX(str(path))

    def embed(aligned: Any) -> Any:
        scale = (127.5, 127.5, 127.5)
        net.setInput(cv2.dnn.blobFromImage(aligned, 1 / 127.5, (112, 112), scale, swapRB=True))
        return net.forward()

    return embed


def describe(detector: Any, recognizer: Any, path: Path, embed: Any = None) -> list[dict[str, Any]]:
    picture = cv2.imread(str(path))
    if picture is None:
        raise SystemExit(f"cannot read {path}")
    scale = min(1.0, LONGEST_SIDE / max(picture.shape[:2]))
    if scale < 1.0:
        picture = cv2.resize(picture, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    height, width = picture.shape[:2]
    detector.setInputSize((width, height))
    _, rows = detector.detect(picture)
    faces = []
    for row in rows if rows is not None else []:
        aligned = recognizer.alignCrop(picture, row)
        vector = (embed(aligned) if embed else recognizer.feature(aligned)).flatten()
        vector = vector / (float(np.linalg.norm(vector)) or 1.0)
        x, y, w, h = (float(v) / scale for v in row[:4])
        faces.append(
            {
                "box": [round(x, 1), round(y, 1), round(w, 1), round(h, 1)],
                "score": round(float(row[-1]), 4),
                "embedding": [round(float(v), 6) for v in vector],
            }
        )
    return faces


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", required=True, help="folder with the two ONNX files")
    parser.add_argument("--out", required=True, help="where to write the JSON")
    parser.add_argument("--arcface", help="an ArcFace ONNX file, to embed with it instead of SFace")
    parser.add_argument("--min-score", type=float, default=0.8, help="detector confidence")
    parser.add_argument("images", nargs="+")
    args = parser.parse_args()
    models = Path(args.models).expanduser()
    detector = cv2.FaceDetectorYN.create(str(models / DETECTOR), "", (320, 320), args.min_score)
    recognizer = cv2.FaceRecognizerSF.create(str(models / RECOGNIZER), "")
    embed = arcface_embedder(Path(args.arcface).expanduser()) if args.arcface else None
    found = {image: describe(detector, recognizer, Path(image), embed) for image in args.images}
    Path(args.out).write_text(json.dumps(found))


if __name__ == "__main__":
    main()
