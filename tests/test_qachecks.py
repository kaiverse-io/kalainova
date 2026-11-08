"""The questions QA asks of a stream job's frames, and what it says when it cannot ask them."""

from __future__ import annotations

import json

import pytest
from kit_fixtures import make_character, make_stream, picture

from kalainova import kitchecks, kits, qachecks, streams
from kalainova.jobfs import ContractError
from kalainova.providers import router


@pytest.fixture
def locked(root):
    make_character(root)
    make_stream(root)
    return streams.request(root, "chan", "a piece")


def _packet(job):
    return {"beats": [{"id": "b1", "text": "A line.", "cast": ["lead"]}], "job_id": job.id}


def _manifest(job):
    from kalainova import consistency

    return {"assets": [], "kit_lock_sha256": consistency.lock_sha256(job)}


def _ids(checks):
    return {c["id"]: c["status"] for c in checks}


def test_a_job_with_no_lock_has_no_lock_to_check(tmp_path):
    from fakes import make_job

    job = make_job(tmp_path)
    assert qachecks.kit_checks(job, {"beats": []}, {"assets": []}, None) == []


def test_a_lock_that_no_longer_holds_fails(locked, monkeypatch):
    def broken(job):
        raise ContractError("the kit's bytes changed")

    monkeypatch.setattr(qachecks.consistency, "for_job", broken)
    found = qachecks.kit_checks(locked, _packet(locked), _manifest(locked), None)
    assert _ids(found) == {"consistency.lock": "fail"}
    assert "bytes changed" in found[0]["detail"]


def test_assets_from_before_this_lock_fail(locked):
    found = _ids(qachecks.kit_checks(locked, _packet(locked), {"assets": []}, None))
    assert found["consistency.manifest"] == "fail"


def test_with_no_sheet_a_person_is_told_to_compare_the_frames(locked):
    found = qachecks.kit_checks(locked, _packet(locked), _manifest(locked), None)
    assert _ids(found)["consistency.vision"] == "warn"
    assert "no contact sheet" in next(c for c in found if c["id"] == "consistency.vision")["detail"]


def _sheet(job):
    picture(job.work, "contact.jpg")
    return "contact.jpg"


def test_a_vision_model_compares_the_frames_with_the_kit(locked, monkeypatch):
    seen = {}

    def judged(job, capability, fn, text, **kw):
        seen.update(kw)
        reply = {"same_character": False, "style_matches": True, "resembles_real_person": False}
        return None, type("Reply", (), {"text": json.dumps(reply)})

    monkeypatch.setattr(router, "generate", judged)
    found = qachecks.kit_checks(locked, _packet(locked), _manifest(locked), _sheet(locked))
    assert _ids(found)["consistency.character"] == "fail"
    assert len(seen["images"]) == 3, "the kit's two pictures, and the sheet"


def test_with_no_vision_model_a_person_is_told_to_compare_the_frames(locked, monkeypatch):
    def none_ready(*a, **k):
        raise LookupError("no provider")

    monkeypatch.setattr(router, "generate", none_ready)
    found = qachecks.kit_checks(locked, _packet(locked), _manifest(locked), _sheet(locked))
    assert "no vision model" in next(c for c in found if c["id"] == "consistency.vision")["detail"]


def test_a_vision_check_that_breaks_says_so_and_the_human_gate_stands(locked, monkeypatch):
    def broke(*a, **k):
        raise ValueError("bad reply")

    monkeypatch.setattr(router, "generate", broke)
    found = qachecks.kit_checks(locked, _packet(locked), _manifest(locked), _sheet(locked))
    vision = next(c for c in found if c["id"] == "consistency.vision")
    assert vision["status"] == "warn" and "bad reply" in vision["detail"]


def test_going_over_the_budget_is_not_swallowed(locked, monkeypatch):
    from kalainova.jobfs import CostCapExceeded

    def over(*a, **k):
        raise CostCapExceeded("over")

    monkeypatch.setattr(router, "generate", over)
    with pytest.raises(CostCapExceeded):
        qachecks.kit_checks(locked, _packet(locked), _manifest(locked), _sheet(locked))


def test_a_judge_is_shown_each_characters_own_pictures(locked, root):
    from kalainova import consistency

    resolved, lock = consistency.for_job(locked)
    images = kitchecks.judge_images(resolved, lock["cast"], per_character=1)
    assert len(images) == 1 and images[0] == kits.blob_path(
        root, resolved.characters[lock["cast"][0]]["identity"]["refs"][0]
    )
