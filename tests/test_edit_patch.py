from __future__ import annotations

import json

import pytest
from fakes import make_job

from kalainova.editor.patch import patch_cut
from kalainova.jobfs import ContractError


def _job_with_edit(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path)
    job.write(
        "asset_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "assets": [
                {"id": "shot-a", "kind": "video", "path": "shot-a.mp4"},
                {"id": "shot-b", "kind": "video", "path": "shot-b.mp4"},
            ],
        },
    )
    job.write(
        "edit_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "runtime": "ffmpeg",
            "duration_sec": 4.0,
            "cuts": [
                {"id": "a", "source": "shot-a", "in_sec": 0.0, "out_sec": 2.0},
                {"id": "b", "source": "shot-b", "in_sec": 2.0, "out_sec": 4.0},
            ],
        },
    )
    return job


def test_patch_cut_updates_source_and_in_sec_leaving_others(tmp_path, monkeypatch):
    job = _job_with_edit(tmp_path, monkeypatch)
    before = [dict(c) for c in job.read("edit_manifest")["cuts"]]

    result = patch_cut(job, 0, source="shot-b", in_sec=1.5)

    em = job.read("edit_manifest")
    assert em["cuts"][0]["source"] == "shot-b"
    assert em["cuts"][0]["in_sec"] == 1.5
    assert em["cuts"][1] == before[1]
    assert result["cut"]["source"] == "shot-b"
    assert result["cut_index"] == 0
    assert result["job_id"] == job.id
    assert result["approval_voided"] is False


def test_patch_cut_invalid_index_raises(tmp_path, monkeypatch):
    job = _job_with_edit(tmp_path, monkeypatch)
    with pytest.raises(ContractError, match="out of bounds"):
        patch_cut(job, 99, in_sec=0.5)
    with pytest.raises(ContractError, match="out of bounds"):
        patch_cut(job, -1, in_sec=0.5)


def test_patch_cut_unknown_source_raises(tmp_path, monkeypatch):
    job = _job_with_edit(tmp_path, monkeypatch)
    with pytest.raises(ContractError, match="not in asset_manifest"):
        patch_cut(job, 0, source="missing-shot")


def test_patch_cut_voids_approval(tmp_path, monkeypatch):
    job = _job_with_edit(tmp_path, monkeypatch)
    (job.folder / "approval.json").write_text(
        json.dumps({"schema_version": "0.1", "job_id": job.id, "approved_by": "human"})
    )

    result = patch_cut(job, 1, title="Payoff")

    assert result["approval_voided"] is True
    assert not (job.folder / "approval.json").exists()
    assert job.read("edit_manifest")["cuts"][1]["title"] == "Payoff"


def test_patch_cut_logs_note_to_direction(tmp_path, monkeypatch):
    job = _job_with_edit(tmp_path, monkeypatch)
    (job.folder / "direction.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": job.id,
                "notes": [{"at": "2026-01-01T00:00:00+00:00", "text": "start"}],
                "settings": {},
            }
        )
        + "\n"
    )

    patch_cut(job, 0, in_sec=0.25, note="nudge the open")

    direction = json.loads((job.folder / "direction.json").read_text())
    assert direction["notes"][0]["text"] == "start"
    assert direction["notes"][-1]["text"] == "patch cut 0: nudge the open"
    assert "at" in direction["notes"][-1]
