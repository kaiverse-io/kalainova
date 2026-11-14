"""Whether a picture shows a character: each face found in it, compared with the kit's faces.

The engine ships no face model. `identity.face_command` in config/studio.yaml is an argument list
for a command that takes `--out FILE` and image paths after it, and writes one JSON object to
FILE, `{path: [face, ...]}`, where a face is `{"box": [x, y, w, h], "score": s,
"embedding": [floats]}`.
`providers/runners/face_run.py` is one such command (OpenCV's YuNet detector and SFace
recognizer), run in an environment of its own.

Every face in a picture is compared with every reference face, so a crowd is read face by face:
the reading says how many faces were found and how close the nearest one comes to the character.
With no command configured nothing is measured, and a caller reports a gap, never a pass.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .. import config, opentools
from ..jobfs import ContractError
from .readings import Reading

FACE_TIMEOUT_SEC = 300.0


@dataclass(frozen=True)
class Face:
    box: tuple[float, float, float, float]
    score: float
    embedding: tuple[float, ...]

    @property
    def area(self) -> float:
        return self.box[2] * self.box[3]


@dataclass(frozen=True)
class Match:
    """What one picture's faces say against a set of reference faces."""

    faces: int
    best: float | None  # cosine similarity of the closest face to any reference; None: no face
    matching: int  # faces at or above the limit

    def detail(self, limit: float) -> str:
        if not self.faces:
            return "no face found"
        return (
            f"{self.faces} face(s); closest {self.best:.3f}; "
            f"{self.matching} at or above {limit:g}, a limit not yet checked against verdicts"
        )


def _settings() -> dict[str, Any]:
    return dict(config.studio().get("identity") or {})


def configured() -> bool:
    """Whether a face command is set. Without one, identity is a gap that a person fills."""
    return bool(_settings().get("face_command"))


def limit() -> float:
    """Cosine similarity at or above which two faces are read as one person."""
    return float(_settings().get("same_face_min", 0.363))


def faces(paths: list[Path]) -> dict[Path, list[Face]]:
    """Every face in each picture, from one run of the configured command."""
    command = [str(Path(part).expanduser()) for part in _settings().get("face_command") or []]
    if not command:
        raise ContractError("no identity.face_command in config/studio.yaml")
    wanted = [str(p.resolve()) for p in paths]
    with tempfile.TemporaryDirectory() as tmp:
        out_file = Path(tmp) / "faces.json"
        run = opentools.run([*command, "--out", str(out_file), *wanted], timeout=FACE_TIMEOUT_SEC)
        if run.returncode != 0:
            raise ContractError(f"the face command failed: {run.stderr.strip()[-400:]}")
        try:
            found = json.loads(out_file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"the face command wrote no readable JSON: {exc}") from exc
    out: dict[Path, list[Face]] = {}
    for path, key in zip(paths, wanted, strict=True):
        rows = found.get(key)
        if rows is None:
            raise ContractError(f"the face command said nothing about {path.name}")
        out[path] = [
            Face(tuple(r["box"]), float(r["score"]), tuple(float(v) for v in r["embedding"]))
            for r in rows
        ]
    return out


def similarity(a: Face, b: Face) -> float:
    va, vb = np.asarray(a.embedding), np.asarray(b.embedding)
    norm = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb / norm) if norm else 0.0


def reference_faces(found: dict[Path, list[Face]], references: list[Path]) -> list[Face]:
    """The largest face in each reference picture. A reference with no face holds nothing."""
    return [max(found[r], key=lambda f: f.area) for r in references if found.get(r)]


def match(picture: list[Face], refs: list[Face], at_least: float) -> Match:
    if not picture or not refs:
        return Match(len(picture), None, 0)
    best_per_face = [max(similarity(face, ref) for ref in refs) for face in picture]
    return Match(
        faces=len(picture),
        best=max(best_per_face),
        matching=sum(s >= at_least for s in best_per_face),
    )


def face_reading(image: Path, references: list[Path]) -> Reading | None:
    """How close the nearest face in a picture comes to the character. None: not measured.

    A picture with no face reads 0, since it was asked to show the character. Warns only: the
    limit is the recognizer's published one, not yet checked against a person's verdicts.
    """
    if not references or not configured():
        return None
    found = faces([image, *references])
    refs = reference_faces(found, references)
    if not refs:
        raise ContractError("no face found in any reference picture")
    result = match(found[image], refs, limit())
    value = 0.0 if result.best is None else result.best
    return Reading(
        id="identity.face_match",
        value=round(value, 4),
        limit=f">= {limit():g}",
        ok=value >= limit(),
    )


def panels_check(panels: list[Path], refs: list[Path]) -> tuple[str, str]:
    """Panels against a cast's faces. A panel with no face says nothing; one whose faces match no
    one in the cast is named. A gap, never a pass, when no face command is set."""
    if not configured():
        return "warn", "no face check configured (identity.face_command); a person compares faces"
    found = faces([*panels, *refs])
    cast = reference_faces(found, refs)
    if not cast:
        return "warn", "no face found in the kit's reference pictures"
    peopled = {p: match(found[p], cast, limit()) for p in panels if found[p]}
    if not peopled:
        return "warn", "no face found in any panel"
    strangers = sorted(p.stem for p, m in peopled.items() if not m.matching)
    closest = min(m.best for m in peopled.values() if m.best is not None)
    detail = f"{len(peopled)} panel(s) with faces; weakest match {closest:.3f} (>= {limit():g})"
    if strangers:
        detail += f"; no cast face in {', '.join(strangers)}"
    return ("warn" if strangers else "pass"), detail
