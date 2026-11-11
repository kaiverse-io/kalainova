"""A moving-picture profile moves every shot unless the brief asks for fewer."""

from __future__ import annotations

import pytest
from fakes import make_job, needs_ffmpeg

from kalainova import assets, plan, shots
from kalainova.jobfs import ContractError
from kalainova.providers import base


def _data(profile=None, **brief):
    data = {"brief": {"subject": "a test", **brief}, "media": ["video", "audio"]}
    if profile:
        data["profile"] = profile
    return data


@pytest.mark.parametrize(
    "profile", [None, "short-9x16", "square", "landscape", "story-4x5", "film-hd", "film-uhd"]
)
def test_every_moving_profile_moves_every_shot_by_default(profile):
    assert shots.video_budget(_data(profile)) >= shots.UNLIMITED


@pytest.mark.parametrize("profile", ["song", "podcast"])
def test_audio_only_profiles_keep_the_small_limit(profile):
    assert shots.video_budget(_data(profile)) == 3


def test_the_brief_can_still_ask_for_fewer():
    assert shots.video_budget(_data("short-9x16", max_video_beats=2)) == 2
    assert shots.video_budget(_data("short-9x16", max_video_beats=0)) == 0


def test_the_planner_is_told_to_move_every_beat(tmp_path):
    job = make_job(tmp_path, profile="short-9x16", brief={"subject": "a test"})
    text = plan._prompt(job.job)
    assert "every beat" in text and "at most" not in text


def test_the_planner_is_told_the_limit_when_the_brief_sets_one(tmp_path):
    job = make_job(tmp_path, brief={"subject": "a test", "max_video_beats": 2})
    assert "at most 2 beats" in plan._prompt(job.job)


def _beat(i):
    return {
        "id": f"b{i}",
        "role": "body",
        "text": "A line of words to say.",
        "visual_kind": "video",
        "visual_cue": f"Shot number {i} rolling",
    }


class Priced(base.Provider):
    name = "priced-video"
    capabilities = ("video",)

    def estimate(self, capability, **request):
        return 4.0


@needs_ffmpeg
def test_moving_shots_over_the_cap_are_refused_before_any_call(tmp_path, studio, monkeypatch):
    monkeypatch.setitem(base._REGISTRY, "priced-video", Priced)
    job = make_job(
        tmp_path,
        beats=[_beat(1), _beat(2), _beat(3)],
        cost_cap=10.0,
        brief={"subject": "a test"},
        providers={"video": ["priced-video"], "image": ["fake"], "voice": ["fake"]},
    )
    with pytest.raises(ContractError, match="estimated at \\$12.00"):
        assets.run(job)
    assert studio.calls == []
    assert job.committed() == 0.0


@needs_ffmpeg
def test_the_estimate_is_printed_when_it_fits(tmp_path, studio, monkeypatch, capsys):
    monkeypatch.setitem(base._REGISTRY, "priced-video", Priced)
    job = make_job(
        tmp_path,
        beats=[_beat(1)],
        cost_cap=None,
        brief={"subject": "a test"},
        providers={"video": ["priced-video"]},
    )
    piece = assets._open_piece(job, False)
    assets._refuse_over_the_cap(piece)
    assert "moving shots: about $4.00" in capsys.readouterr().err
