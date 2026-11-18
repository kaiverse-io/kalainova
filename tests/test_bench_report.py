"""A bench, read: a pick the engine explains, ranked only within the takes compared (ADR 0026),
and a person's preferences, aspect by aspect, that the readings are held to."""

from __future__ import annotations

import json

import pytest
from fakes import make_job

from kalainova import benchreport, config, verdicts
from kalainova.jobfs import ContractError
from kalainova.takejudges import merged

RULES = [{"reading": "lip.conf", "better": "higher"}, {"reading": "lip.dist", "better": "lower"}]


def _take(n: int, ok: bool = True, model: str = "m", **found: float) -> dict:
    judged = {k.replace("__", "."): v for k, v in found.items() if "__" in k}
    plain = {k: v for k, v in found.items() if "__" not in k}
    return {"n": n, "ok": ok, "model": model, "readings": {**plain, "judged": judged}}


def test_takes_are_ranked_within_the_bench_and_the_pick_says_why():
    made = [
        _take(0, lip__conf=5.0, lip__dist=7.0),
        _take(1, lip__conf=3.0, lip__dist=9.0),
        _take(2, lip__conf=4.0, lip__dist=8.0),
    ]
    found = benchreport.rank(made, RULES)
    assert [r["n"] for r in found["order"]] == [0, 2, 1]
    assert found["status"] == "pick" and found["pick"] == 0
    assert "lip.conf 5 (1 of 3)" in found["reason"] and "lip.dist 7 (1 of 3)" in found["reason"]


def test_a_readings_unit_does_not_change_the_order_because_it_is_scaled_within_the_bench():
    small = [_take(0, lip__conf=5.0, lip__dist=7.0), _take(1, lip__conf=3.0, lip__dist=9.0)]
    large = [_take(0, lip__conf=500.0, lip__dist=0.07), _take(1, lip__conf=300.0, lip__dist=0.09)]
    scores = [[r["score"] for r in benchreport.rank(m, RULES)["order"]] for m in (small, large)]
    assert scores[0] == scores[1]


def test_a_close_second_is_a_persons_call():
    made = [
        _take(0, lip__conf=5.0, lip__dist=8.0),
        _take(1, lip__conf=4.9, lip__dist=8.0),
        _take(2, lip__conf=1.0, lip__dist=8.0),
    ]
    found = benchreport.rank(made, RULES, close=0.25)
    assert found["status"] == "close" and found["pick"] == 0
    assert "a person decides" in found["reason"]


def test_a_take_under_the_size_floor_is_ranked_but_not_picked():
    made = [
        _take(0, width=716, height=1284, lip__conf=6.0, lip__dist=7.0),
        _take(1, width=1080, height=1920, lip__conf=4.0, lip__dist=8.0),
    ]
    found = benchreport.rank(made, RULES, floor=1048)
    assert found["order"][0]["n"] == 0 and found["pick"] == 1
    assert "under the 1048 px floor" in found["reason"]
    alone = benchreport.rank(made[:1], RULES, floor=1048)
    assert alone["status"] == "unsure" and alone["pick"] is None


def test_a_take_missing_a_reading_or_its_floor_is_listed_and_not_ranked():
    made = [
        _take(0, lip__conf=5.0, lip__dist=7.0),
        _take(1, lip__conf=3.0),
        _take(2, ok=False, lip__conf=9.0, lip__dist=1.0),
    ]
    found = benchreport.rank(made, RULES)
    assert [r["n"] for r in found["order"]] == [0]
    assert "lip.dist" in found["left_out"][1] and found["left_out"][2] == "missed its floor"


def test_with_nothing_set_to_rank_there_is_no_pick():
    found = benchreport.rank([_take(0)], [])
    assert found["status"] == "none" and found["pick"] is None


def test_a_rank_rule_says_which_way_is_better(monkeypatch):
    table = {"rank": {"sing": [{"reading": "x", "better": "sideways"}]}}
    monkeypatch.setattr(config, "studio", lambda: table)
    with pytest.raises(ContractError, match="higher or lower"):
        benchreport.rules("sing")


def test_a_label_names_the_model_without_the_route_every_model_shares():
    both = "fal-ai/kling-video/o3/pro/reference-to-video+fal-ai/sync-lipsync/v3"
    assert benchreport.short(both) == "kling-video/o3/pro + sync-lipsync/v3"
    assert benchreport.short("heygen/avatar-6/image-to-video") == "heygen/avatar-6"


def test_a_second_judge_kind_adds_its_scores_and_the_first_keeps_its_rank():
    first = {"shot_motion": 0.2, "judged": {"lip.conf": 5.0}, "rank": 5.0}
    out = merged(first, {"judged": {"perf.head": 9.0}, "rank": 9.0})
    assert out["judged"] == {"lip.conf": 5.0, "perf.head": 9.0} and out["rank"] == 5.0
    assert merged(first, {}) is first
    assert merged({}, {"judged": {"perf.head": 9.0}, "rank": 1.0})["rank"] == 1.0


def _three_takes(tmp_path):
    job = make_job(tmp_path)
    rows = [(0, 9.0, 3.0), (1, 2.0, 6.0), (2, 5.0, 4.0)]
    made = [
        {"n": n, "seed": 1, "file": f"t{n}.mp4", "sha256": f"sha{n}", "provider": "fake",
         "model": f"m{n}", "ok": True, "bench": True,
         "readings": {"judged": {"perf.head": head, "lip.conf": conf}}}
        for n, head, conf in rows
    ]  # fmt: skip
    data = {"schema_version": "0.1", "job_id": job.id,
            "shots": {"s1": {"chosen": 0, "chosen_by": "reading", "takes": made}}}  # fmt: skip
    (job.folder / "takes.json").write_text(json.dumps(data))
    return job


def test_the_best_of_several_takes_is_a_preference_over_each_of_the_others(tmp_path):
    job = _three_takes(tmp_path)
    entries = verdicts.best_of(job, 0, [0, 1, 2], reviewer="r", shot="s1", aspect="head")
    assert [(e["preferred"], e["over"], e["aspect"]) for e in entries] == [
        (0, 1, "head"),
        (0, 2, "head"),
    ]
    with pytest.raises(ContractError, match="not among"):
        verdicts.best_of(job, 5, [0, 1], reviewer="r", shot="s1")
    with pytest.raises(ContractError, match="an aspect is one of"):
        verdicts.record(job, "accept", reviewer="r", shot="s1", preferred=0, over=1, aspect="vibe")


def test_each_reading_is_held_to_what_a_person_preferred_on_its_own_aspect(tmp_path):
    job = _three_takes(tmp_path)
    verdicts.best_of(job, 0, [0, 1, 2], reviewer="r", shot="s1", aspect="head")
    verdicts.best_of(job, 1, [0, 1, 2], reviewer="r", shot="s1", aspect="lips")
    found = {(r["aspect"], r["reading"]): r for r in verdicts.agreement(tmp_path / "jobs")}
    assert found[("head", "perf.head")]["higher_won"] == 1.0
    assert found[("head", "lip.conf")]["higher_won"] == 0.0
    assert found[("lips", "lip.conf")]["higher_won"] == 1.0
    assert found[("lips", "lip.conf")]["says"] == verdicts.NOT_ENOUGH, "two pairs prove nothing"
