from __future__ import annotations

from pathlib import Path

from PIL import Image

from kalainova import bar


def test_measure_still_image(tmp_path: Path) -> None:
    img_path = tmp_path / "sample.png"
    # Create image with gradients
    img = Image.new("L", (600, 600))
    pixels = img.load()
    for y in range(600):
        for x in range(600):
            pixels[x, y] = int((x + y) * 255 / 1200)
    img.save(img_path)

    report = bar.measure(img_path)
    assert report["total"] >= 5
    reading_ids = {r["id"] for r in report["readings"]}
    assert "picture.banding" in reading_ids
    assert "picture.detail" in reading_ids
    assert "picture.dynamic_range" in reading_ids
    assert "picture.clipping" in reading_ids
    assert "picture.dimensions" in reading_ids
