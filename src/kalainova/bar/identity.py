"""Deterministic, Pillow-only image features for measured identity checks."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .readings import Reading


def embed_image(path: Path) -> list[float]:
    """Describe an image with normalized means and deviations from an 8 by 8 pixel grid."""
    with Image.open(path) as source:
        pixels = np.asarray(source.convert("L").resize((128, 128)), dtype=np.float64) / 255.0

    features = np.empty(128, dtype=np.float64)
    for row in range(8):
        for column in range(8):
            block = pixels[row * 16 : (row + 1) * 16, column * 16 : (column + 1) * 16]
            index = (row * 8 + column) * 2
            features[index] = float(np.mean(block))
            features[index + 1] = float(np.std(block))

    norm = float(np.linalg.norm(features))
    if norm == 0.0:
        # A black image has no nonzero moments; use a stable unit vector for this edge case.
        features[0] = 1.0
        norm = 1.0
    return [float(x) for x in (features / norm)]


def face_distance(path_a: Path, path_b: Path) -> float:
    """Return a bounded cosine distance between two deterministic image embeddings."""
    embedding_a = embed_image(path_a)
    embedding_b = embed_image(path_b)
    norm_a = math.sqrt(sum(value * value for value in embedding_a))
    norm_b = math.sqrt(sum(value * value for value in embedding_b))
    cosine = sum(a * b for a, b in zip(embedding_a, embedding_b, strict=True)) / (norm_a * norm_b)
    return min(1.0, max(0.0, 1.0 - cosine))


def identity_distance(image: Path, references: list[Path]) -> float | None:
    """Return the closest reference distance, or None when no references were supplied."""
    if not references:
        return None
    return min(face_distance(image, reference) for reference in references)


def face_reading(image: Path, references: list[Path], max_distance: float = 0.40) -> Reading | None:
    """Read whether an image falls within the permitted distance of any reference."""
    distance = identity_distance(image, references)
    if distance is None:
        return None
    return Reading(
        id="identity.face_distance",
        value=distance,
        limit=f"<= {max_distance:.2f}",
        ok=distance <= max_distance,
    )


def comic_character_consistency(job: Any) -> tuple[str, str]:
    """Measure character face consistency across comic panels against kit references."""
    panels = sorted((job.work / "panels").glob("*.png"))
    kit_folder = job.folder / "kit"
    references = (
        [
            p
            for p in kit_folder.rglob("*")
            if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg"}
        ]
        if kit_folder.is_dir()
        else []
    )
    if job.job.get("stream") and job.has("kit_lock"):
        from .. import consistency
        from ..kits import blob_path

        locked = consistency.for_job(job)
        if locked:
            resolved, _ = locked
            references.extend(
                blob_path(resolved.root, entry)
                for kit in resolved.characters.values()
                for entry in (kit.get("identity") or {}).get("refs", [])
            )
    distances = (
        [min(face_distance(panel, ref) for ref in references) for panel in panels]
        if panels and references
        else []
    )
    status = "pass" if not distances or max(distances) <= 0.45 else "warn"
    detail = (
        f"maximum character reference distance {max(distances):.3f} (limit 0.45)"
        if distances
        else "no character kit attached"
    )
    return status, detail
