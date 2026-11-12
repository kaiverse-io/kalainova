"""The live check: opt-in on every side, and read right when it runs. No call here is real."""

from __future__ import annotations

import pytest
from fakes import make_job

from kalainova.__main__ import main
from kalainova.jobfs import ContractError
from kalainova.providers import base, check


class Paid(base.Provider):
    name = "paid"
    capabilities = ("llm", "search", "transcribe", "song")
    broken: list[str] = []
    calls: list[str] = []

    def estimate(self, capability, **request):
        return 0.01

    def llm(self, prompt, **kw):
        Paid.calls.append("llm")
        return base.Result(text="ok", cost=0.012, model="paid-llm")

    def search(self, query, *, limit=5, **kw):
        Paid.calls.append("search")
        if "search" in Paid.broken:
            return {}["hits"]  # the vendor's reply no longer has what the adapter reads
        return base.Result(model="paid-search", cost=0.01)

    def transcribe(self, src, **kw):
        Paid.calls.append("transcribe")
        return base.Result(model="paid-whisper", cost=0.01)


@pytest.fixture
def paid(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    monkeypatch.setitem(base._REGISTRY, "paid", Paid)
    Paid.broken, Paid.calls = [], []
    return Paid


def _job(tmp_path, cap=1.0):
    return make_job(tmp_path, cost_cap=cap)


def test_the_plan_prices_every_call_and_lists_what_has_no_cheap_call(tmp_path, paid):
    calls, unchecked = check.plan(_job(tmp_path), "paid")
    assert {c.capability for c in calls} == {"llm", "search", "transcribe"}
    assert all(c.estimated == 0.01 for c in calls)
    assert [u.capability for u in unchecked] == ["song"] and unchecked[0].status == "unchecked"
    assert paid.calls == []  # planning calls nothing


def test_it_refuses_without_the_flag_and_makes_no_call(tmp_path, paid):
    job = _job(tmp_path)
    calls, _ = check.plan(job, "paid")
    with pytest.raises(ContractError, match="--spend"):
        check.run(job, "paid", calls, spend=False)
    assert paid.calls == [] and job.spent() == 0


def test_it_refuses_a_job_with_no_cap(tmp_path, paid):
    job = _job(tmp_path, cap=None)
    calls, _ = check.plan(job, "paid")
    with pytest.raises(ContractError, match="cost_cap"):
        check.run(job, "paid", calls, spend=True)
    assert paid.calls == []


def test_a_pass_reports_the_charge_against_the_estimate_and_the_ledger_holds_it(tmp_path, paid):
    job = _job(tmp_path)
    calls, _ = check.plan(job, "paid", "llm")
    (out,) = check.run(job, "paid", calls, spend=True)
    assert (out.status, out.model, out.estimated) == ("passed", "paid-llm", 0.01)
    assert out.charged == 0.012 and round(job.spent(), 6) == 0.012


def test_a_reply_that_does_not_match_the_adapter_is_a_schema_mismatch(tmp_path, paid):
    paid.broken = ["search"]
    job = _job(tmp_path)
    calls, _ = check.plan(job, "paid")
    got = {o.capability: o for o in check.run(job, "paid", calls, spend=True)}
    assert got["llm"].status == "passed"
    assert got["search"].status == "schema mismatch" and "KeyError" in got["search"].detail


def test_it_never_runs_under_automation():
    with pytest.raises(ContractError, match="automation"):
        check.refuse_automation({"CI": "true"})
    check.refuse_automation({})


def test_the_command_refuses_here_because_the_tests_are_automation(tmp_path, paid, capsys):
    job = _job(tmp_path)
    assert main(["providers", "--check", "paid", "--job", str(job.folder), "--spend"]) == 1
    assert "automation" in capsys.readouterr().err
    assert paid.calls == []


def test_a_capability_the_provider_lacks_is_an_error(tmp_path, paid):
    with pytest.raises(ContractError, match="no voice"):
        check.plan(_job(tmp_path), "paid", "voice")


class Video(base.Provider):
    name = "video-only"
    capabilities = ("video",)

    def estimate(self, capability, **request):
        return 0.5

    def reference_support(self, capability, model):
        return {"images_param": "x"}


def test_the_video_check_also_tries_a_still_and_a_reference(tmp_path, monkeypatch):
    monkeypatch.setitem(base._REGISTRY, "video-only", Video)
    calls, _ = check.plan(_job(tmp_path), "video-only")
    assert [c.label for c in calls] == ["video", "video from a still", "video from a reference"]
    still = calls[1].kw["image"]
    assert still.read_bytes().startswith(b"\x89PNG")
    assert calls[2].kw["references"][0]["label"]


def test_the_reference_route_is_left_out_for_a_provider_that_cannot_take_one(tmp_path, monkeypatch):
    class Plain(Video):
        name = "plain-video"

        def reference_support(self, capability, model):
            return {}

    monkeypatch.setitem(base._REGISTRY, "plain-video", Plain)
    calls, _ = check.plan(_job(tmp_path), "plain-video")
    assert [c.label for c in calls] == ["video", "video from a still"]
