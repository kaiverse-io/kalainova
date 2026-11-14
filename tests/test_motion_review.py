"""Looking at a piece in motion: strips, the judge's request, findings, retake limits, and the
shot-length ceiling and safe zones that warn before and after a render."""

from __future__ import annotations

import json

import pytest
from fakes import make_job, needs_ffmpeg
from PIL import Image

from kalainova import (
    assets,
    config,
    edit,
    media,
    qa,
    qachecks,
    render,
    shotmake,
    shots,
    takes,
    timeline,
)
from kalainova.jobfs import ContractError
from kalainova.providers import router


def _clip(path, size="320x180", seconds=4.0):
    media.run(
        ["-f", "lavfi", "-i", f"testsrc2=s={size}:d={seconds}:r=24", "-f", "lavfi", "-i",
         f"sine=f=220:d={seconds}:r=48000", "-pix_fmt", "yuv420p", "-shortest", str(path)]
    )  # fmt: skip
    return path


CUTS = [{"id": "cut-b1", "start_sec": 0.0}, {"id": "cut-b2", "start_sec": 2.0}]


def _moving(**extra):
    return {
        "id": "b1",
        "role": "hook",
        "text": "A line.",
        "visual_kind": "video",
        "visual_cue": "Waves rolling in",
        **extra,
    }


# ---- the strips ---------------------------------------------------------------------------
def test_frame_times_are_in_order_and_inside_the_shot():
    times = timeline.frame_times(2.0, 6.0, 7)
    assert len(times) == 7 and times == sorted(times)
    assert times[0] > 2.0 and times[-1] < 6.0


@needs_ffmpeg
def test_a_motion_strip_has_the_asked_number_of_frames_for_every_shot(tmp_path):
    out = timeline.motion_sheet(_clip(tmp_path / "c.mp4"), CUTS, 4.0, tmp_path / "m.jpg", frames=5)
    sheet = Image.open(out)
    cell = timeline.MOTION_LANDSCAPE_WIDTH
    assert sheet.width == cell * 5 + 3 * 4, "five frames across"
    assert sheet.height > (sheet.width / 5) * 0.5 * 2 - 1, "and a row for each of two shots"


@needs_ffmpeg
def test_a_cut_strip_has_a_row_for_every_cut_and_shows_what_was_found(tmp_path):
    clip = _clip(tmp_path / "c.mp4")
    report = timeline.cut_report(clip, [*CUTS, {"id": "cut-b3", "start_sec": 3.0}])
    assert len(report) == 2
    out = timeline.cut_sheet(clip, report, tmp_path / "x.jpg")
    sheet = Image.open(out)
    assert sheet.width == timeline.MOTION_LANDSCAPE_WIDTH * 4 + 9 + timeline.CUT_GAP
    assert sheet.height >= 2 * (timeline.MOTION_LANDSCAPE_WIDTH * 9 // 16)


def test_the_strips_of_a_sound_file_are_nothing_rather_than_a_crash(tmp_path):
    tone = tmp_path / "t.wav"
    media.run(["-f", "lavfi", "-i", "sine=f=220:d=1", str(tone)])
    assert timeline.motion_sheet(tone, CUTS, 1.0, tmp_path / "m.jpg") is None
    assert timeline.cut_sheet(tone, [{"at_sec": 0.5}], tmp_path / "c.jpg") is None


# ---- the judge ---------------------------------------------------------------------------
def test_the_rubric_asks_about_motion_and_a_versioned_answer():
    from kalainova import prompts

    text = prompts.load("qa_rubric").format(shape="vertical", script="[]")
    for word in ("warping", "flicker", "action_happened", '"version": 3', "retake_prompt"):
        assert word in text


def test_a_judges_motion_faults_become_findings_a_retake_can_read():
    judge = {
        "shots": [
            {"id": "b1", "moved": True, "geometry_ok": True, "warping": False},
            {
                "id": "b2",
                "moved": True,
                "warping": True,
                "time": 1.0,
                "retake_prompt": "Keep the face still.",
            },
            {"id": "b3", "action_happened": False, "time": 2.0, "note": "nothing happens"},
        ]
    }
    found = qachecks.findings_from_judge("p1", judge)
    assert found and found["source"] == "judge"
    assert [s["id"] for s in found["shots"]] == ["b2", "b3"]
    assert found["shots"][0]["problems"] == ["warping"]
    assert found["shots"][0]["suggested_prompt_change"] == "Keep the face still."
    assert found["shots"][1]["problems"] == ["action_missing"]
    assert qachecks.findings_from_judge("p1", {"shots": [{"id": "b1", "moved": True}]}) is None
    assert qachecks.judged_shots(judge)[0]["status"] == "warn"


@needs_ffmpeg
def test_qa_sends_the_judge_the_motion_strip_and_keeps_its_findings(tmp_path, studio, monkeypatch):
    job = make_job(tmp_path, beats=[_moving(), _moving(id="b2", role="payoff")])
    assets.run(job)
    edit.run(job)
    render.compile_plan(job)
    render.execute(job)
    seen = {}
    reply = {
        "version": 3,
        "policy_risk": "none",
        "verdict": "ship",
        "shots": [
            {
                "id": "b2",
                "flicker": True,
                "time": 0.5,
                "note": "strobing",
                "retake_prompt": "Steady light.",
            }
        ],
    }

    def judged(job_, capability, fn, text, **kw):
        if kw.get("note") == "qa-judge":
            seen.update(kw)
            return None, type("Reply", (), {"text": json.dumps(reply)})
        return real(job_, capability, fn, text, **kw)

    real = router.generate
    monkeypatch.setattr(router, "generate", judged)
    report = qa.run(job)
    assert [p.name for p in seen["images"]] == ["contact.jpg", "motion.jpg"]
    assert report["artifacts"]["motion_strip"] == "motion.jpg"
    assert report["artifacts"]["cut_strip"] == "cuts.jpg"
    assert (job.work / "cuts.jpg").exists()
    assert report["passed"] or all(
        c["status"] != "fail" for c in report["checks"] if "judge" in c["id"]
    )
    found = takes.findings(job)
    assert found["shots"][0]["id"] == "b2" and found["shots"][0]["problems"] == ["flicker"]


def _write_findings(job, **shot):
    entry = {"id": "b1", "problems": ["warping"], "note": "mine", **shot}
    job.write(
        "findings",
        {"schema_version": "0.1", "job_id": job.id, "source": "agent", "shots": [entry]},
    )


def test_an_agents_findings_are_not_overwritten_by_the_judge(tmp_path):
    job = make_job(tmp_path, beats=[_moving()], job_id="find-agent")
    _write_findings(job)
    qa._keep_findings(job, {"shots": [{"id": "b1", "flicker": True}]})
    assert takes.findings(job)["source"] == "agent"


def test_findings_in_the_wrong_shape_are_refused(tmp_path):
    job = make_job(tmp_path, beats=[_moving()], job_id="find-shape")
    with pytest.raises(ContractError):
        _write_findings(job, problems=["sad"])


# ---- the retake --------------------------------------------------------------------------
@needs_ffmpeg
def test_a_retake_with_no_note_reads_the_finding_for_that_shot(tmp_path, studio):
    job = make_job(tmp_path, beats=[_moving()])
    assets.run(job)
    _write_findings(job, suggested_prompt_change="Hold the face steady.")
    studio.calls.clear()
    shotmake.retake(job, "b1")
    assert "Hold the face steady." in studio.calls[0]["prompt"]


@needs_ffmpeg
def test_a_retake_past_the_shot_limit_is_refused_by_the_engine(tmp_path, studio):
    job = make_job(tmp_path, beats=[_moving()])
    assets.run(job)
    per_shot, _ = takes.retake_limits({})
    for _ in range(per_shot):
        shotmake.retake(job, "b1", "again")
    studio.calls.clear()
    with pytest.raises(ContractError, match="limit is"):
        shotmake.retake(job, "b1", "again")
    assert studio.calls == [], "nothing was asked of a model"


@needs_ffmpeg
def test_a_retake_past_the_job_limit_is_refused_and_a_brief_can_raise_it(tmp_path, studio):
    beats = [_moving(), _moving(id="b2", role="body")]
    job = make_job(tmp_path, beats=beats)
    data = job.job
    data["brief"]["max_retakes"] = 1
    job.write("job", data)
    assets.run(job)
    shotmake.retake(job, "b1", "again")
    with pytest.raises(ContractError, match="the job has had 1 retakes"):
        shotmake.retake(job, "b2", "again")
    data["brief"]["max_retakes"] = 2
    job.write("job", data)
    shotmake.retake(job, "b2", "again")


# ---- the shot-length ceiling -------------------------------------------------------------
def _packet(*beats):
    return {"beats": list(beats)}


def test_a_long_shot_with_a_character_warns_and_a_short_one_does_not():
    long_ = _moving(cast=["lead"], duration_sec=5.0)
    short = _moving(id="b2", cast=["lead"], duration_sec=2.5)
    empty = _moving(id="b3", cast=[], duration_sec=9.0)
    found = shots.review(_packet(long_, short, empty), budget=9, character_max_sec=3.2)
    ids = [p for p in found if p["id"] == "plan.character_shot_length"]
    assert len(ids) == 1 and "b1" in ids[0]["detail"] and ids[0]["status"] == "warn"


def test_the_ceiling_comes_from_the_profile_and_a_brief_overrides_it():
    assert shots.character_ceiling({"profile": "short-9x16"}) == 3.2
    assert (
        shots.character_ceiling({"profile": "short-9x16", "brief": {"character_shot_max_sec": 5}})
        == 5
    )
    assert (
        shots.character_ceiling({"profile": "short-9x16", "brief": {"character_shot_max_sec": 0}})
        is None
    )
    assert shots.character_ceiling({"profile": "podcast"}) is None


def test_qa_warns_about_a_long_character_shot_and_never_fails_on_it():
    data = {"profile": "short-9x16", "media": ["video"]}
    found = qachecks.plan_checks(data, _packet(_moving(cast=["lead"], duration_sec=6.0)))
    long_ = [c for c in found if c["id"] == "plan.character_shot_length"]
    assert long_ and long_[0]["status"] == "warn"


def test_a_short_clip_is_priced_at_the_length_the_model_bills():
    from kalainova.providers.fal import Fal

    fal = Fal()
    short = fal.estimate("video", duration=2.0, image=True)
    assert short and short == fal.estimate("video", duration=3.0, image=True)
    assert short < fal.estimate("video", duration=4.0, image=True)


# ---- safe zones --------------------------------------------------------------------------
def _ass(job, ys, height=1920):
    lines = "\n".join(
        f"Dialogue: 2,0:00:00.00,0:00:01.00,Cap,,0,0,0,,{{\\pos(540,{int(height * y)})}}word"
        for y in ys
    )
    (job.work / "captions.ass").parent.mkdir(parents=True, exist_ok=True)
    (job.work / "captions.ass").write_text(
        f"[Script Info]\nPlayResY: {height}\n[Events]\n{lines}\n"
    )


def test_the_vertical_profile_names_where_overlays_leave_room():
    zone = config.safe_zone("short-9x16")
    assert zone["caption_y"] == [0.55, 0.72] and zone["caption_floor"] == 0.75
    assert zone["right_margin"] == 0.15 and zone["face_y"] == [0.15, 0.75]
    assert config.safe_zone("landscape") == {}


def test_burned_text_below_the_band_warns_and_inside_it_passes(tmp_path):
    job = make_job(tmp_path, beats=[_moving()], job_id="zone-text")
    _ass(job, [0.62, 0.8])
    found = qachecks.safe_zone_checks(job, "short-9x16")
    assert found[0]["status"] == "warn" and "0.8" in found[0]["detail"]
    _ass(job, [0.62, 0.7])
    assert qachecks.safe_zone_checks(job, "short-9x16")[0]["status"] == "pass"


def test_a_face_centre_outside_its_band_warns_only_when_one_was_recorded(tmp_path):
    job = make_job(tmp_path, beats=[_moving()], job_id="zone-face")
    (job.work / "face_centres.json").unlink(missing_ok=True)
    (job.work / "captions.ass").unlink(missing_ok=True)
    assert qachecks.safe_zone_checks(job, "short-9x16") == []
    (job.work / "face_centres.json").write_text(
        json.dumps([{"x": 0.5, "y": 0.1}, {"x": 0.5, "y": 0.4}])
    )
    found = qachecks.safe_zone_checks(job, "short-9x16")
    assert found[0]["id"] == "safe_zone.faces" and found[0]["status"] == "warn"


def test_a_profile_with_no_safe_zone_is_not_checked(tmp_path):
    job = make_job(tmp_path, beats=[_moving()], job_id="zone-none")
    _ass(job, [0.95])
    assert qachecks.safe_zone_checks(job, "landscape") == []


def test_studio_captions_sit_inside_the_vertical_band_when_given_it(tmp_path):
    from kalainova import captions

    card = {"text": "hello there", "start_sec": 0.0, "end_sec": 1.0}
    zone = config.safe_zone("short-9x16")
    job = make_job(tmp_path, beats=[_moving()], job_id="zone-default")
    job.work.mkdir(parents=True, exist_ok=True)
    text, _ = captions.studio_captions([card], 1080, 1920, None, zone["caption_y"][1])
    (job.work / "captions.ass").write_text(text)
    found = qachecks.safe_zone_checks(job, "short-9x16")
    assert found[0]["id"] == "safe_zone.captions" and found[0]["status"] == "pass"
    unset, _ = captions.studio_captions([card], 1080, 1920)
    (job.work / "captions.ass").write_text(unset)
    assert qachecks.safe_zone_checks(job, "short-9x16")[0]["status"] == "warn"


def test_the_render_plan_hands_the_vertical_caption_band_to_burned_captions():
    from kalainova.render import _caption_steps

    zone = config.safe_zone("short-9x16")
    prof = {"width": 1080, "height": 1920, "fps": 30, "safe_zone": zone}
    cap = [{"text": "hi", "start_sec": 0.0, "end_sec": 1.0}]
    for style, expect in (("studio", 0.72), ("kinetic", 0.72), ("drawn", None)):
        em = {"profile": prof, "captions": cap, "caption_style": style}
        steps, _ = _caption_steps(em, "picture.mp4")
        assert steps[-1]["args"].get("caption_y") == expect
