"""What must be true before money leaves (ADR 0022): a stopped studio spends nothing."""

from __future__ import annotations

import json

import pytest
from test_router import PRICES, Flaky, image, job_with, providers  # noqa: F401 - the autouse fixture

from kalainova import gates
from kalainova.__main__ import main
from kalainova.jobfs import ContractError


def test_a_stopped_studio_makes_no_paid_call_and_says_who_stopped_it(tmp_path):
    job = job_with(tmp_path, ["flaky"])
    gates.stop(tmp_path, by="the operator", why="checking a bill")
    with pytest.raises(ContractError, match="stopped in this studio by the operator: checking"):
        image(job)
    assert Flaky.calls == 0 and job.spent() == 0
    gates.resume(tmp_path, by="the operator")
    image(job)
    assert Flaky.calls == 1
    log = [json.loads(line)["event"] for line in (tmp_path / gates.LOG).read_text().splitlines()]
    assert log == ["stop", "resume"]


def test_a_free_provider_still_runs_while_stopped(tmp_path):
    job = job_with(tmp_path, ["placeholder"])
    gates.stop(tmp_path, by="the operator")
    assert image(job)[0].name == "placeholder"


def test_stop_and_resume_name_who(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    with pytest.raises(SystemExit):
        main(["stop"])  # --by is required
    assert main(["stop", "--by", "the operator"]) == 0 and (tmp_path / gates.STOP).exists()
    assert main(["resume", "--by", "the operator"]) == 0 and not (tmp_path / gates.STOP).exists()
