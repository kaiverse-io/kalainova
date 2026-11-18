"""How a person on camera moves, as a judge: head, eyes, and body, apart from the background
(judges.performance).

A whole-frame motion number cannot tell a still person in a moving crowd from a moving person in
a still room, and both read as "motion". This judge reads the person alone, in any clip with one:
singing, speaking, or acting, close or wide. It measures properties, not taste: how far the head
turns, nods, and tilts; how much the eyes travel and how open they are; how much the person moves
once the camera's own movement is taken out; and how much the rest of the frame moves.

MediaPipe (Apache-2.0) gives the face (`face_landmarker.task`, with its head pose and blink
blendshapes) and the person's outline (`selfie_segmenter.tflite`); OpenCV's dense optical flow
gives movement. Movement is a share of the frame's diagonal per second, so a 480p and a 1080p take
of one shot read alike.

Writes {path: {name: number}}. Head ranges are degrees (5th to 95th percentile, so one bad frame
does not set them); `head_travel` and `gaze_travel` are spreads in face heights and eye widths;
`eyes_open` is 0 (shut) to 1; `face_share` and `person_share` say how often each was found, and a
reading that needs the face is left out when it was found too seldom to trust.

    python perform_run.py --face-model face_landmarker.task --person-model selfie_segmenter.tflite
        --out scores.json clip.mp4 [clip.mp4 ...]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

FACE_MIN = 0.6  # readings of the face are left out below this share of frames
PERSON_MIN = 0.02  # a mask this small is not a person
FLOW_WIDTH = 320  # frames are read at this width for movement: enough to see a gesture
BLINK_AT = 0.5  # a blink blendshape over this is a closed eye
NOSE, BROW, CHIN = 1, 10, 152
RIGHT_EYE = (33, 133, 159, 145, 468)  # outer corner, inner corner, upper lid, lower lid, iris
LEFT_EYE = (263, 362, 386, 374, 473)


@dataclass
class Track:
    """Everything read from one clip, frame by frame (NaN where nothing was found)."""

    fps: float = 25.0
    frames: int = 0
    yaw: list[float] = field(default_factory=list)
    pitch: list[float] = field(default_factory=list)
    roll: list[float] = field(default_factory=list)
    nose: list[tuple[float, float]] = field(default_factory=list)
    gaze: list[tuple[float, float]] = field(default_factory=list)
    blink: list[float] = field(default_factory=list)
    subject: list[float] = field(default_factory=list)
    background: list[float] = field(default_factory=list)
    camera: list[float] = field(default_factory=list)
    person: int = 0


def pose(matrix: Any) -> tuple[float, float, float]:
    """Yaw, pitch, and roll in degrees from a face's transformation matrix."""
    m = np.asarray(matrix)[:3, :3]
    pitch = math.degrees(math.atan2(m[2, 1], m[2, 2]))
    yaw = math.degrees(math.asin(max(-1.0, min(1.0, -m[2, 0]))))
    roll = math.degrees(math.atan2(m[1, 0], m[0, 0]))
    return yaw, pitch, roll


def eye_ratio(p: Any, eye: tuple[int, ...], aspect: float = 1.0) -> tuple[float, float] | None:
    """Where the iris sits from the eye's centre, along the line of its corners and across it, in
    eye widths. The width, not the gap between the lids, so a narrowed eye does not inflate it."""
    outer, inner, iris = p[eye[0]], p[eye[1]], p[eye[4]]
    ax, ay = (outer.x - inner.x) * aspect, outer.y - inner.y
    width = math.hypot(ax, ay)
    if width < 1e-6:
        return None
    ux, uy = ax / width, ay / width
    dx = (iris.x - (outer.x + inner.x) / 2) * aspect
    dy = iris.y - (outer.y + inner.y) / 2
    return (dx * ux + dy * uy) / width, (dy * ux - dx * uy) / width


def _face(track: Track, found: Any, aspect: float) -> None:
    if not found.face_landmarks:
        for row in (track.yaw, track.pitch, track.roll, track.blink):
            row.append(float("nan"))
        track.nose.append((float("nan"), float("nan")))
        track.gaze.append((float("nan"), float("nan")))
        return
    p = found.face_landmarks[0]
    yaw, pitch, roll = pose(found.facial_transformation_matrixes[0])
    track.yaw.append(yaw)
    track.pitch.append(pitch)
    track.roll.append(roll)
    height = abs(p[CHIN].y - p[BROW].y) or 1.0
    track.nose.append((p[NOSE].x * aspect / height, p[NOSE].y / height))
    shapes = {s.category_name: s.score for s in (found.face_blendshapes or [[]])[0]}
    closed = [shapes[k] for k in ("eyeBlinkLeft", "eyeBlinkRight") if k in shapes]
    shut = float(np.mean(closed)) if closed else float("nan")
    track.blink.append(shut)
    eyes = [r for r in (eye_ratio(p, RIGHT_EYE, aspect), eye_ratio(p, LEFT_EYE, aspect)) if r]
    seen = eyes and not shut > BLINK_AT  # a shut eye's iris is a guess, so it is not counted
    track.gaze.append(tuple(np.mean(eyes, axis=0)) if seen else (float("nan"), float("nan")))


def split_flow(
    flow: np.ndarray, mask: np.ndarray, diagonal: float, fps: float
) -> tuple[float, ...]:
    """The camera's movement (the background's median), and what moves beyond it inside and
    outside the person, each as a share of the frame's diagonal per second."""
    rest = ~mask
    if rest.sum() < 50:
        return float("nan"), float("nan"), float("nan")
    camera = np.median(flow[rest], axis=0)
    own = np.linalg.norm(flow - camera, axis=2)
    scale = fps / diagonal
    subject = float(own[mask].mean()) * scale if mask.sum() >= 50 else float("nan")
    return float(np.linalg.norm(camera)) * scale, subject, float(own[rest].mean()) * scale


def read(clip: Path, face_model: Path, person_model: Path) -> Track:
    """Read a clip once, frame by frame: the face, the person's outline, and the flow."""
    import cv2  # the judge's own environment has these; the engine's does not
    import mediapipe as mp

    vision = mp.tasks.vision
    faces = vision.FaceLandmarker.create_from_options(
        vision.FaceLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(face_model)),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,
            output_facial_transformation_matrixes=True,
        )
    )
    people = vision.ImageSegmenter.create_from_options(
        vision.ImageSegmenterOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(person_model)),
            running_mode=vision.RunningMode.VIDEO,
            output_confidence_masks=True,
            output_category_mask=False,
        )
    )
    cap = cv2.VideoCapture(str(clip))
    track = Track(fps=float(cap.get(cv2.CAP_PROP_FPS) or 25.0))
    before = None
    with faces, people:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            at = int(track.frames * 1000 / track.fps)
            track.frames += 1
            rgb = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame[:, :, ::-1].copy())
            h, w = frame.shape[:2]
            _face(track, faces.detect_for_video(rgb, at), w / h)
            mask = people.segment_for_video(rgb, at).confidence_masks[-1].numpy_view() > 0.5
            small_h = round(FLOW_WIDTH * h / w)
            gray = cv2.cvtColor(cv2.resize(frame, (FLOW_WIDTH, small_h)), cv2.COLOR_BGR2GRAY)
            small_mask = cv2.resize(mask.astype(np.uint8), (FLOW_WIDTH, small_h)) > 0
            if small_mask.mean() >= PERSON_MIN:
                track.person += 1
            if before is not None:
                flow = cv2.calcOpticalFlowFarneback(before, gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                diagonal = math.hypot(FLOW_WIDTH, small_h)
                camera, subject, background = split_flow(flow, small_mask, diagonal, track.fps)
                track.camera.append(camera)
                track.subject.append(subject)
                track.background.append(background)
            before = gray
    cap.release()
    return track


def _span(values: list[float]) -> float:
    a = np.asarray(values, dtype=float)
    a = a[~np.isnan(a)]
    return float(np.percentile(a, 95) - np.percentile(a, 5)) if a.size else float("nan")


def _spread(points: list[tuple[float, float]]) -> float:
    a = np.asarray(points, dtype=float)
    a = a[~np.isnan(a).any(axis=1)] if a.size else a
    return float(np.hypot(*np.std(a, axis=0))) if len(a) > 1 else float("nan")


def blinks_per_min(blink: list[float], fps: float) -> float:
    """Closings of the eyes per minute: each rise of the blink score past BLINK_AT counts once."""
    a = np.asarray(blink, dtype=float)
    seen = a[~np.isnan(a)]
    if seen.size < 2:
        return float("nan")
    closed = seen > BLINK_AT
    rises = int(np.sum(closed[1:] & ~closed[:-1]))
    return rises * 60.0 * fps / seen.size


def score(track: Track) -> dict[str, float]:
    """The readings of one clip; a face reading is left out when the face was seldom found."""
    n = max(track.frames, 1)
    face_share = float(np.mean(~np.isnan(np.asarray(track.yaw, dtype=float)))) if track.yaw else 0.0
    out = {"face_share": face_share, "person_share": track.person / n}
    for name, row in (
        ("camera_motion", track.camera),
        ("subject_motion", track.subject),
        ("background_motion", track.background),
    ):
        a = np.asarray(row, dtype=float)
        if a.size and not np.isnan(a).all():
            out[name] = float(np.nanmean(a))
    if face_share >= FACE_MIN:
        blink = np.asarray(track.blink, dtype=float)
        out |= {
            "head_yaw_range": _span(track.yaw),
            "head_pitch_range": _span(track.pitch),
            "head_roll_range": _span(track.roll),
            "head_travel": _spread(track.nose),
            "gaze_travel": _spread(track.gaze),
            "eyes_open": float(1.0 - np.nanmean(blink)) if not np.isnan(blink).all() else 0.0,
            "blinks_per_min": blinks_per_min(track.blink, track.fps),
        }
    return {k: round(v, 4) for k, v in out.items() if not math.isnan(v)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--face-model", required=True, type=Path, help="MediaPipe face_landmarker.task")
    ap.add_argument("--person-model", required=True, type=Path, help="selfie_segmenter.tflite")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("files", nargs="+", type=Path)
    a = ap.parse_args()
    found: dict[str, dict[str, float]] = {}
    for clip in a.files:
        try:
            found[str(clip)] = score(read(clip, a.face_model, a.person_model))
        except Exception as exc:  # one unreadable clip must not lose the others
            print(f"{clip}: not read ({exc})", file=sys.stderr)
    a.out.write_text(json.dumps(found, indent=2))


if __name__ == "__main__":
    main()
