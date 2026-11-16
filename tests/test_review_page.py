"""The review page shows every take with what its readings flag, and how to record a verdict."""

from __future__ import annotations

import pytest
from fakes import make_job

from kalainova import reviewpage, takes
from kalainova.jobfs import ContractError


def _take(n, *, ok=True, **readings):
    return {
        "n": n,
        "seed": 7 + n,
        "file": f"takes/b1/take-{n:02d}.mp4",
        "sha256": f"sha{n}",
        "provider": "fal",
        "model": "a <video> model",
        "ok": ok,
        "readings": {"score": 0.2, "shot_motion": 0.2, "width": 1080, "height": 1920, **readings},
        "meta": {"start_frame_sent": True},
        "cost": 0.56,
    }


def test_each_take_is_shown_with_its_flags_and_its_verdict_command(tmp_path):
    beats = [{"id": "b1", "role": "hook", "text": "x", "cast": ["lead"]}]
    job = make_job(tmp_path, beats=beats)
    takes.record(job, "b1", _take(0))
    small = _take(1, ok=False, width=1280, height=720)
    small["readings"]["below_source_floor"] = "1280x720, under 1080px a side"
    takes.record(job, "b1", small)

    page = reviewpage.write(job).read_text()

    assert page.count("<video") == 2
    assert "take 0 ★ in use" in page
    assert "under the source size: 1280x720" in page
    assert (
        f"kalainova verdict {job.id} accept|fix|reject --reviewer NAME --shot b1 --take 1" in page
    )
    assert f"kalainova take {job.id} b1 1" in page  # how to use the take not in use
    assert "a &lt;video&gt; model" in page  # text from a record is escaped
    assert "The face is the kit" in page  # a shot with a character asks about the face


def test_a_shot_without_a_character_is_not_asked_about_a_face(tmp_path):
    job = make_job(tmp_path, beats=[{"id": "b1", "role": "hook", "text": "x", "cast": []}])
    takes.record(job, "b1", _take(0))
    page = reviewpage.write(job).read_text()
    assert "B-roll" in page and "The face is the kit" not in page
    assert "Hands have five fingers" in page


def test_no_takes_means_nothing_to_review(tmp_path):
    with pytest.raises(ContractError, match="no takes"):
        reviewpage.write(make_job(tmp_path))
