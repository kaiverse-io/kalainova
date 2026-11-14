from __future__ import annotations

import datetime as dt
import json

import pytest
import yaml

from kalainova.jobfs import ContractError
from kalainova.templates import fill_template

TEMPLATE = {
    "strategy": "owned-derivative",
    "rights": "owned",
    "distribution_identity": "{league}-recap",
    "brief": {
        "title": "{winner} beats {loser}",
        "subject": "a recap of {league} night",
    },
    "claims": [
        {"claim": "{winner} won {score}", "source": "{data_source}"},
    ],
    "cards": [
        {"kind": "stat", "value": "{score}", "label": "{league} final"},
    ],
}

DATA = {
    "winner": "the home team",
    "loser": "the away team",
    "score": "3-1",
    "league": "spring",
    "data_source": "https://example.com/box-score",
}


def _write(path, name, payload, *, as_yaml=False):
    p = path / name
    p.write_text(yaml.safe_dump(payload) if as_yaml else json.dumps(payload))
    return p


def _setup(tmp_path, monkeypatch, *, data_extra=None, template_extra=None):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    template = {**TEMPLATE, **(template_extra or {})}
    data = {**DATA, **(data_extra or {})}
    template_path = _write(tmp_path, "template.yaml", template, as_yaml=True)
    data_path = _write(tmp_path, "data.json", data)
    return template_path, data_path


def test_fill_template_writes_job_and_hydrated_script_packet(tmp_path, monkeypatch):
    template_path, data_path = _setup(tmp_path, monkeypatch)

    job = fill_template(template_path, data_path, "recap-1")

    assert job.folder == tmp_path / "jobs" / "recap-1"
    assert job.job["brief"]["title"] == "the home team beats the away team"
    assert job.job["distribution_identity"] == "spring-recap"
    assert job.job["strategy"] == "owned-derivative"
    assert job.job["rights"] == "owned"

    packet = job.read("script_packet")
    assert packet["claims"] == [
        {
            "id": "c1",
            "statement": "the home team won 3-1",
            "source": "https://example.com/box-score",
        }
    ]
    assert packet["beats"]

    cards = json.loads((job.folder / "cards.json").read_text())
    assert cards == [{"kind": "stat", "value": "3-1", "label": "spring final"}]


def test_stale_data_file_raises_contract_error(tmp_path, monkeypatch):
    as_of = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=10)).isoformat()
    template_path, data_path = _setup(tmp_path, monkeypatch, data_extra={"as_of": as_of})

    with pytest.raises(ContractError, match="stale"):
        fill_template(template_path, data_path, "recap-2", max_age_hours=6)


def test_fresh_data_file_passes_within_max_age_hours(tmp_path, monkeypatch):
    as_of = (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat()
    template_path, data_path = _setup(tmp_path, monkeypatch, data_extra={"as_of": as_of})

    job = fill_template(template_path, data_path, "recap-3", max_age_hours=6)

    assert job.job["job_id"] == "recap-3"


def test_missing_placeholder_in_data_raises_contract_error(tmp_path, monkeypatch):
    template_path, data_path = _setup(tmp_path, monkeypatch)
    data = json.loads(data_path.read_text())
    del data["data_source"]
    data_path.write_text(json.dumps(data))

    with pytest.raises(ContractError, match="data_source"):
        fill_template(template_path, data_path, "recap-4")
