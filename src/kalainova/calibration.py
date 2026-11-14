"""Calibration and agreement report: deterministic readings, model judges, and human verdicts.

Analyzes how often the engine's automated checks agree with the human operator's verdicts.
Readings and judges that do not correlate with human acceptance are reported as uncalibrated.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Any


def evaluate_job(folder: Path) -> dict[str, Any] | None:
    """Extract human verdict and automated assessments from a job folder."""
    verdict_file = folder / "verdict.json"
    qa_file = folder / "qa.json"
    findings_file = folder / "findings.json"

    if not verdict_file.is_file():
        # Check approval.json as an accept verdict
        appr_file = folder / "approval.json"
        if appr_file.is_file():
            verdict = "accept"
        else:
            return None
    else:
        try:
            v_data = json.loads(verdict_file.read_text())
            verdict = v_data.get("verdict", "reject")
        except Exception:
            return None

    human_accepted = verdict == "accept"

    # Automated reading result
    reading_passed: bool | None = None
    if qa_file.is_file():
        with contextlib.suppress(Exception):
            qa_data = json.loads(qa_file.read_text())
            reading_passed = bool(qa_data.get("passed", False))

    # Model judge result from findings.json
    judge_passed: bool | None = None
    if findings_file.is_file():
        with contextlib.suppress(Exception):
            f_data = json.loads(findings_file.read_text())
            problems = f_data.get("problems", [])
            judge_passed = len(problems) == 0

    return {
        "job_id": folder.name,
        "verdict": verdict,
        "human_accepted": human_accepted,
        "reading_passed": reading_passed,
        "judge_passed": judge_passed,
    }


def report_calibration(jobs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute calibration metrics from evaluated job records."""
    total = len(jobs)
    if total == 0:
        return {
            "total_jobs": 0,
            "human_accepted": 0,
            "reading_agreement_rate": None,
            "judge_agreement_rate": None,
            "status": "not enough data yet",
        }

    accepted = sum(1 for j in jobs if j["human_accepted"])

    # Reading agreement: (both true or both false)
    r_pairs = [
        (j["human_accepted"], j["reading_passed"]) for j in jobs if j["reading_passed"] is not None
    ]
    reading_agree = sum(1 for h, r in r_pairs if h == r) / len(r_pairs) if r_pairs else None

    # Judge agreement:
    j_pairs = [
        (j["human_accepted"], j["judge_passed"]) for j in jobs if j["judge_passed"] is not None
    ]
    judge_agree = sum(1 for h, j in j_pairs if h == j) / len(j_pairs) if j_pairs else None

    return {
        "total_jobs": total,
        "human_accepted": accepted,
        "human_rejected": total - accepted,
        "reading_evaluated_count": len(r_pairs),
        "reading_agreement_rate": round(reading_agree, 3) if reading_agree is not None else None,
        "judge_evaluated_count": len(j_pairs),
        "judge_agreement_rate": round(judge_agree, 3) if judge_agree is not None else None,
        "status": "calibrated" if total >= 5 else "preliminary (n < 5)",
    }


def calibrate_directory(root: Path) -> dict[str, Any]:
    """Scan all job subfolders under root and produce calibration report."""
    evaluated: list[dict[str, Any]] = []
    if root.is_dir():
        for sub in sorted(root.iterdir()):
            if sub.is_dir() and (sub / "job.json").is_file():
                res = evaluate_job(sub)
                if res is not None:
                    evaluated.append(res)
    return report_calibration(evaluated)
