"""Approval covers the file a platform receives, not only the one a person watched."""

from __future__ import annotations

import json

import pytest
from fakes import make_job

from kalainova import bar, publish, render
from kalainova.jobfs import ContractError


def _approvable(tmp_path, monkeypatch, *, with_master=True):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path)
    final = job.work / "final.mp4"
    final.write_bytes(b"the proxy a person watched")
    master = job.work / "final.master.mov"
    hashes = {"video": publish.sha256_file(final)}
    if with_master:
        master.write_bytes(b"the master a platform receives")
        hashes["master"] = publish.sha256_file(master)
    job.write(
        "asset_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "assets": [
                {"id": "v", "kind": "audio", "path": "x.wav", "provider": "paid", "model": "m"}
            ],
        },
    )
    render.stamp(job, final)
    job.write(
        "qa",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "passed": True,
            "checks": [],
            "artifacts_sha256": hashes,
        },
    )
    (job.folder / "script_packet.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": job.id,
                "beats": [{"id": "b", "role": "hook", "text": "x"}],
            }
        )
    )
    return job, final, master


def test_an_approval_records_the_master_it_covers(tmp_path, monkeypatch):
    job, _, master = _approvable(tmp_path, monkeypatch)
    record = publish.approve(job, "human", platforms=["youtube"])
    assert record["master_sha256"] == publish.sha256_file(master)


def test_a_master_changed_before_approval_is_refused(tmp_path, monkeypatch):
    job, _, master = _approvable(tmp_path, monkeypatch)
    master.write_bytes(b"something else")
    with pytest.raises(ContractError, match="not the master QA checked"):
        publish.approve(job, "human", platforms=["youtube"])


def test_a_master_changed_after_approval_cannot_be_published(tmp_path, monkeypatch):
    job, _, master = _approvable(tmp_path, monkeypatch)
    publish.approve(job, "human", platforms=["youtube"])
    master.write_bytes(b"something else")
    with pytest.raises(ContractError, match="QA checked|changed after approval"):
        publish.publish(job, "youtube", dry_run=True)


def test_a_master_qa_never_saw_is_refused(tmp_path, monkeypatch):
    job, _, master = _approvable(tmp_path, monkeypatch, with_master=False)
    master.write_bytes(b"appeared later")
    with pytest.raises(ContractError, match="never checked"):
        publish.approve(job, "human", platforms=["youtube"])


def test_a_piece_with_no_master_is_approved_as_before(tmp_path, monkeypatch):
    job, _, _ = _approvable(tmp_path, monkeypatch, with_master=False)
    assert "master_sha256" not in publish.approve(job, "human", platforms=["youtube"])


def test_a_broken_motion_promise_cannot_be_approved_unless_a_person_allowed_it(
    tmp_path, monkeypatch
):
    job, final, _ = _approvable(tmp_path, monkeypatch)
    manifest = job.read("asset_manifest")
    manifest["promise_breaks"] = [{"beat_id": "b", "reason": "the model was down"}]
    job.write("asset_manifest", manifest)
    render.stamp(job, final)
    with pytest.raises(ContractError, match="asked to move"):
        publish.approve(job, "human", platforms=["youtube"])
    data = job.job
    data["brief"]["allow_stills"] = True
    job.write("job", data)
    assert publish.approve(job, "human", platforms=["youtube"])["reviewer"] == "human"


def _reading(rid, ok, *, blocks):
    return {"id": rid, "value": 1, "limit": "x", "ok": ok, "blocks": blocks}


def test_a_report_keeps_conformance_apart_from_craft():
    report = bar._summary(
        [
            _reading("master.codec", True, blocks=True),
            _reading("master.size", True, blocks=True),
            _reading("picture.detail", False, blocks=False),
        ]
    )
    assert report["conformance"] == {"met": 2, "total": 2}
    assert report["craft"] == {"met": 0, "total": 1}
    line = bar.summary_line(report)
    assert "conformance 2/2" in line and "craft 0/1" in line
    assert "not that the piece is good" in line


def test_a_long_piece_is_read_across_its_whole_length_and_not_only_its_middle():
    windows = bar._windows(3600.0, 24.0)
    assert len(windows) == bar.LONG_WINDOWS
    assert windows[0][0] == 0.0 and windows[-1][0] + windows[-1][1] == pytest.approx(3600.0)
    assert bar._windows(5.0, 24.0) == [(0.0, 5.0)], "a short piece is read whole"


def test_a_long_piece_samples_shots_from_end_to_end():
    picked = bar._spread(list(range(1000)), 10)
    assert len(picked) == 10 and picked[0] == 0 and picked[-1] >= 900
    assert bar._spread([1.0, 2.0], 10) == [1.0, 2.0]
