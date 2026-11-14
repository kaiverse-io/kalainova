from pathlib import Path

import numpy as np
from PIL import Image

from kalainova.bar import identity_readings
from kalainova.bar.identity import face_distance, face_reading


def _save_pattern(path: Path, *, checkerboard: bool) -> None:
    if checkerboard:
        image = (np.indices((128, 128)).sum(axis=0) // 8 % 2 * 255).astype(np.uint8)
    else:
        image = np.zeros((128, 128), dtype=np.uint8)
    Image.fromarray(image).save(path)


def test_identical_images_have_zero_distance(tmp_path: Path) -> None:
    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    _save_pattern(first, checkerboard=True)
    _save_pattern(second, checkerboard=True)

    assert face_distance(first, second) == 0.0


def test_different_images_have_positive_distance(tmp_path: Path) -> None:
    black = tmp_path / "black.png"
    checkerboard = tmp_path / "checkerboard.png"
    _save_pattern(black, checkerboard=False)
    _save_pattern(checkerboard, checkerboard=True)

    assert face_distance(black, checkerboard) > 0.0


def test_identity_reading_obeys_limit(tmp_path: Path) -> None:
    black = tmp_path / "black.png"
    checkerboard = tmp_path / "checkerboard.png"
    _save_pattern(black, checkerboard=False)
    _save_pattern(checkerboard, checkerboard=True)

    passing = face_reading(black, [black], max_distance=0.40)
    failing = face_reading(black, [checkerboard], max_distance=0.40)
    configured = identity_readings(black, [checkerboard])

    assert passing is not None and passing.ok
    assert failing is not None and not failing.ok
    assert failing.limit == "<= 0.40"
    assert len(configured) == 1 and not configured[0].ok
