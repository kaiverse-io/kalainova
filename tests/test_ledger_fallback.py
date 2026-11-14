from __future__ import annotations

import argparse
import json
from pathlib import Path

from kalainova import provenance
from kalainova.jobfs import Job
from kalainova.production_cli import _ledger


def test_ledger_report_without_asset_manifest(tmp_path: Path) -> None:
    folder = tmp_path / "jobs" / "j1"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "j1",
                "strategy": "generated",
                "media": ["audio"],
                "rights": "owned",
                "distribution_identity": "t",
                "status": "draft",
                "cost_cap": 10.0,
            }
        )
    )
    job = Job(folder)
    # Record spend in ledger
    res = job.reserve("elevenlabs", "voice", 0.05)
    job.charge("elevenlabs", "voice", 0.04, reservation=res)

    rep = provenance.report(job)
    assert rep["job_id"] == "j1"
    assert rep["ledger"]["total_estimated"] == 0.04
    assert rep["ledger"]["by_provider"]["elevenlabs"] == 0.04
    assert rep["assets"] == []

    # Test CLI handler does not raise
    args = argparse.Namespace(job=str(job.folder), invoice=None)
    rc = _ledger(args)
    assert rc == 0
