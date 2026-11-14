"""Tests for trace telemetry recording and schema validation."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import jsonschema
import pytest

from kalainova import trace
from kalainova.jobfs import Job


@pytest.fixture
def fake_job(tmp_path: Path) -> Job:
    folder = tmp_path / "jobs" / "job_test"
    folder.mkdir(parents=True)
    job = MagicMock(spec=Job)
    job.id = "job_test"
    job.folder = folder
    return job


def test_record_writes_row_and_conforms_to_schema(fake_job: Job):
    schema_path = Path("schemas/trace.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    row = trace.record(
        fake_job,
        capability="image",
        provider="fal",
        model="flux-pro",
        started_at="2026-11-14T04:00:00Z",
        elapsed_sec=1.25,
        outcome="ok",
        estimated_cost=0.05,
        settled_cost=0.045,
    )
    assert row is not None
    assert row["outcome"] == "ok"
    assert row["elapsed_sec"] == 1.25

    jsonschema.validate(instance=row, schema=schema)

    rows = trace.load(fake_job)
    assert len(rows) == 1
    assert rows[0]["provider"] == "fal"


def test_record_handles_unknown_outcome(fake_job: Job):
    row = trace.record(
        fake_job,
        capability="voice",
        provider="elevenlabs",
        model="flash",
        started_at="2026-11-14T04:00:00Z",
        elapsed_sec=0.5,
        outcome="something_odd",
    )
    assert row is not None
    assert row["outcome"] == "error"


def test_record_and_load_graceful_on_io_failure(fake_job: Job, monkeypatch):
    # If folder is read-only or open fails, never raises
    monkeypatch.setattr("builtins.open", MagicMock(side_effect=PermissionError("read-only")))
    assert (
        trace.record(
            fake_job,
            capability="voice",
            provider="p",
            model="m",
            started_at="2026",
            elapsed_sec=0.1,
            outcome="ok",
        )
        is None
    )


def test_load_nonexistent_or_corrupt(fake_job: Job):
    assert trace.load(fake_job) == []
    trace_path = fake_job.folder / "trace.jsonl"
    trace_path.write_text("invalid json line\n", encoding="utf-8")
    assert trace.load(fake_job) == []
