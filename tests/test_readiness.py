"""A package says whether each paid call is ready to buy, before anyone is asked to sign it off.

A wrong or missing input blocks it; what is likely to need a retake is a risk that a person fixes or
accepts with a reason (readiness.py, ADR 0022). Nothing here calls a model.
"""

from __future__ import annotations

import pytest
from fakes import make_job

from kalainova import readiness
from kalainova.providers import base
from kalainova.providers.contract import Inputs

WORDS = "the DJ, both hands on the mixer, behind the decks, warm amber light, medium shot"


def _beat(**over):
    beat = {
        "id": "s00",
        "role": "hook",
        "text": "A line.",
        "visual_kind": "video",
        "visual_cue": "The DJ lifts one hand from the mixer as the light sweeps across",
        "duration_sec": 3.0,
        "shot": {"size": "medium", "camera": "a slow push in", "must_show": "the DJ at the decks"},
    }
    return {**beat, **over}


def _video(**asked):
    full = {"capability": "video", "prompt": WORDS, "duration": 3.0, "dst": "take-00.mp4",
            "start": {"file": "s00.still.png", "sha256": "aa"},
            "references": [{"label": "lead"}], **asked}  # fmt: skip
    return {"n": 1, "capability": "video", "provider": "fake", "routed": "", "shot": "s00",
            "asked": full, "requests": []}  # fmt: skip


def _ids(found):
    return {f["id"]: f["level"] for f in found}


def test_a_concrete_shot_with_everything_it_needs_is_ready(tmp_path):
    job = make_job(tmp_path, beats=[_beat(cast=["lead"])])
    assert readiness.review(job, "motion", [_video()]) == []


def test_a_vague_prompt_is_a_risk_named_for_its_shot(tmp_path):
    job = make_job(tmp_path, beats=[_beat()])
    found = readiness.review(job, "motion", [_video(prompt="a cool club shot")])
    assert _ids(found) == {"vague_prompt:s00": "risk"}
    assert "4 words" in found[0]["detail"] and found[0]["fix"]


def test_a_face_with_no_reference_picture_blocks(tmp_path):
    job = make_job(tmp_path, beats=[_beat(cast=["lead"])])
    assert _ids(readiness.review(job, "motion", [_video(references=[])])) == {
        "no_references:s00": "block"
    }


def test_a_moving_shot_that_says_nothing_of_success_is_a_risk(tmp_path):
    job = make_job(tmp_path, beats=[_beat(shot={"size": "medium", "camera": "a slow push in"})])
    assert _ids(readiness.review(job, "motion", [_video()])) == {"no_success_stated:s00": "risk"}


def test_a_shot_longer_than_the_model_makes_blocks(tmp_path, studio, monkeypatch):
    job = make_job(tmp_path, beats=[_beat()])
    fake = base.get("fake")
    monkeypatch.setattr(type(fake), "inputs", lambda self, c, m=None: Inputs(longest_sec=2.0))
    assert _ids(readiness.review(job, "motion", [_video()])) == {"too_long:s00": "block"}


def test_motion_waits_for_an_accepted_animatic_and_its_stills(tmp_path):
    job = make_job(tmp_path, beats=[_beat()], brief={"subject": "a test", "animatic_gate": True})
    assert "animatic_not_accepted:piece" in _ids(readiness.review(job, "motion", [_video()]))
    data = job.job
    data["animatic_reviewed"] = {
        "verdict": "accept",
        "stills": {"s00": "bb"},
        "reviewer": "a person",
        "at": "2026-11-16T00:00:00+00:00",
        "animatic_sha256": "cc",
    }
    job.write("job", data)
    assert _ids(readiness.review(job, "motion", [_video()])) == {"start_frame_changed:s00": "block"}


def test_the_plans_own_review_is_carried_onto_its_shot(tmp_path):
    long_hold = _beat(cast=["lead"], duration_sec=6.0)
    job = make_job(tmp_path, beats=[long_hold])
    found = _ids(readiness.review(job, "stills", []))
    assert found == {"character_shot_length:s00": "risk"}
    job = make_job(tmp_path / "b", beats=[_beat(continues=True)])
    assert _ids(readiness.review(job, "stills", [])) == {"continues:s00": "block"}


def test_a_field_the_vendor_would_refuse_blocks(tmp_path):
    job = make_job(tmp_path, beats=[_beat()])
    call = {**_video(), "requests": [{"schema": ["safety_tolerance is not a field"]}]}
    assert _ids(readiness.review(job, "motion", [call])) == {"vendor_schema:s00": "block"}


@pytest.mark.parametrize("capability", ["music", "voice", "llm"])
def test_a_call_with_no_picture_is_not_held_to_picture_checks(tmp_path, capability):
    job = make_job(tmp_path, beats=[_beat()])
    call = {"n": 1, "capability": capability, "provider": "fake", "shot": "",
            "asked": {"prompt": "calm"}, "requests": []}  # fmt: skip
    assert readiness.review(job, "motion", [call]) == []
