"""Contract files are replaced whole: a crash mid-write leaves the old file, never part of one."""

from __future__ import annotations

import json
import os

import pytest
from fakes import make_job

from kalainova import jobfs


def test_a_write_that_fails_part_way_leaves_the_last_good_file(tmp_path, monkeypatch):
    job = make_job(tmp_path)
    before = job.path("job").read_text()
    data = json.loads(before)
    data["status"] = "rendered"

    def crash(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(jobfs.os, "replace", crash)
    with pytest.raises(OSError, match="disk full"):
        job.write("job", data)

    assert job.path("job").read_text() == before
    assert not [p for p in job.folder.iterdir() if p.name.endswith(".tmp")]


def test_a_write_replaces_the_file_whole(tmp_path):
    job = make_job(tmp_path)
    data = job.job
    data["status"] = "rendered"
    job.write("job", data)
    assert job.job["status"] == "rendered"
    assert not [p for p in job.folder.iterdir() if p.name.endswith(".tmp")]


def test_the_stamp_and_the_ledger_are_written_the_same_way(tmp_path, monkeypatch):
    job = make_job(tmp_path)
    seen = []
    real = os.replace
    monkeypatch.setattr(jobfs.os, "replace", lambda a, b: (seen.append(b), real(a, b)))
    job.write_stamp({"sha256": "x"})
    job.charge("fake", "image", 0.0)
    assert {p.name for p in seen} >= {jobfs.RENDER_STAMP, job.ledger_path.name}


def test_tests_never_render_into_the_repos_out_folder():
    assert os.environ["KALAINOVA_OUT"] != str(jobfs.REPO / "out")
    assert "KALAINOVA_HOME" not in os.environ
