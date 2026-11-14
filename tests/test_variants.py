from __future__ import annotations

import pytest
from fakes import make_job

from kalainova.jobfs import ContractError
from kalainova.variants import open_variant


def _parent(tmp_path, monkeypatch, *, with_edit=True, with_assets=True):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    parent = make_job(tmp_path)
    if with_assets:
        parent.write(
            "asset_manifest",
            {
                "schema_version": "0.1",
                "job_id": parent.id,
                "assets": [
                    {"id": "shot-a", "kind": "video", "path": "shot-a.mp4"},
                    {"id": "shot-b", "kind": "video", "path": "shot-b.mp4"},
                ],
            },
        )
        for name in ("shot-a.mp4", "shot-b.mp4"):
            path = parent.work / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(name.encode())
    if with_edit:
        parent.write(
            "edit_manifest",
            {
                "schema_version": "0.1",
                "job_id": parent.id,
                "runtime": "ffmpeg",
                "duration_sec": 4.0,
                "cuts": [
                    {"id": "a", "source": "shot-a", "in_sec": 0, "out_sec": 2},
                    {"id": "b", "source": "shot-b", "in_sec": 2, "out_sec": 4},
                ],
                "overlays": [
                    {"kind": "hook_card", "start_sec": 0, "end_sec": 1.5, "text": "Old hook"}
                ],
                "brief": {"title": "Original title"},
            },
        )
    parent.write(
        "script_packet",
        {
            "schema_version": "0.1",
            "job_id": parent.id,
            "beats": [{"id": "b1", "role": "body", "text": "Body"}],
        },
    )
    return parent


def test_open_variant_requires_edit_and_asset_manifests(tmp_path, monkeypatch):
    parent = _parent(tmp_path / "no-edit", monkeypatch, with_edit=False)
    with pytest.raises(ContractError, match="edit_manifest"):
        open_variant(parent, "missing-edit")

    parent = _parent(tmp_path / "no-assets", monkeypatch, with_assets=False)
    with pytest.raises(ContractError, match="asset_manifest"):
        open_variant(parent, "missing-assets")


def test_open_variant_records_parent_in_child_brief(tmp_path, monkeypatch):
    parent = _parent(tmp_path, monkeypatch)
    child = open_variant(parent, "opening-child")
    assert child.job["brief"]["variant_of"] == parent.id
    assert child.job["brief"]["variant_type"] == "opening"


def test_open_variant_replaces_hook_card_text_and_title(tmp_path, monkeypatch):
    parent = _parent(tmp_path, monkeypatch)
    child = open_variant(parent, "text-child", opening_text="New hook", title="New title")
    em = child.read("edit_manifest")
    assert em["overlays"][0]["text"] == "New hook"
    assert em["brief"]["title"] == "New title"


def test_open_variant_inserts_or_replaces_the_hook_card(tmp_path, monkeypatch):
    parent = _parent(tmp_path, monkeypatch)
    card = {"kind": "hook_card", "start_sec": 0, "end_sec": 1, "text": "Card hook"}
    child = open_variant(parent, "card-child", opening_card=card)
    assert child.read("edit_manifest")["overlays"][0] == card


def test_open_variant_swaps_only_the_first_cut_source(tmp_path, monkeypatch):
    parent = _parent(tmp_path, monkeypatch)
    child = open_variant(parent, "shot-child", opening_shot="replacement")
    assert [cut["source"] for cut in child.read("edit_manifest")["cuts"]] == [
        "replacement",
        "shot-b",
    ]


def test_open_variant_shares_parent_assets_and_script_packet(tmp_path, monkeypatch):
    parent = _parent(tmp_path, monkeypatch)
    child = open_variant(parent, "shared-child")
    assert child.read("asset_manifest")["assets"] == parent.read("asset_manifest")["assets"]
    assert (child.work / "shot-a.mp4").stat().st_ino == (parent.work / "shot-a.mp4").stat().st_ino
    assert child.read("script_packet")["job_id"] == child.id
