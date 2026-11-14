"""The questions QA asks of a stream job's frames, and what it says when it cannot ask them."""

from __future__ import annotations

import json

import pytest
from fakes import needs_ffmpeg
from kit_fixtures import make_character, make_stream, picture

from kalainova import kitchecks, kits, media, qachecks, streams
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


def _report(passed, *checks):
    return {"passed": passed, "checks": list(checks)}


def test_the_headline_stays_plain_when_nothing_is_broken():
    assert qachecks.headline(_report(True)) == "QA PASSED"
    assert qachecks.headline(_report(False)) == "QA FAILED"


def test_a_broken_motion_promise_or_placeholder_assets_change_the_headline():
    promise = {
        "id": "delivery.motion_promise",
        "status": "warn",
        "detail": "asked to move and did not: b1, b2, b3",
    }
    fake = {"id": "delivery.placeholder", "status": "warn", "detail": "4 placeholder assets: a, b"}
    line = qachecks.headline(_report(True, promise, fake))
    assert "PASSED" not in line and "not reviewable" in line
    assert "did not move: b1, b2, b3" in line and "4 placeholder assets" in line
    assert "FAILED" in qachecks.headline(_report(False, promise))


def test_assets_from_a_placeholder_provider_are_named():
    am = {
        "assets": [
            {"id": "s1", "provider": "local"},
            {"id": "s2", "provider": "operator"},
            {"id": "s3"},
            {"id": "s4", "provider": "nowhere"},
        ]
    }
    (found,) = qachecks.placeholder_checks(am)
    assert found["id"] == "delivery.placeholder" and found["status"] == "warn"
    assert "1 placeholder" in found["detail"] and "s1" in found["detail"]
    assert qachecks.placeholder_checks({"assets": [{"id": "x", "provider": "operator"}]}) == []


def test_an_answer_with_no_cited_region_or_time_is_dropped():
    # Without region or time, problems are dropped
    assert qachecks.shot_problems({"id": "b1", "warping": True}) == []
    assert qachecks.shot_problems({"id": "b1", "geometry_ok": False}) == []
    assert qachecks.shot_problems({"id": "b1", "action_happened": False}) == []
    # With region or time, problems are kept
    assert qachecks.shot_problems(
        {"id": "b1", "warping": True, "region": [0.1, 0.2, 0.3, 0.4]}
    ) == ["warping"]
    assert qachecks.shot_problems({"id": "b1", "geometry_ok": False, "time": 1.5}) == ["geometry"]
    assert qachecks.shot_problems({"id": "b1", "action_happened": False, "at_sec": 2.0}) == [
        "action_missing"
    ]


def test_unsure_is_recorded_as_its_own_status_and_does_not_fail_qa():
    judge = {
        "version": 3,
        "policy_risk": "none",
        "verdict": "ship",
        "shots": [
            {"id": "b1", "status": "unsure", "note": "lighting makes it hard to see"},
            {"id": "b2", "geometry_ok": True, "moved": True, "region": [0, 0, 1, 1]},
        ],
    }
    checks = qachecks.judged_shots(judge)
    ids = {c["id"]: c["status"] for c in checks}
    assert ids.get("judge.unsure") == "unsure"
    # An unsure check does not fail QA
    assert all(c["status"] != "fail" for c in checks)


@needs_ffmpeg
def test_a_clip_that_failed_a_free_reading_is_not_sent_to_the_judge(tmp_path, studio):
    from fakes import make_job

    from kalainova import qa

    job = make_job(
        tmp_path,
        beats=[
            {
                "id": "b1",
                "role": "hook",
                "text": "First beat",
                "visual_cue": "Cue 1",
                "visual_kind": "video",
            },
            {
                "id": "b2",
                "role": "body",
                "text": "Second beat",
                "visual_cue": "Cue 2",
                "visual_kind": "video",
            },
        ],
    )
    # Put a final video
    media.run(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:d=2:r=24",
            "-pix_fmt",
            "yuv420p",
            str(job.work / "final.mp4"),
        ]
    )
    import shutil

    shutil.copy(job.work / "final.mp4", job.work / "b1.video.mp4")
    picture(job.work, "contact.jpg")
    job.write(
        "edit_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "runtime": "ffmpeg",
            "profile": {"aspect": "9:16", "width": 320, "height": 180, "fps": 24.0},
            "duration_sec": 2.0,
            "cuts": [{"id": "c1", "source": "b1.video", "in_sec": 0, "out_sec": 2}],
        },
    )
    job.write(
        "asset_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "assets": [
                {
                    "id": "b1.video",
                    "kind": "video",
                    "rights": "owned",
                    "path": "b1.video.mp4",
                    "synthetic": True,
                }
            ],
        },
    )
    # Studio provides a judge response
    studio.replies = [
        json.dumps(
            {
                "version": 3,
                "policy_risk": "none",
                "verdict": "ship",
                "shots": [{"id": "b2", "status": "pass", "moved": True, "region": [0, 0, 1, 1]}],
            }
        )
    ]

    # Simulate b1 failing a free reading
    def mock_checks(*a, **kw):
        return [{"id": "b1.black_frames", "status": "fail", "detail": "black span"}]

    import kalainova.qachecks as qc

    orig = qc.cut_checks
    qc.cut_checks = mock_checks
    try:
        qa.run(job)
    finally:
        qc.cut_checks = orig

    # The judge call was made, but b1 was excluded from the script
    judge_calls = [c for c in studio.calls if c["capability"] in ("judge", "llm")]
    if judge_calls:
        assert "b1" not in judge_calls[0].get("prompt", "")


def test_a_still_the_fake_judge_flags_is_reported_at_stills_stage_before_any_video_call(
    tmp_path, studio
):
    from fakes import make_job

    from kalainova import assets

    job = make_job(
        tmp_path,
        cost_cap=50.0,
        beats=[
            {
                "id": "b1",
                "role": "hook",
                "text": "Line 1",
                "visual_kind": "video",
                "visual_cue": "a room",
            },
        ],
    )
    # Studio returns a flagged still for b1 with cited region
    studio.replies = [
        json.dumps(
            {
                "version": 1,
                "passed": False,
                "anatomy_ok": False,
                "text_ok": True,
                "cue_ok": True,
                "region": [0.1, 0.2, 0.3, 0.4],
                "note": "garbled hand anatomy",
            }
        )
    ]
    assets.run(job)
    # Check that findings.json holds the fault
    assert job.has("findings")
    findings = job.read("findings")
    assert any(s["id"] == "b1" and "garbled hand" in s["note"] for s in findings["shots"])
    # Video call was NOT made for b1
    video_calls = [c for c in studio.calls if c["capability"] == "video"]
    assert len(video_calls) == 0


@needs_ffmpeg
def test_the_judge_uses_the_judge_model_when_configured(tmp_path, studio, monkeypatch):
    from fakes import make_job

    from kalainova import config, qa

    job = make_job(
        tmp_path,
        beats=[
            {
                "id": "b1",
                "role": "hook",
                "text": "Line 1",
                "visual_kind": "video",
                "visual_cue": "a room",
            }
        ],
    )
    media.run(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=320x180:d=2:r=24",
            "-pix_fmt",
            "yuv420p",
            str(job.work / "final.mp4"),
        ]
    )
    import shutil

    shutil.copy(job.work / "final.mp4", job.work / "b1.video.mp4")
    picture(job.work, "contact.jpg")
    job.write(
        "edit_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "runtime": "ffmpeg",
            "profile": {"aspect": "9:16", "width": 320, "height": 180, "fps": 24.0},
            "duration_sec": 2.0,
            "cuts": [{"id": "c1", "source": "b1.video", "in_sec": 0, "out_sec": 2}],
        },
    )
    job.write(
        "asset_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "assets": [
                {
                    "id": "b1.video",
                    "kind": "video",
                    "rights": "owned",
                    "path": "b1.video.mp4",
                    "synthetic": True,
                }
            ],
        },
    )
    monkeypatch.setattr(
        config,
        "model_for",
        lambda prov, cap: "custom-judge-haiku" if cap == "judge" else "opus-llm",
    )
    studio.replies = [
        json.dumps(
            {
                "version": 3,
                "policy_risk": "none",
                "verdict": "ship",
                "shots": [{"id": "b1", "status": "pass", "moved": True, "region": [0, 0, 1, 1]}],
            }
        )
    ]
    qa.run(job)
    judge_calls = [c for c in studio.calls if c["capability"] in ("judge", "llm")]
    assert len(judge_calls) == 1
    assert judge_calls[0].get("model") == "custom-judge-haiku"
