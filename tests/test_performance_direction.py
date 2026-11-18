"""A person on camera is directed by the engine, the same way in every first take.

Lessons from review, each held here so it cannot come back: a sung cue that half-closed the eyes
left them lifeless; a still caught mid-note set the mouth wide; a prompt over a model's limit is
refused or cut upstream without a word; the default look read as generated.
"""

from __future__ import annotations

import pytest

from kalainova import config, readiness, shotmake, shots
from kalainova.jobfs import ContractError
from kalainova.providers import fal_sing
from kalainova.providers.contract import SingRequest

SUNG = {"start_sec": 0.0, "end_sec": 3.8}
CUE = "front, chest up behind the decks: she sings the line to the crowd, warm light behind her"


def _beat(**extra):
    return {"id": "s00", "text": "", "visual_kind": "video", "visual_cue": CUE, **extra}


def test_a_sung_shot_is_told_how_to_perform_and_a_silent_one_is_not():
    direction = shots.performance("sing")
    sung = _beat(sings=SUNG)
    told = shots.motion_prompt({"beats": [sung]}, sung, "", has_start_image=True)
    assert told.startswith(CUE) and direction in told
    plain = _beat()
    assert direction not in shots.motion_prompt({"beats": [plain]}, plain, "", has_start_image=True)


def test_the_direction_never_names_the_mouth_since_the_voice_moves_it():
    assert not shots.PERFORMED.search(shots.performance("sing"))


def test_fitting_a_word_limit_drops_the_picture_before_the_direction():
    sung = _beat(sings=SUNG)
    kept = len(f"{CUE} {shots.performance('sing')}".split())
    told = shots.motion_prompt({"beats": [sung]}, sung, "35mm", has_start_image=False, limit=kept)
    assert told.endswith(shots.performance("sing")) and "35mm" not in told


@pytest.mark.parametrize(
    "cue",
    ["she sings with her eyes half closed", "she sings, eyes closed", "her mouth wide on the note"],
)
def test_a_sung_cue_that_directs_the_eyes_or_the_mouth_is_warned(cue):
    sung = _beat(visual_cue=cue, sings=SUNG)
    found = [p["id"] for p in shots.review({"beats": [sung]}, budget=9)]
    assert "plan.performance_words" in found
    silent = _beat(visual_cue=cue)
    quiet = shots.review({"beats": [silent]}, budget=9)
    assert "plan.performance_words" not in [p["id"] for p in quiet]
    assert "performance_words" in readiness.FIXES


def test_a_singing_still_starts_with_relaxed_lips_and_nothing_over_the_mouth():
    assert "relaxed lips" in shots.MOUTH_CLEAR and "mid-note" not in shots.MOUTH_CLEAR
    assert "no microphone" in shots.MOUTH_CLEAR


def _request(prompt: str) -> SingRequest:
    from pathlib import Path

    return SingRequest(prompt=prompt, still=Path("s.png"), audio=Path("l.wav"), dst=Path("o.mp4"),
                       aspect="9:16")  # fmt: skip


def test_a_prompt_longer_than_the_model_reads_is_refused_before_it_is_sent():
    claim = {"max": 300, "class": "reseller", "observed": "2026-11-18", "source": "a reference"}
    spec = {"image_param": "image_url", "audio_param": "audio_url",
            "limits": {"prompt_chars": claim}}  # fmt: skip
    body = fal_sing.payload(spec, _request("x" * 300), "still", "line", [], "")
    assert body["prompt"] == "x" * 300
    with pytest.raises(ContractError, match="301 characters"):
        fal_sing.payload(spec, _request("x" * 301), "still", "line", [], "")


def test_the_configured_singing_models_carry_their_prompt_limits_with_sources():
    rows = config.studio()["sing_models"]["fal"]
    omni = rows["bytedance/omnihuman/v2"]["limits"]["prompt_chars"]
    assert omni["max"] == 300 and omni["provisional"] and omni["class"] == "reseller"
    assert omni["source"] and omni["observed"]
    heygen = rows["heygen/avatar-6/image-to-video"]["limits"]["prompt_chars"]
    assert heygen["max"] == 1200 and heygen["class"] == "vendor"


def test_the_engine_adds_no_look_of_its_own_and_a_studio_or_brief_sets_one(monkeypatch):
    assert shotmake.style({"brief": {}}) == ""  # a look is a studio's taste, not the engine's
    studio = {**config.studio(), "visual_style": "photographed, not rendered"}
    monkeypatch.setattr(shotmake.config, "studio", lambda: studio)
    assert shotmake.style({"brief": {}}) == "photographed, not rendered"
    assert shotmake.style({"brief": {"visual_style": "ink and wash"}}) == "ink and wash"
