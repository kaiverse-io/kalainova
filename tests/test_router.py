"""The rules every model call runs under, tested with a provider that misbehaves on request."""

from __future__ import annotations

import json
import threading
import time

import pytest

from kalainova.jobfs import CostCapExceeded, Job
from kalainova.providers import base, router


class Flaky(base.Provider):
    name = "flaky"
    capabilities = ("image", "llm")
    env_key = None
    calls = 0
    cost = 1.0
    fails = None

    def image(self, prompt, dst, *, width=64, height=64, **kw):
        type(self).calls += 1
        if type(self).fails:
            raise type(self).fails
        dst.write_bytes(f"bytes:{prompt}".encode())
        return base.Result(path=dst, cost=self.cost, model="flaky-1")

    def llm(self, prompt, **kw):
        type(self).calls += 1
        return base.Result(text="ok", cost=self.cost, model="flaky-1")


class Backup(Flaky):
    name = "backup"
    calls = 0
    fails = None


class Placeholder(Flaky):
    name = "placeholder"
    calls = 0
    fails = None
    free = True
    placeholder = True


class Hung(Flaky):
    name = "hung"
    calls = 0
    fails = None

    def image(self, prompt, dst, **kw):
        type(self).calls += 1
        time.sleep(1.0)
        dst.write_bytes(b"late")  # an abandoned call finishing after the engine moved on
        return base.Result(path=dst, cost=self.cost, model="hung-1")


PRICES = {"flaky": {"image": {"per_image": 1.0}, "llm": {"input_per_mtok": 1.0}},
          "backup": {"image": {"per_image": 1.0}}, "hung": {"image": {"per_image": 1.0}}}


@pytest.fixture(autouse=True)
def providers(monkeypatch, tmp_path):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    base.names()
    for cls in (Flaky, Backup, Placeholder, Hung):
        cls.calls = 0
        cls.fails = None
        monkeypatch.setitem(base._REGISTRY, cls.name, cls)
    monkeypatch.setattr(base.config, "price_for", lambda provider, key: dict(PRICES.get(provider, {}).get(key, {})))
    yield


def job_with(tmp_path, order, cap=None):
    folder = tmp_path / "jobs" / "r"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(json.dumps({
        "schema_version": "0.1", "job_id": "r", "strategy": "generated", "media": ["video"], "rights": "owned",
        "distribution_identity": "t", "status": "draft", "cost_cap": cap,
        "providers": {"image": order, "llm": order}}))
    return Job(folder)


def image(job, name="a.png", prompt="p", **kw):
    return router.generate(job, "image", "image", prompt, job.work / name, **kw)


def test_a_pinned_provider_fails_the_job_and_nothing_is_substituted(tmp_path):
    job = job_with(tmp_path, ["flaky"])
    Flaky.fails = ConnectionError("node offline")
    with pytest.raises(router.ProviderError, match="node offline"):
        image(job)
    assert not (job.work / "a.png").exists()
    assert job.spent() == 0


def test_failover_only_reaches_listed_providers_and_is_reported(tmp_path, capfd):
    job = job_with(tmp_path, ["flaky", "backup"])
    Flaky.fails = ConnectionError("node offline")
    p, _ = image(job)
    assert p.name == "backup"
    assert "used backup after: flaky" in capfd.readouterr().err


def test_a_bug_in_an_adapter_is_raised_not_treated_as_an_outage(tmp_path):
    job = job_with(tmp_path, ["flaky", "backup"])
    Flaky.fails = TypeError("adapter bug")
    with pytest.raises(TypeError):
        image(job)
    assert Backup.calls == 0


def test_a_restart_reuses_paid_files_and_does_not_charge_again(tmp_path):
    job = job_with(tmp_path, ["flaky"])
    image(job)
    image(job)
    assert Flaky.calls == 1
    assert job.spent() == 1.0


def test_a_changed_request_or_file_is_generated_again(tmp_path):
    job = job_with(tmp_path, ["flaky"])
    image(job)
    image(job, prompt="different")
    assert Flaky.calls == 2
    (job.work / "a.png").write_bytes(b"changed on disk")
    image(job, prompt="different")
    assert Flaky.calls == 3


def test_fresh_generates_again(tmp_path):
    job = job_with(tmp_path, ["flaky"])
    image(job)
    image(job, fresh=True)
    assert Flaky.calls == 2


def test_a_placeholder_is_never_reused_once_the_real_provider_returns(tmp_path):
    job = job_with(tmp_path, ["flaky", "placeholder"])
    Flaky.fails = ConnectionError("node offline")
    assert image(job)[0].name == "placeholder"
    Flaky.fails = None
    assert image(job)[0].name == "flaky"


def test_a_hung_call_is_abandoned_charged_and_cannot_overwrite_the_result(tmp_path, monkeypatch):
    monkeypatch.setattr(router, "_deadline", lambda capability: 0.1)
    job = job_with(tmp_path, ["hung", "backup"])
    p, _ = image(job)
    assert p.name == "backup"
    assert job.spent() == 2.0  # the abandoned call may have been billed, so its estimate counts
    good = (job.work / "a.png").read_bytes()
    time.sleep(1.2)
    assert (job.work / "a.png").read_bytes() == good


def test_a_capped_job_refuses_an_unpriced_provider_before_calling_it(tmp_path, monkeypatch):
    monkeypatch.setattr(base.config, "price_for", lambda provider, key: {})
    job = job_with(tmp_path, ["flaky"], cap=100)
    with pytest.raises(router.ProviderError, match="no price"):
        image(job)
    assert Flaky.calls == 0


def test_an_uncapped_job_may_use_an_unpriced_provider(tmp_path, monkeypatch):
    monkeypatch.setattr(base.config, "price_for", lambda provider, key: {})
    job = job_with(tmp_path, ["flaky"])
    assert image(job)[0].name == "flaky"


def test_the_cap_stops_a_call_before_it_is_made(tmp_path):
    job = job_with(tmp_path, ["flaky", "backup"], cap=1.5)
    image(job)
    with pytest.raises(CostCapExceeded):
        image(job, name="b.png", prompt="q")
    assert Flaky.calls == 1 and Backup.calls == 0


def test_llm_calls_are_charged_and_not_saved(tmp_path):
    job = job_with(tmp_path, ["flaky"])
    router.generate(job, "llm", "llm", "same prompt")
    router.generate(job, "llm", "llm", "same prompt")
    assert Flaky.calls == 2
    assert job.spent() == 2.0


def test_no_ready_provider_is_a_lookup_error_callers_can_handle(tmp_path):
    job = job_with(tmp_path, ["not-a-provider"])
    with pytest.raises(LookupError, match="not-a-provider"):
        image(job)
    assert not router.available(job, "image")


def test_parallel_charges_all_reach_the_ledger(tmp_path):
    job = job_with(tmp_path, ["flaky"])
    errors = []

    def worker():
        for _ in range(25):
            try:
                job.charge("flaky", "image", 1.0)
            except Exception as exc:
                errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert job.spent() == 200.0
