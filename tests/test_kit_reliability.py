from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from kalainova import kits
from kalainova.jobfs import ContractError


def test_kit_merge_rejects_real_person(tmp_path: Path) -> None:
    kits.new(tmp_path, "k1")
    with pytest.raises(ContractError, match="cannot represent a real person"):
        kits.merge(tmp_path, "k1", {"origin": {"real_person": True}})


def test_kit_merge_rejects_underage(tmp_path: Path) -> None:
    kits.new(tmp_path, "k1")
    with pytest.raises(ContractError, match="must be an adult"):
        kits.merge(tmp_path, "k1", {"persona": {"age": 16}})


def test_kit_replace_and_remove_reference(tmp_path: Path) -> None:
    kits.new(tmp_path, "k1")
    img1 = tmp_path / "ref1.png"
    img2 = tmp_path / "ref2.png"
    Image.new("RGB", (100, 100), color="red").save(img1)
    Image.new("RGB", (100, 100), color="blue").save(img2)

    # Add ref with label "front"
    kits.add_file(tmp_path, "k1", "identity", img1, label="front")
    draft = kits.read_draft(tmp_path, "k1")
    assert len(draft["identity"]["refs"]) == 1
    sha1 = draft["identity"]["refs"][0]["sha256"]

    # Re-adding with same label replaces entry
    kits.add_file(tmp_path, "k1", "identity", img2, label="front")
    draft = kits.read_draft(tmp_path, "k1")
    assert len(draft["identity"]["refs"]) == 1
    assert draft["identity"]["refs"][0]["sha256"] != sha1

    # Remove reference
    kits.remove_reference(tmp_path, "k1", "identity", "front")
    draft = kits.read_draft(tmp_path, "k1")
    assert len(draft["identity"]["refs"]) == 0
