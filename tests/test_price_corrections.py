"""The engine checks its own prices: a stale table cannot under-reserve, and a bill teaches it."""

from __future__ import annotations

import json
import time

import pytest
from fakes import make_job

from kalainova.providers import prices

MODEL = "vendor/video-model"


class Vendor:
    name = "vendor"
    listed = None

    def price_key(self, capability, request):
        return "reference_to_video"

    def list_price(self, model):
        return type(self).listed


@pytest.fixture
def table(monkeypatch):
    rows = {MODEL: {"per_sec": 0.112}}

    def price_for(provider, key, model=None):
        return dict(rows.get(model) or {})

    monkeypatch.setattr(prices.config, "price_for", price_for)
    Vendor.listed = None
    return rows


def test_the_table_stands_when_nothing_says_otherwise(tmp_path, table):
    job = make_job(tmp_path)
    assert prices.correction(job, Vendor(), "video", {"model": MODEL}) == (1.0, "")


def test_a_higher_list_price_raises_the_estimate(tmp_path, table):
    # 16 Nov 2026: the table said $0.112/s, the vendor listed $0.14 for this account
    Vendor.listed = {"unit_price": 0.14, "unit": "seconds"}
    factor, why = prices.correction(make_job(tmp_path), Vendor(), "video", {"model": MODEL})
    assert factor == pytest.approx(1.25) and "list price" in why


def test_a_reviewed_row_or_another_unit_is_not_raised_by_the_list(tmp_path, table):
    job = make_job(tmp_path)
    Vendor.listed = {"unit_price": 0.045, "unit": "seconds"}  # a base rate below 1080p's
    assert prices.correction(job, Vendor(), "video", {"model": MODEL})[0] == 1.0  # never lowers
    Vendor.listed = {"unit_price": 9.0, "unit": "1000 tokens"}
    (tmp_path / prices.LISTED).unlink()
    assert prices.correction(job, Vendor(), "video", {"model": MODEL})[0] == 1.0
    table[MODEL]["checked"] = "1080p rate from the model page"
    Vendor.listed = {"unit_price": 0.5, "unit": "seconds"}
    (tmp_path / prices.LISTED).unlink()
    assert prices.correction(job, Vendor(), "video", {"model": MODEL})[0] == 1.0


def test_a_bill_above_the_table_raises_later_estimates_and_is_reported(tmp_path, table, capsys):
    job = make_job(tmp_path)
    prices.learn(job, "vendor", MODEL, {"table_cost": 0.56, "vendor_cost": 0.70, "billed_units": 5})
    assert "billed $0.7000" in capsys.readouterr().err
    factor, why = prices.correction(job, Vendor(), "video", {"model": MODEL})
    assert factor == pytest.approx(1.25) and "bill" in why
    row = json.loads((tmp_path / prices.LEARNED).read_text())
    assert row["ratio"] == pytest.approx(1.25) and row["billed_units"] == 5


def test_the_list_price_is_read_at_most_once_a_day(tmp_path, table):
    job = make_job(tmp_path)
    reads = []

    def fetch(model):
        reads.append(model)
        return {"unit_price": 0.14, "unit": "seconds"}

    assert prices.listed(job, "vendor", MODEL, fetch)["unit_price"] == 0.14
    assert prices.listed(job, "vendor", MODEL, fetch)["unit_price"] == 0.14
    assert reads == [MODEL]
    cache = json.loads((tmp_path / prices.LISTED).read_text())
    cache[f"vendor:{MODEL}"]["read_at"] = time.time() - prices.LIST_MAX_AGE - 1
    (tmp_path / prices.LISTED).write_text(json.dumps(cache))
    prices.listed(job, "vendor", MODEL, fetch)
    assert reads == [MODEL, MODEL]
    assert prices.listed(job, "vendor", MODEL, None)["unit_price"] == 0.14  # no reader: the cache
