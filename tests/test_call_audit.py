"""Every model call can be audited: one attempt id joins its records, and its cost is checked."""

from __future__ import annotations

import json

import pytest
from test_router import PRICES, Flaky, image, job_with, providers  # noqa: F401 - the autouse fixture

from kalainova import trace
from kalainova.providers import base, router


class Billed(Flaky):
    """A vendor that hands back its own request id, as fal does on submit."""

    name = "billed"
    calls = 0
    fails = None

    def image(self, prompt, dst, *, width=64, height=64, **kw):
        self.request_id = f"vendor-{type(self).calls}"
        if type(self).fails:
            raise type(self).fails
        return Flaky.image(self, prompt, dst, width=width, height=height, **kw)


def test_one_attempt_id_joins_the_trace_the_ledger_and_the_record(tmp_path, monkeypatch):
    # An auditor must get from a cost to the call, its model, its vendor request and its output
    monkeypatch.setitem(base._REGISTRY, "billed", Billed)
    monkeypatch.setitem(PRICES, "billed", {"image": {"per_image": 1.0}})
    job = job_with(tmp_path, ["billed"])
    with trace.labelled(stage="assets", shot="s01"):
        image(job, model="asked-model")
    (row,) = trace.load(job)
    (entry,) = json.loads(job.ledger_path.read_text())
    record = json.loads((job.folder / router.GENERATIONS).read_text())
    assert row["attempt"] and row["attempt"] == entry["attempt"] == record["attempt"]
    assert row["model"] == entry["model"] == "flaky-1"  # what the adapter says it used
    assert row["request_id"] == entry["request_id"] == record["request_id"] == "vendor-0"
    assert (row["stage"], row["shot"]) == (entry["stage"], entry["shot"]) == ("assets", "s01")
    assert row["run_id"] == entry["run_id"] == trace.RUN_ID
    assert row["engine"] and entry["at"]


def test_a_failed_call_is_traced_with_the_model_asked_and_what_the_vendor_said(tmp_path):
    job = job_with(tmp_path, ["flaky"])
    Flaky.fails = ConnectionError("422: elements need a second angle")
    with pytest.raises(router.ProviderError):
        image(job, model="asked-model")
    (row,) = trace.load(job)
    assert row["model"] == "asked-model"  # not the provider's default model
    assert row["outcome"] == "error" and "second angle" in row["error_detail"]
    assert job.spent() == 0


def test_a_charge_with_no_file_still_writes_a_trace_row(tmp_path, monkeypatch):
    monkeypatch.setattr(Flaky, "image", lambda self, p, dst, **kw: base.Result(cost=1.0, model="m"))
    job = job_with(tmp_path, ["flaky"])
    with pytest.raises(router.ProviderError, match="no file"):
        image(job)
    (row,) = trace.load(job)
    assert row["settled_cost"] == 1.0 and row["error_class"] == "NoFile"
    from kalainova import provenance

    assert provenance.report(job)["ledger"]["charged_without_a_trace"] == []


class Charged(Flaky):
    """A vendor that says what it billed, which differs from the price table."""

    name = "charged"
    calls = 0
    fails = None

    def image(self, prompt, dst, *, width=64, height=64, **kw):
        self.billed_units, self.charged = 1, 1.25
        return Flaky.image(self, prompt, dst, width=width, height=height, **kw)


@pytest.mark.parametrize(("table", "settled"), [(1.0, 1.25), (2.0, 2.0)])
def test_the_ledger_settles_at_the_higher_of_the_table_and_the_vendor(
    tmp_path, monkeypatch, table, settled
):
    # A vendor's unit price can be a base rate; until its bill confirms, the higher figure holds
    monkeypatch.setitem(base._REGISTRY, "charged", Charged)
    monkeypatch.setitem(PRICES, "charged", {"image": {"per_image": table}})
    monkeypatch.setattr(Charged, "cost", table)  # what the adapter priced from its table
    job = job_with(tmp_path, ["charged"])
    image(job)
    (entry,) = json.loads(job.ledger_path.read_text())
    (row,) = trace.load(job)
    assert entry["cost"] == row["settled_cost"] == settled
    assert (entry["table_cost"], entry["vendor_cost"], entry["billed_units"]) == (table, 1.25, 1)
    assert entry["price_source"].startswith("higher of")


def test_a_call_with_no_vendor_figure_says_it_was_priced_by_the_table(tmp_path):
    job = job_with(tmp_path, ["flaky"])
    image(job)
    (entry,) = json.loads(job.ledger_path.read_text())
    assert entry["price_source"] == "price table" and entry["cost"] == 1.0
