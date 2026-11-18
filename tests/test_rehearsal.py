"""A rehearsal writes down every paid request and its price, and sends and spends nothing."""

from __future__ import annotations

import json

import pytest
import requests
from fakes import context, make_job, needs_ffmpeg

from kalainova import assets, config, media, rehearse
from kalainova.jobfs import ContractError
from kalainova.providers import base, fal, rehearsal
from kalainova.providers.contract import MusicRequest, Reference, VideoRequest

pytestmark = needs_ffmpeg

SCHEMA_OK = lambda provider, model, payload: []  # noqa: E731 - the live schema is read in its own test

BEAT = {
    "id": "b1",
    "role": "hook",
    "text": "A line.",
    "visual_kind": "video",
    "visual_cue": "Waves rolling in",
}


@pytest.fixture
def offline(monkeypatch):
    """Any request to a vendor fails the test."""

    def sent(*a, **kw):
        raise AssertionError("a rehearsal reached the network")

    for verb in ("get", "post", "put"):
        monkeypatch.setattr(requests, verb, sent)


def _job(tmp_path, video):
    providers = {c: ["fake"] for c in ("voice", "image", "music", "sfx", "transcribe", "graphics")}
    return make_job(
        tmp_path,
        beats=[dict(BEAT)],
        cost_cap=5.0,
        brief={"subject": "a test", "max_video_beats": 9, "animatic_gate": True},
        providers={**providers, "video": video},
    )


def test_a_rehearsal_names_each_field_and_price_and_spends_nothing(tmp_path, studio, offline):
    job = _job(tmp_path, ["fal"])
    report = rehearse.run(job, check=SCHEMA_OK)

    assert report["stopped"] == ""
    (call,) = [c for c in report["calls"] if c["capability"] == "video"]
    assert call["provider"] == "fal" and call["estimate"] > 0
    (sent,) = call["requests"]
    field = config.video_spec("fal", sent["model"]).get("image_param", "image_url")
    assert sent["payload"][field].startswith(rehearsal.SCHEME + "upload/b1.still.png")
    assert report["shots"]["b1"][0]["start_frame_sent"] is True
    # every paid call the real run makes is priced, the still's check by a judge among them
    others = [c for c in report["calls"] if c["capability"] != "video"]
    assert {c["capability"] for c in others} <= {"judge", "llm"}
    assert report["estimate_total"] == pytest.approx(sum(c["estimate"] for c in report["calls"]))
    assert "only" in report["animatic_gate"]  # the gate was passed in the copy, and it says so

    assert job.committed() == 0
    assert not (job.folder / "ledger.json").exists()
    assert not (job.work / "takes").exists()
    assert not (tmp_path / "out" / f"{job.id}-rehearsal").exists()
    assert json.loads((job.work / rehearse.REPORT).read_text())["calls"]


def test_the_real_run_still_waits_for_the_animatic(tmp_path, studio, offline):
    job = _job(tmp_path, ["fal"])
    rehearse.run(job, check=SCHEMA_OK)
    with pytest.raises(ContractError, match="animatic"):
        assets.run(job)


class Paid(base.Provider):
    """A model that costs money and has no way to rehearse."""

    name = "paid"
    capabilities = ("video",)
    calls = 0

    def estimate(self, billable, model=None):
        return 0.5

    def video(self, req, ctx):
        Paid.calls += 1
        raise AssertionError("a rehearsal called a paid model")


def test_a_paid_model_that_cannot_rehearse_stops_it(tmp_path, studio, offline, monkeypatch):
    monkeypatch.setitem(base._REGISTRY, "paid", Paid)
    Paid.calls = 0
    report = rehearse.run(_job(tmp_path, ["paid"]))
    assert "paid is listed first for video and cannot rehearse" in report["stopped"]
    assert Paid.calls == 0
    assert any("would stop" in line for line in rehearse.lines(report))


class Keyed(Paid):
    """The same, with a key this machine does not have."""

    name = "keyed"
    env_key = "KEYED_TEST_KEY"


def test_a_keyless_paid_model_listed_first_stops_it(tmp_path, studio, offline, monkeypatch):
    # With its key set, the real run would call it; the rehearsal must not show fal's route instead
    monkeypatch.setitem(base._REGISTRY, "keyed", Keyed)
    monkeypatch.delenv("KEYED_TEST_KEY", raising=False)
    Paid.calls = 0
    report = rehearse.run(_job(tmp_path, ["keyed", "fal"]))
    assert "keyed is listed first for video and cannot rehearse" in report["stopped"]
    assert Paid.calls == 0
    assert not [c for c in report["calls"] if c["capability"] == "video"]


def test_a_request_is_paired_with_its_call_by_the_attempt(tmp_path, offline):
    # fal brings audio down as .src and converts it; the request still belongs to the router's call
    dst = tmp_path / ".1a2b3c4d.music.wav"
    asked = MusicRequest(prompt="a warm bed", dst=dst, duration=6)
    with rehearsal.opened() as dry:
        dry.begin("1a2b3c4d", asked, "fal", 0.04, "music")
        fal.Fal().music(asked, context(attempt="1a2b3c4d"))
    (call,) = dry.report()
    assert call["requests"][0]["model"] == config.model_for("fal", "music")
    assert not dry.loose
    assert media.duration(dst) == pytest.approx(6, abs=0.2)  # the length the engine asked for


def test_fal_writes_down_the_start_frame_and_the_references(tmp_path, offline, monkeypatch):
    model = "fal-ai/kling-video/o3/pro/reference-to-video"
    still, face = tmp_path / "still.png", tmp_path / "face.png"
    for path in (still, face):
        media.run(["-f", "lavfi", "-i", "testsrc2=size=360x640", "-frames:v", "1", str(path)])
    refs = (Reference(path=face, sha256="a", label="the lead's face"),)
    asked = VideoRequest(
        prompt="she plays the drop",
        dst=tmp_path / "clip.mp4",
        duration=5,
        aspect="9:16",
        start=still,
        references=refs,
    )
    with rehearsal.opened() as dry:
        assert not fal.Fal().missing_env()  # no key is needed to send nothing
        made = fal.Fal().video(asked, context(model=model))
    (sent,) = dry.loose  # no router opened this call, so it is kept apart
    assert sent["model"] == model
    assert sent["payload"]["start_image_url"].startswith(rehearsal.SCHEME + "upload/still.png")
    assert media.duration(made.path) == pytest.approx(5, abs=0.2)
    assert made.sent is not None and made.sent.start_frame is True
    assert fal.Fal().missing_env() == ["FAL_KEY"]  # closed again


def test_only_one_rehearsal_runs_at_a_time():
    with rehearsal.opened(), pytest.raises(RuntimeError), rehearsal.opened():
        pass
    assert rehearsal.active() is None


def test_a_field_fal_would_refuse_stops_the_rehearsal(tmp_path, studio, offline):
    # The schema check runs on every rehearsal, so nobody has to remember a script
    def refuse(provider, model, payload):
        return [f"not in {model}'s schema: ['tail_image_url']"] if "video" in model else []

    report = rehearse.run(_job(tmp_path, ["fal"]), check=refuse)
    assert report["stopped"].startswith("the vendor would refuse: request")
    assert "tail_image_url" in report["stopped"]
    (call,) = [c for c in report["calls"] if c["capability"] == "video"]
    assert call["requests"][0]["schema"] != "ok"
    assert any("SCHEMA REFUSES" in line for line in rehearse.lines(report))


def test_a_bench_that_has_its_still_rehearses_only_the_bench(tmp_path, studio, offline):
    job = _job(tmp_path, ["fal"])
    assets.run(job, animatic=True)  # the still, made free by the fake image provider
    packet = job.read("script_packet")
    packet["beats"][0]["duration_sec"] = 3.0  # and its length, from the plan
    job.write("script_packet", packet)
    model = next(iter(config.studio()["video_models"]["fal"]))
    report = rehearse.run(job, check=SCHEMA_OK, bench=("b1", [model]))
    assert report["stopped"] == ""
    assert report["calls"] and {c["capability"] for c in report["calls"]} == {"video"}, (
        "the bench starts from the still it has, so no still is priced"
    )
