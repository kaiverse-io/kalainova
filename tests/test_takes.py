"""Several attempts at a shot: a reading picks, and a person's choice stands."""

from __future__ import annotations

import pytest
from fakes import make_job, needs_ffmpeg

from kalainova import assets, edit, media, publish, qa, render, shotmake, takes
from kalainova.jobfs import ContractError

pytestmark = needs_ffmpeg


def _moving_beat(**extra):
    return {
        "id": "b1",
        "role": "hook",
        "text": "A line.",
        "visual_kind": "video",
        "visual_cue": "Waves rolling in",
        **extra,
    }


def _shot(job):
    return takes.load(job)["shots"]["b1"]


def test_a_frozen_take_asks_for_another_with_a_new_seed(tmp_path, studio):
    studio.frozen_takes = 1
    job = make_job(tmp_path, beats=[_moving_beat()])
    assets.run(job)
    videos = [c for c in studio.calls if c["capability"] == "video"]
    assert len(videos) == 2 and videos[0]["seed"] != videos[1]["seed"]
    shot = _shot(job)
    assert [t["ok"] for t in shot["takes"]] == [False, True]
    assert shot["chosen"] == 1 and shot["chosen_by"] == "reading"


def test_a_shot_that_reads_well_first_time_costs_one_take(tmp_path, studio):
    job = make_job(tmp_path, beats=[_moving_beat()])
    assets.run(job)
    assert sum(1 for c in studio.calls if c["capability"] == "video") == 1


def test_retakes_stop_at_the_limit_and_keep_the_best_of_what_came(tmp_path, studio):
    studio.frozen_takes = 99
    job = make_job(tmp_path, beats=[_moving_beat()])
    assets.run(job)
    assert len(_shot(job)["takes"]) == 2, "the studio's limit, even though no take read well"


def test_a_brief_can_ask_for_more_takes_up_front(tmp_path, studio):
    job = make_job(
        tmp_path,
        beats=[_moving_beat()],
        brief={"subject": "a test", "max_video_beats": 9, "takes": 3, "max_takes": 3},
    )
    assets.run(job)
    assert len(_shot(job)["takes"]) == 3


def test_every_take_is_kept_with_its_seed_and_reading(tmp_path, studio):
    studio.frozen_takes = 1
    job = make_job(tmp_path, beats=[_moving_beat()])
    assets.run(job)
    for take in _shot(job)["takes"]:
        assert (job.work / take["file"]).is_file()
        assert take["seed"] and "shot_motion" in take["readings"] and take["sha256"]


def test_the_seed_is_the_same_for_the_same_attempt_and_different_for_the_next():
    assert takes.seed_for("a prompt", 1) == takes.seed_for("a prompt", 1)
    assert takes.seed_for("a prompt", 1) != takes.seed_for("a prompt", 2)


def test_the_piece_uses_the_chosen_take_at_its_usual_path_and_records_its_seed(tmp_path, studio):
    studio.frozen_takes = 1
    job = make_job(tmp_path, beats=[_moving_beat()])
    manifest = assets.run(job)
    asset = next(a for a in manifest["assets"] if a["id"] == "b1.video")
    chosen = _shot(job)["takes"][1]
    assert asset["path"] == "beats/b1.video.mp4"
    assert asset["provenance"]["seed"] == chosen["seed"]
    assert publish.sha256_file(job.work / asset["path"]) == chosen["sha256"]


def test_a_persons_choice_stands_against_a_better_reading(tmp_path, studio):
    studio.frozen_takes = 1
    job = make_job(tmp_path, beats=[_moving_beat()])
    assets.run(job)
    takes.choose(job, "b1", 0)
    shotmake.apply_chosen(job, "b1")
    shotmake.retake(job, "b1")
    shot = _shot(job)
    assert shot["chosen"] == 0 and shot["chosen_by"] == "human" and len(shot["takes"]) == 3


def test_choosing_a_take_that_does_not_exist_is_refused(tmp_path, studio):
    job = make_job(tmp_path, beats=[_moving_beat()])
    assets.run(job)
    with pytest.raises(ContractError, match="no take 7"):
        takes.choose(job, "b1", 7)
    with pytest.raises(ContractError, match="no takes of b9"):
        takes.choose(job, "b9", 0)


def test_a_retake_with_a_note_says_it_to_the_model_and_touches_no_other_shot(tmp_path, studio):
    beats = [_moving_beat(), _moving_beat(id="b2", role="body")]
    job = make_job(tmp_path, beats=beats)
    assets.run(job)
    other = publish.sha256_file(job.work / "beats" / "b2.video.mp4")
    studio.calls.clear()
    shotmake.retake(job, "b1", "The water must keep moving.")
    assert [c["capability"] for c in studio.calls] == ["video"]
    assert "The water must keep moving." in studio.calls[0]["prompt"]
    assert publish.sha256_file(job.work / "beats" / "b2.video.mp4") == other
    assert _shot(job)["takes"][-1]["note"] == "The water must keep moving."


def test_a_retake_that_reads_well_is_used_because_a_person_saw_what_a_reading_cannot(
    tmp_path, studio
):
    job = make_job(tmp_path, beats=[_moving_beat()])
    assets.run(job)
    assert _shot(job)["chosen"] == 0
    take = shotmake.retake(job, "b1", "The light is wrong.")
    assert take["n"] == 1 and _shot(job)["chosen"] == 1
    assert _shot(job)["chosen_by"] == "reading", "only a person's own choice is marked as theirs"


def test_a_retake_that_comes_back_frozen_is_not_used(tmp_path, studio):
    job = make_job(tmp_path, beats=[_moving_beat()])
    assets.run(job)
    studio.frozen_takes = 99
    take = shotmake.retake(job, "b1", "The light is wrong.")
    assert take["n"] == 0 and _shot(job)["chosen"] == 0


def test_a_retake_of_a_shot_the_script_does_not_have_is_refused(tmp_path, studio):
    job = make_job(tmp_path, beats=[_moving_beat()])
    assets.run(job)
    with pytest.raises(ContractError, match="no beat b9"):
        shotmake.retake(job, "b9")


def test_a_new_take_reaches_the_cut(tmp_path, studio):
    job = make_job(tmp_path, beats=[_moving_beat()])
    assets.run(job)
    first = edit.run(job)["asset_manifest_sha256"]
    takes_before = takes.load(job)["shots"]["b1"]["chosen"]
    shotmake.retake(job, "b1")
    assert takes.load(job)["shots"]["b1"]["chosen"] in (takes_before, 1)
    assert edit.run(job)["asset_manifest_sha256"] != first, "the manifest records the new bytes"


# ---- the motion promise -----------------------------------------------------------------
def test_a_shot_that_asked_to_move_stops_the_job_when_it_cannot(tmp_path, studio):
    studio.fail_video = True
    job = make_job(tmp_path, beats=[_moving_beat()])
    with pytest.raises(ContractError, match="asked to move"):
        assets.run(job)


def test_a_person_can_accept_a_still_and_the_record_says_so(tmp_path, studio):
    studio.fail_video = True
    job = make_job(
        tmp_path,
        beats=[_moving_beat()],
        brief={"subject": "a test", "max_video_beats": 9, "allow_stills": True},
    )
    manifest = assets.run(job)
    assert manifest["promise_breaks"][0]["beat_id"] == "b1"
    assert "b1.video" not in {a["id"] for a in manifest["assets"]}


def test_a_broken_promise_fails_qa_and_cannot_be_approved(tmp_path, studio):
    job = make_job(tmp_path, beats=[_moving_beat()])
    manifest = assets.run(job)
    manifest["promise_breaks"] = [{"beat_id": "b1", "reason": "the model was down"}]
    job.write("asset_manifest", manifest)
    edit.run(job)
    render.compile_plan(job)
    render.execute(job)
    report = qa.run(job)
    assert "delivery.motion_promise" in {c["id"] for c in report["checks"] if c["status"] == "fail"}
    assert not report["passed"]


def test_more_moving_shots_than_the_budget_is_refused_before_any_call(tmp_path, studio):
    job = make_job(
        tmp_path,
        beats=[_moving_beat(), _moving_beat(id="b2", role="body")],
        brief={"subject": "a test", "max_video_beats": 1},
    )
    with pytest.raises(ContractError, match="budget"):
        assets.run(job)
    assert studio.calls == []


# ---- continuity across shots ------------------------------------------------------------
def test_a_shot_that_continues_starts_from_the_last_frame_of_the_one_before(tmp_path, studio):
    beats = [_moving_beat(), _moving_beat(id="b2", role="body", continues=True)]
    job = make_job(tmp_path, beats=beats)
    manifest = assets.run(job)
    still = next(a for a in manifest["assets"] if a["id"] == "b2.still")
    assert still["provider"] == "chained"
    assert still["provenance"]["chained_from"] == "b1.video.mp4"
    assert sum(1 for c in studio.calls if c["capability"] == "image") == 1, "no second still"
    assert (job.work / "beats" / "b2.still.png").is_file()


def test_a_clip_is_told_what_moves_and_a_still_what_things_look_like(tmp_path, studio):
    shot = {"first_frame": "He stands at the glass.", "action": "He wipes the pane"}
    job = make_job(tmp_path, beats=[_moving_beat(shot=shot)])
    assets.run(job)
    still = next(c for c in studio.calls if c["capability"] == "image")
    clip = next(c for c in studio.calls if c["capability"] == "video")
    assert "He stands at the glass" in still["prompt"]
    assert "He wipes the pane" in clip["prompt"] and "He stands" not in clip["prompt"]


# ---- sound and speech -------------------------------------------------------------------
def test_a_line_said_on_camera_is_lip_synced_to_its_own_voice(tmp_path, studio):
    job = make_job(tmp_path, beats=[_moving_beat(on_camera=True, speaker="her")])
    manifest = assets.run(job)
    sync = next(c for c in studio.calls if c["capability"] == "lipsync")
    assert sync["audio"].name.startswith(".") or "b1.voice" in sync["audio"].name
    asset = next(a for a in manifest["assets"] if a["id"] == "b1.video")
    assert asset["provenance"]["lipsync_model"] == "fake-lipsync"


def test_a_place_with_an_ambience_cue_gets_its_own_sound_in_the_mix(tmp_path, studio):
    job = make_job(tmp_path, beats=[_moving_beat(ambience="wind and heavy surf")])
    assets.run(job)
    em = edit.run(job)
    assert em["audio"]["ambience"][0]["asset_id"] == "b1.ambience"
    render.compile_plan(job)
    render.execute(job)
    assert media.duration(job.work / "effects.stem.wav") > 0
    assert media.duration(job.work / "me.stem.wav") > 0, "music and effects, for a foreign version"


def test_a_composition_is_rendered_as_a_shot_and_not_generated(tmp_path, studio):
    job = make_job(tmp_path, beats=[_moving_beat(graphics="chart")])
    (job.folder / "chart").mkdir()
    manifest = assets.run(job)
    assert sum(1 for c in studio.calls if c["capability"] == "video") == 0
    asset = next(a for a in manifest["assets"] if a["id"] == "b1.video")
    assert asset["model"] == "fake-graphics" and asset["synthetic"] is False


def test_a_composition_outside_the_job_is_refused(tmp_path, studio):
    job = make_job(tmp_path, beats=[_moving_beat(graphics="../../elsewhere")])
    with pytest.raises(ContractError, match="no composition"):
        assets.run(job)
