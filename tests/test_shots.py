"""How a shot is written: what a still is told, what a clip is told, and what a plan is refused."""

from __future__ import annotations

from kalainova import shots

STYLE = "cinematic film still, 35mm"
COAT = "a tall woman in a long green raincoat"
STREET = "a wet street far below the window"


def _beat(**extra):
    return {"id": "b1", "role": "body", "text": "A line.", **extra}


def _packet(*beats, **extra):
    return {"beats": list(beats), **extra}


def test_a_still_starts_from_its_first_frame_and_carries_the_fixed_descriptions():
    beat = _beat(
        visual_cue="ignored once a first frame exists",
        shot={"first_frame": "He stands at the glass."},
        cast=["walker"],
        location="office",
    )
    block = {"people": {"walker": COAT}, "places": {"office": STREET}}
    prompt = shots.still_prompt(_packet(beat, continuity=block), beat, STYLE)
    assert prompt.startswith("He stands at the glass.")
    assert COAT in prompt and STREET in prompt and "35mm" in prompt
    assert "ignored" not in prompt


def test_the_same_person_gets_the_same_words_in_every_shot():
    block = {"people": {"walker": COAT}}
    first = shots.continuity_text(_packet(continuity=block), _beat(cast=["walker"]))
    second = shots.continuity_text(_packet(continuity=block), _beat(id="b9", cast=["walker"]))
    assert first == second == [COAT]


def test_a_clip_with_a_start_image_is_told_what_moves_and_not_what_things_look_like():
    beat = _beat(
        visual_cue="an enormous description of the whole picture",
        shot={
            "first_frame": "The picture.",
            "camera": "Slow push in until the door fills the frame",
            "action": "He wipes the pane",
            "environment": "Waves roll toward the rocks",
        },
    )
    prompt = shots.motion_prompt(_packet(beat), beat, STYLE, has_start_image=True)
    assert prompt.index("push in") < prompt.index("wipes") < prompt.index("Waves")
    assert "The picture" not in prompt and "35mm" not in prompt


def test_a_clip_with_no_start_image_still_gets_the_picture_after_the_motion():
    beat = _beat(shot={"first_frame": "The picture.", "action": "Waves roll"})
    prompt = shots.motion_prompt(_packet(beat), beat, STYLE, has_start_image=False)
    assert prompt.index("Waves roll") < prompt.index("The picture")


def test_a_video_prompt_is_never_told_to_be_a_still():
    beat = _beat(visual_cue="A film still of waves rolling in")
    prompt = shots.motion_prompt(_packet(beat), beat, STYLE, has_start_image=False)
    assert "film still" not in prompt.lower()


def test_a_long_prompt_is_cut_from_the_end_so_the_motion_survives():
    beat = _beat(shot={"action": "She crosses the road.", "environment": " ".join(["water"] * 200)})
    prompt = shots.motion_prompt(_packet(beat), beat, STYLE, has_start_image=True, limit=20)
    assert prompt.startswith("She crosses the road.")
    assert len(prompt.split()) <= 20


def test_a_model_that_makes_sound_is_told_what_this_place_sounds_like():
    beat = _beat(ambience="wind and heavy surf", shot={"action": "Waves roll"})
    with_sound = shots.motion_prompt(
        _packet(beat), beat, STYLE, has_start_image=True, with_sound=True
    )
    without = shots.motion_prompt(_packet(beat), beat, STYLE, has_start_image=True)
    assert "wind and heavy surf" in with_sound and "wind" not in without


def _found(packet, **kw):
    kw.setdefault("budget", 9)
    return {p["id"]: p for p in shots.review(packet, **kw)}


def test_a_name_nobody_described_is_refused_before_anything_is_spent():
    packet = _packet(_beat(cast=["stranger"]), continuity={"people": {"walker": COAT}})
    assert _found(packet)["plan.continuity"]["status"] == "fail"


def test_asking_for_more_moving_shots_than_the_budget_is_refused_unless_stills_are_allowed():
    packet = _packet(_beat(visual_kind="video"), _beat(id="b2", visual_kind="video"))
    assert _found(packet, budget=1)["plan.video_budget"]["status"] == "fail"
    assert _found(packet, budget=1, allow_stills=True)["plan.video_budget"]["status"] == "warn"


def test_the_first_shot_has_nothing_to_continue_from():
    assert _found(_packet(_beat(continues=True)))["plan.continues"]["status"] == "fail"


def test_a_line_said_on_camera_needs_someone_to_say_it():
    assert _found(_packet(_beat(on_camera=True)))["plan.on_camera"]["status"] == "fail"
    assert "plan.on_camera" not in _found(_packet(_beat(on_camera=True, speaker="walker")))


def test_a_moving_shot_that_never_says_what_moves_is_flagged():
    still = _beat(visual_kind="video", visual_cue="A bridge over a river")
    assert "plan.motion_stated" in _found(_packet(still))
    moving = _beat(visual_kind="video", visual_cue="Waves rolling against a rock")
    assert "plan.motion_stated" not in _found(_packet(moving))


def test_a_moving_shot_asking_for_a_still_is_flagged():
    beat = _beat(visual_kind="video", visual_cue="A film still of waves rolling")
    assert "plan.still_words" in _found(_packet(beat))


def test_a_plan_of_mostly_stills_reads_as_a_slideshow():
    beats = [_beat(id=f"b{n}") for n in range(4)]
    assert "plan.slideshow_risk" in _found(_packet(*beats))
    moving = [_beat(id=f"b{n}", visual_kind="video") for n in range(4)]
    assert "plan.slideshow_risk" not in _found(_packet(*moving))
    assert "plan.slideshow_risk" not in _found(_packet(*beats), wants_video=False)


def test_two_shots_describing_the_same_picture_are_flagged():
    cue = "Waves rolling against the black rocks below the iron bridge at dusk"
    beats = [_beat(visual_cue=cue), _beat(id="b2", visual_cue=cue)]
    assert "plan.repetition" in _found(_packet(*beats))


def test_three_shots_of_one_size_in_a_row_are_flagged_once():
    beats = [_beat(id=f"b{n}", shot={"size": "wide"}) for n in range(4)]
    assert (
        sum(1 for p in shots.review(_packet(*beats), budget=9) if p["id"] == "plan.shot_sizes") == 1
    )


def test_a_prompt_past_what_the_model_reads_is_flagged():
    beat = _beat(visual_kind="video", shot={"action": " ".join(["moving"] * 90)})
    assert "plan.prompt_length" in _found(_packet(beat), limit=80)
    assert "plan.prompt_length" not in _found(_packet(beat))


def test_the_limit_is_the_tightest_among_the_providers_a_call_could_reach():
    assert shots.word_limit(["mac"]) == 80
    assert shots.word_limit(["fal"]) is None
