"""A private config is laid over the repo's, so it holds only what it changes."""

from __future__ import annotations

import pytest

from kalainova import config


def test_tables_merge_key_by_key_and_other_values_replace():
    base = {"prices": {"fal": {"video": 0.28, "image": 0.15}}, "preference": {"song": ["a", "b"]}}
    over = {"prices": {"fal": {"video": 0.2}}, "preference": {"song": []}}
    assert config.overlay(base, over) == {
        "prices": {"fal": {"video": 0.2, "image": 0.15}},
        "preference": {"song": []},
    }


@pytest.fixture
def private(monkeypatch, tmp_path):
    """A private config file, active for one test only."""
    path = tmp_path / "studio.yaml"
    monkeypatch.setenv("KALAINOVA_CONFIG", str(path))
    config.studio.cache_clear()
    yield path
    config.studio.cache_clear()


def test_a_private_file_keeps_every_section_it_leaves_out(private):
    private.write_text("identity: {same_face_min: 0.57}\n")
    merged = config.studio()
    assert merged["identity"]["same_face_min"] == 0.57
    assert "video_models" in merged
    assert "takes" in merged
    assert merged["prices"]["fal"] == config._repo()["prices"]["fal"]


def test_a_missing_private_file_leaves_the_repo_config(private):
    assert config.studio() == config._repo()
