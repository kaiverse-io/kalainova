from __future__ import annotations

from kalainova import scorecard


def test_scorecard_empty() -> None:
    card = scorecard.aggregate_traces([])
    assert card["schema_version"] == "0.1"
    assert card["capabilities"] == {}
    table = scorecard.format_table(card)
    assert "No telemetry records found" in table


def test_scorecard_small_sample_threshold() -> None:
    traces = [
        {
            "schema_version": "0.1",
            "trace_id": f"tr-{i}",
            "job_id": "job-1",
            "call_id": f"call-{i}",
            "capability": "video",
            "provider": "fal",
            "model": "model-v1",
            "start_time": "2026-11-14T00:00:00Z",
            "duration_sec": 10.0,
            "cost": 0.10,
            "outcome": "success",
        }
        for i in range(3)
    ]
    card = scorecard.aggregate_traces(traces)
    vid = card["capabilities"]["video"]
    assert "not enough yet" in vid["status"]
    assert vid["models"]["model-v1"]["sample_count"] == 3
    assert "not enough yet" in vid["models"]["model-v1"]["status"]


def test_scorecard_qualified() -> None:
    traces = [
        {
            "schema_version": "0.1",
            "trace_id": f"tr-{i}",
            "job_id": "job-1",
            "call_id": f"call-{i}",
            "capability": "image",
            "provider": "fal",
            "model": "model-i1",
            "start_time": "2026-11-14T00:00:00Z",
            "duration_sec": 2.5,
            "cost": 0.02,
            "outcome": "success" if i != 0 else "error",
        }
        for i in range(5)
    ]
    card = scorecard.aggregate_traces(traces)
    img = card["capabilities"]["image"]
    assert img["status"] == "qualified"
    m = img["models"]["model-i1"]
    assert m["sample_count"] == 5
    assert m["success_rate"] == 0.8
    assert m["status"] == "qualified"

    table = scorecard.format_table(card, capability="image")
    assert "model-i1" in table
    assert "qualified" in table
