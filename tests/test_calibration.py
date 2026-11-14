from __future__ import annotations

import json
from pathlib import Path

from kalainova import calibration


def test_calibration_metrics() -> None:
    jobs = [
        {"human_accepted": True, "reading_passed": True, "judge_passed": True},
        {"human_accepted": True, "reading_passed": True, "judge_passed": False},
        {"human_accepted": False, "reading_passed": False, "judge_passed": False},
        {"human_accepted": False, "reading_passed": True, "judge_passed": False},
        {"human_accepted": True, "reading_passed": True, "judge_passed": True},
    ]
    rep = calibration.report_calibration(jobs)
    assert rep["total_jobs"] == 5
    assert rep["human_accepted"] == 3
    assert rep["human_rejected"] == 2
    assert rep["reading_agreement_rate"] == 0.8  # 4 out of 5 agreed
    assert rep["judge_agreement_rate"] == 0.8  # 4 out of 5 agreed
    assert rep["status"] == "calibrated"


def test_calibration_directory_scan(tmp_path: Path) -> None:
    # Set up mock job directory
    j1 = tmp_path / "job-1"
    j1.mkdir()
    (j1 / "job.json").write_text(json.dumps({"job_id": "job-1"}))
    (j1 / "verdict.json").write_text(json.dumps({"verdict": "accept"}))
    (j1 / "qa.json").write_text(json.dumps({"passed": True}))
    (j1 / "findings.json").write_text(json.dumps({"problems": []}))

    res = calibration.calibrate_directory(tmp_path)
    assert res["total_jobs"] == 1
    assert res["human_accepted"] == 1
    assert res["reading_agreement_rate"] == 1.0
    assert res["status"] == "preliminary (n < 5)"
