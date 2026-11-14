"""A rough cut before the money, a gate on video until a person has watched it, and a look sheet."""

from __future__ import annotations

import json

import pytest
from fakes import Studio, make_job, needs_ffmpeg
from kit_fixtures import Stub, make_character
from PIL import Image

from kalainova import assets, kits, lookdev, preproduction, publish, verdicts
from kalainova.blobstore import sha256_file
from kalainova.jobfs import ContractError
from kalainova.providers import base


def _beat(i, **extra):
    return {
        "id": f"b{i}",
        "role": "body",
        "text": "A line of words to say.",
        "visual_kind": "video",
        "visual_cue": f"Shot number {i} rolling",
        **extra,
    }


class Priced(base.Provider):
    name = "priced-video"
    capabilities = ("video",)

    def estimate(self, capability, **request):
        return 4.0


def _calls(studio, capability):
    return [c for c in studio.calls if c["capability"] == capability]


def _job(tmp_path, **extra):
    return make_job(tmp_path, beats=[_beat(1), _beat(2), _beat(3)], **extra)


def _make(job):
    made = assets.run(job, animatic=True)
    return made, preproduction.write_record(job, made, preproduction.render(job, made))


@needs_ffmpeg
def test_an_animatic_makes_no_video_call_and_no_manifest(tmp_path, studio):
    job = _job(tmp_path)
    made, record = _make(job)
    assert _calls(studio, "video") == []
    assert len(_calls(studio, "image")) == 3
    assert not job.has("asset_manifest")
    assert (job.work / "animatic.mp4").is_file()
    assert record["is_animatic"] is True and record["file"] == "animatic.mp4"
    assert [s["moves"] for s in record["shots"]] == [True, True, True]
    assert job.read("animatic")["sha256"] == sha256_file(job.work / "animatic.mp4")
    assert made["total"] == pytest.approx(record["duration_sec"], abs=0.5)


@needs_ffmpeg
def test_an_animatic_is_refused_by_approve(tmp_path, studio):
    job = _job(tmp_path)
    _make(job)
    (job.work / "final.mp4").write_bytes((job.work / "animatic.mp4").read_bytes())
    with pytest.raises(ContractError, match="animatic"):
        publish.approve(job, "a person", platforms=["x"])
    assert not job.has("approval")


@needs_ffmpeg
def test_a_file_named_as_an_animatic_is_never_the_artifact(tmp_path, studio):
    job = _job(tmp_path)
    final = job.work / "animatic-copy.mp4"
    final.write_bytes(b"not a real file")
    with pytest.raises(ContractError, match="animatic"):
        preproduction.refuse_animatic(job, final)


@needs_ffmpeg
def test_the_printed_cost_is_the_sum_of_the_shots(tmp_path, studio, monkeypatch):
    monkeypatch.setitem(base._REGISTRY, "priced-video", Priced)
    job = _job(
        tmp_path,
        cost_cap=100.0,
        providers={"video": ["priced-video"], "image": ["fake"], "voice": ["fake"]},
    )
    _, record = _make(job)
    prices = [s["estimate_usd"] for s in record["shots"]]
    assert prices == [4.0, 4.0, 4.0]
    assert record["video_estimate_usd"] == sum(prices) == 12.0
    lines = preproduction.cost_lines(record, 100.0, job.committed())
    assert "about $12.00" in lines[0] and len(lines) == 4
    assert studio.calls and _calls(studio, "video") == []


@needs_ffmpeg
def test_the_printed_cost_says_when_it_is_over_the_cap(tmp_path, studio, monkeypatch):
    monkeypatch.setitem(base._REGISTRY, "priced-video", Priced)
    job = _job(
        tmp_path,
        cost_cap=10.0,
        providers={"video": ["priced-video"], "image": ["fake"], "voice": ["fake"]},
    )
    _, record = _make(job)  # a rough cut is made, and says what the video would cost
    assert "OVER THE CAP" in preproduction.cost_lines(record, 10.0, job.committed())[0]


@needs_ffmpeg
def test_the_gate_holds_video_until_the_animatic_is_accepted(tmp_path, studio):
    job = _job(tmp_path, brief={"subject": "a test", "max_video_beats": 9, "animatic_gate": True})
    with pytest.raises(ContractError, match="kalainova animatic"):
        assets.run(job)
    assert studio.calls == []
    _make(job)
    with pytest.raises(ContractError, match="no verdict"):
        assets.run(job)
    verdicts.record(job, "fix", reviewer="a person", animatic=True)
    with pytest.raises(ContractError, match="judged fix"):
        assets.run(job)
    assert _calls(studio, "video") == []
    verdicts.record(job, "accept", reviewer="a person", animatic=True)
    assets.run(job)
    assert len(_calls(studio, "video")) == 3
    assert job.job["animatic_reviewed"]["verdict"] == "accept"


@needs_ffmpeg
def test_an_accept_does_not_carry_over_to_a_different_cut(tmp_path, studio):
    job = _job(tmp_path, brief={"subject": "a test", "max_video_beats": 9, "animatic_gate": True})
    _make(job)
    verdicts.record(job, "accept", reviewer="a person", animatic=True)
    other = job.read("animatic")
    other["sha256"] = "0" * 64  # the rough cut was made again, and is not the one that was watched
    job.write("animatic", other)
    with pytest.raises(ContractError, match="made again"):
        assets.run(job)


@needs_ffmpeg
def test_a_job_without_the_gate_behaves_as_before(tmp_path, studio):
    job = _job(tmp_path)
    assets.run(job)
    assert len(_calls(studio, "video")) == 3


@needs_ffmpeg
def test_the_full_run_reuses_the_animatics_stills_at_no_new_charge(tmp_path, studio):
    job = _job(tmp_path)
    _make(job)
    stills = len(_calls(studio, "image"))
    voices = len(_calls(studio, "voice"))
    assets.run(job)
    assert len(_calls(studio, "image")) == stills
    assert len(_calls(studio, "voice")) == voices
    assert len(_calls(studio, "video")) == 3
    assert job.committed() == 0.0


def test_a_verdict_on_the_animatic_needs_one(tmp_path):
    job = make_job(tmp_path, beats=[_beat(1)])
    with pytest.raises(ContractError, match="no animatic"):
        verdicts.record(job, "accept", reviewer="a person", animatic=True)
    with pytest.raises(ContractError, match="whole rough cut"):
        verdicts.record(job, "accept", reviewer="a person", animatic=True, shot="b1")


@needs_ffmpeg
def test_an_animatic_verdict_is_not_a_sample_of_the_bar(tmp_path, studio):
    job = _job(tmp_path)
    _make(job)
    verdicts.record(job, "accept", reviewer="a person", animatic=True)
    assert json.loads((job.folder / "verdicts.jsonl").read_text())["stage"] == "animatic"
    assert verdicts.samples(tmp_path / "jobs") == []


# ------------------------------------------------------------------ look development
def _kit_bytes(root, kit_id):
    return {p: p.read_bytes() for p in (root / "kits" / kit_id).rglob("*.json")}


def test_a_look_sheet_is_written_and_no_kit_file_changes(root):
    make_character(root)
    before = _kit_bytes(root, "lead")
    out = lookdev.sheet(root, "lead", root / "out" / "look-lead" / "look-sheet.jpg")
    assert out.is_file() and out.stat().st_size > 0
    assert _kit_bytes(root, "lead") == before
    assert kits.versions(root, "lead") == [1]


def test_a_look_sheet_reads_a_draft_and_leaves_it_alone(root):
    make_character(root)
    kits.bump(root, "lead")
    before = _kit_bytes(root, "lead")
    lookdev.sheet(root, "lead", root / "sheet.jpg")
    assert _kit_bytes(root, "lead") == before
    assert kits.versions(root, "lead") == [1]


def test_test_stills_are_one_per_look_under_a_cap(root, monkeypatch):
    def picture(self, prompt, dst, *, width, height, **kw):
        Stub.calls.append({"capability": "image", "prompt": prompt, **kw})
        Image.linear_gradient("L").resize((width, height)).convert("RGB").save(dst, format="PNG")
        return base.Result(path=dst, model=kw.get("model") or "stub-plain")

    monkeypatch.setattr(Stub, "image", picture)
    make_character(root)
    made = lookdev.make_test_stills(root, "lead", cost_cap=1.0, provider="stub", model="img-ref")
    assert [name for name, _ in made] == ["office"]
    assert all(path.is_file() for _, path in made)
    sent = [c for c in Stub.calls if c["capability"] == "image"]
    assert len(sent) == 1 and sent[0]["references"] and sent[0]["model"] == "img-ref"
    sheet = lookdev.sheet(root, "lead", root / "sheet.jpg", stills=made)
    assert sheet.is_file()
    assert json.loads((root / "jobs" / "look-lead" / "job.json").read_text())["cost_cap"] == 1.0


def test_test_stills_need_a_model_that_holds_a_face(root, studio):
    make_character(root)
    with pytest.raises(ContractError, match="takes no reference images"):
        lookdev.make_test_stills(root, "lead", cost_cap=1.0, provider="fake", model="x")


def test_a_missing_frozen_kit_points_at_the_look_step(root):
    kits.new(root, "lead")
    with pytest.raises(ContractError, match="kalainova look lead"):
        kits.load(root, "lead", 1)


@needs_ffmpeg
def test_the_animatic_command_prints_the_file_and_the_cost(tmp_path, studio, capsys):
    from kalainova.__main__ import main

    job = _job(tmp_path)
    assert main(["animatic", str(job.folder)]) == 0
    out = capsys.readouterr().out
    assert "animatic.mp4" in out and "video still to pay for" in out
    assert "verdict" in out and "--animatic" in out
    assert main(["verdict", str(job.folder), "accept", "--animatic", "--reviewer", "a person"]) == 0
    assert job.job["animatic_reviewed"]["reviewer"] == "a person"


def test_the_look_command_writes_a_sheet_and_leaves_the_kit_be(root, capsys):
    from kalainova.__main__ import main

    make_character(root)
    before = _kit_bytes(root, "lead")
    assert main(["look", "lead"]) == 0
    assert "look-sheet.jpg" in capsys.readouterr().out
    assert _kit_bytes(root, "lead") == before


def test_test_stills_through_the_command_need_a_model_and_a_cap(root):
    from kalainova.__main__ import main

    make_character(root)
    assert main(["look", "lead", "--stills"]) == 1


class PaidVideoStudio(Studio):
    name = "paid-video"
    capabilities = ("video",)
    free = False

    def estimate(self, capability, **request):
        return 2.0


@needs_ffmpeg
def test_capped_job_with_paid_video_provider_stops_until_animatic_accepted(
    tmp_path, studio, monkeypatch
):
    monkeypatch.setitem(base._REGISTRY, "paid-video", PaidVideoStudio)
    from fakes import EVERY

    job = _job(
        tmp_path,
        cost_cap=50.0,
        providers={c: ["fake"] for c in EVERY} | {"video": ["paid-video"]},
    )
    with pytest.raises(ContractError, match="holds video until its animatic is accepted"):
        assets.run(job)
    assert _calls(PaidVideoStudio, "video") == []
    _make(job)
    with pytest.raises(ContractError, match="no verdict"):
        assets.run(job)
    verdicts.record(job, "accept", reviewer="a person", animatic=True)
    assets.run(job)
    assert len(_calls(PaidVideoStudio, "video")) == 3


@needs_ffmpeg
def test_changing_one_still_makes_that_shot_refuse_and_others_run(tmp_path, studio):
    job = _job(tmp_path, brief={"subject": "a test", "max_video_beats": 9, "animatic_gate": True})
    _make(job)
    verdicts.record(job, "accept", reviewer="a person", animatic=True)
    b2_still = job.work / "beats" / "b2.still.png"
    Image.new("RGB", (64, 64), color="red").save(b2_still)

    manifest = assets.run(job)
    video_calls = _calls(studio, "video")
    assert len(video_calls) == 2
    assert any(b["beat_id"] == "b2" for b in manifest.get("promise_breaks", []))


@needs_ffmpeg
def test_changing_still_on_still_only_shot_refuses(tmp_path, studio):
    job = make_job(
        tmp_path,
        beats=[_beat(1, visual_kind="still"), _beat(2, visual_kind="still")],
        brief={"subject": "a test", "animatic_gate": True},
    )
    _make(job)
    verdicts.record(job, "accept", reviewer="a person", animatic=True)
    b1_still = job.work / "beats" / "b1.still.png"
    Image.new("RGB", (64, 64), color="blue").save(b1_still)
    with pytest.raises(ContractError, match="b1: still does not match accepted animatic still"):
        assets.run(job)


@needs_ffmpeg
def test_job_on_free_providers_runs_straight_through_as_today(tmp_path, studio):
    assert studio.free is True
    job = _job(tmp_path, cost_cap=50.0)
    assets.run(job)
    assert len(_calls(studio, "video")) == 3


@needs_ffmpeg
def test_animatic_gate_false_in_brief_turns_gate_off_and_shows_in_job_record(
    tmp_path, studio, monkeypatch
):
    monkeypatch.setitem(base._REGISTRY, "paid-video", PaidVideoStudio)
    from fakes import EVERY

    job = _job(
        tmp_path,
        cost_cap=50.0,
        providers={c: ["fake"] for c in EVERY} | {"video": ["paid-video"]},
        brief={"subject": "test", "animatic_gate": False},
    )
    assets.run(job)
    assert len(_calls(PaidVideoStudio, "video")) == 3
    assert job.job["brief"]["animatic_gate"] is False


@needs_ffmpeg
def test_status_command_shows_which_gate_a_job_is_waiting_at(tmp_path, studio, monkeypatch, capsys):
    from fakes import EVERY

    from kalainova.__main__ import main

    monkeypatch.setitem(base._REGISTRY, "paid-video", PaidVideoStudio)
    job = _job(
        tmp_path,
        cost_cap=50.0,
        providers={c: ["fake"] for c in EVERY} | {"video": ["paid-video"]},
    )
    assert main(["status", str(job.folder)]) == 0
    out = capsys.readouterr().out
    assert "gate=animatic" in out or "waiting at gate: animatic" in out

    _make(job)
    verdicts.record(job, "accept", reviewer="someone", animatic=True)
    assert main(["status", str(job.folder)]) == 0
    out2 = capsys.readouterr().out
    assert "gate=animatic" not in out2


def test_missing_accepted_animatic_still_raises_contract_error(tmp_path, studio):
    job = _job(tmp_path, cost_cap=50.0)
    _make(job)
    verdicts.record(job, "accept", reviewer="someone", animatic=True)
    (job.work / "beats" / "b1.still.png").unlink()
    with pytest.raises(ContractError, match="b1: accepted animatic still is missing from disk"):
        assets.run(job)


def test_refuse_shot_still_exempts_continuation_beats(tmp_path, studio):
    job = _job(tmp_path, cost_cap=50.0)
    _make(job)
    verdicts.record(job, "accept", reviewer="someone", animatic=True)
    still = job.work / "beats" / "b1.still.png"
    # Overwrite still with different data
    still.write_bytes(b"altered-frame-content")
    # A standard beat fails the check
    assert preproduction.refuse_shot_still(job, "b1", still) is not None
    assert preproduction.refuse_shot_still(job, {"id": "b1"}, still) is not None
    # A chained/continuation beat is exempt
    assert preproduction.refuse_shot_still(job, {"id": "b1", "continues": True}, still) is None
