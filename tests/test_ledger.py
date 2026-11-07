"""The money: a reservation is held before a call, and settles at what the call really cost."""

from __future__ import annotations

import threading

import pytest
from fakes import Studio, make_job, studio  # noqa: F401
from PIL import Image

from kalainova.jobfs import CostCapExceeded
from kalainova.providers import base, router


def test_a_reservation_counts_against_the_cap_before_any_money_moves(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path, cost_cap=1.0)
    first = job.reserve("fal", "video", 0.8)
    assert first and job.spent() == 0.0 and job.committed() == pytest.approx(0.8)
    with pytest.raises(CostCapExceeded):
        job.reserve("fal", "video", 0.3)


def test_parallel_reservations_cannot_overshoot_the_cap(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path, cost_cap=1.0)
    won, lost = [], []

    def try_to_reserve():
        try:
            won.append(job.reserve("fal", "video", 0.4))
        except CostCapExceeded:
            lost.append(1)

    threads = [threading.Thread(target=try_to_reserve) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(won) == 2 and len(lost) == 6
    assert job.committed() == pytest.approx(0.8)


def test_settling_replaces_the_estimate_with_the_real_cost(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path, cost_cap=5.0)
    held = job.reserve("fal", "video", 2.0)
    job.charge("fal", "video", 1.25, "shot", held)
    assert job.spent() == pytest.approx(1.25) and job.committed() == pytest.approx(1.25)


def test_a_release_gives_the_money_back(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path, cost_cap=5.0)
    job.release(job.reserve("fal", "video", 2.0))
    assert job.committed() == 0.0


def test_a_free_call_holds_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path, cost_cap=0.0)
    assert job.reserve("mac", "video", 0.0) is None
    assert job.committed() == 0.0


class Priced(base.Provider):
    name = "priced"
    capabilities = ("image",)
    outcome = "ok"

    def estimate(self, capability, **request):
        return 1.0

    def image(self, prompt, dst, *, width=64, height=64, **kw):
        if Priced.outcome == "billed":
            raise base.BilledError(0.75, "the file did not arrive")
        if Priced.outcome == "down":
            raise OSError("no route to vendor")
        if Priced.outcome == "bug":
            raise TypeError("an adapter bug")
        Image.linear_gradient("L").resize((width, height)).convert("RGB").save(dst, format="PNG")
        return base.Result(path=dst, cost=0.5, model="priced-1")


@pytest.fixture
def priced(monkeypatch, tmp_path):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    base.names()
    monkeypatch.setitem(base._REGISTRY, "priced", Priced)
    Priced.outcome = "ok"
    job = make_job(tmp_path, cost_cap=10.0, providers={"image": ["priced"]})
    return job, job.work / "a.png"


def test_a_call_settles_at_its_real_cost(priced):
    job, dst = priced
    router.generate(job, "image", "image", "a prompt", dst, width=64, height=64)
    assert job.spent() == pytest.approx(0.5) and job.committed() == pytest.approx(0.5)


def test_money_the_vendor_took_stays_on_the_ledger_when_the_file_is_lost(priced):
    job, dst = priced
    Priced.outcome = "billed"
    with pytest.raises(router.ProviderError):
        router.generate(job, "image", "image", "a prompt", dst, width=64, height=64)
    assert job.spent() == pytest.approx(0.75)
    assert job.committed() == pytest.approx(0.75), "no reservation is left open"


def test_a_failed_call_that_was_not_billed_costs_nothing(priced):
    job, dst = priced
    Priced.outcome = "down"
    with pytest.raises(router.ProviderError):
        router.generate(job, "image", "image", "a prompt", dst, width=64, height=64)
    assert job.committed() == 0.0


def test_a_bug_in_an_adapter_is_raised_with_nothing_left_held(priced):
    job, dst = priced
    Priced.outcome = "bug"
    with pytest.raises(TypeError):
        router.generate(job, "image", "image", "a prompt", dst, width=64, height=64)
    assert job.committed() == 0.0
