"""A rehearsal writes down every paid request and its price, and sends and spends nothing."""

from __future__ import annotations

import json

import pytest
import requests
from fakes import make_job, needs_ffmpeg

from kalainova import assets, config, media, rehearse
from kalainova.jobfs import ContractError
from kalainova.providers import base, fal, rehearsal

pytestmark = needs_ffmpeg

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
    report = rehearse.run(job)

    assert report["stopped"] == ""
    (call,) = [c for c in report["calls"] if c["capability"] == "video"]
    assert call["provider"] == "fal" and call["estimate"] > 0
    (sent,) = call["requests"]
    field = config.video_spec("fal", sent["model"]).get("image_param", "image_url")
    assert sent["payload"][field].startswith(rehearsal.SCHEME + "upload/b1.still.png")
    assert report["shots"]["b1"][0]["start_frame_sent"] is True
    assert report["estimate_total"] == pytest.approx(call["estimate"])
    assert "only" in report["animatic_gate"]  # the gate was passed in the copy, and it says so

    assert job.committed() == 0
    assert not (job.folder / "ledger.json").exists()
    assert not (job.work / "takes").exists()
    assert not (tmp_path / "out" / f"{job.id}-rehearsal").exists()
    assert json.loads((job.work / rehearse.REPORT).read_text())["calls"]


def test_the_real_run_still_waits_for_the_animatic(tmp_path, studio, offline):
    job = _job(tmp_path, ["fal"])
    rehearse.run(job)
    with pytest.raises(ContractError, match="animatic"):
        assets.run(job)


class Paid(base.Provider):
    """A model that costs money and has no way to rehearse."""

    name = "paid"
    capabilities = ("video",)
    calls = 0

    def estimate(self, capability, **request):
        return 0.5

    def video(self, prompt, dst, *, duration, aspect, image=None, **kw):
        Paid.calls += 1
        raise AssertionError("a rehearsal called a paid model")


def test_a_paid_model_that_cannot_rehearse_stops_it(tmp_path, studio, offline, monkeypatch):
    monkeypatch.setitem(base._REGISTRY, "paid", Paid)
    Paid.calls = 0
    report = rehearse.run(_job(tmp_path, ["paid"]))
    assert "paid cannot rehearse video" in report["stopped"]
    assert Paid.calls == 0
    assert any("would stop" in line for line in rehearse.lines(report))


def test_fal_writes_down_the_start_frame_and_the_references(tmp_path, offline, monkeypatch):
    model = "fal-ai/kling-video/o3/pro/reference-to-video"
    still, face = tmp_path / "still.png", tmp_path / "face.png"
    for path in (still, face):
        media.run(["-f", "lavfi", "-i", "testsrc2=size=360x640", "-frames:v", "1", str(path)])
    refs = [{"path": face, "sha256": "a", "label": "the lead's face", "group": ""}]
    with rehearsal.opened() as dry:
        assert not fal.Fal().missing_env()  # no key is needed to send nothing
        made = fal.Fal().video(
            "she plays the drop",
            tmp_path / "clip.mp4",
            duration=5,
            aspect="9:16",
            image=still,
            references=refs,
            model=model,
        )
    (sent,) = dry.loose  # no router opened this call, so it is kept apart
    assert sent["model"] == model
    assert sent["payload"]["start_image_url"].startswith(rehearsal.SCHEME + "upload/still.png")
    assert media.duration(made.path) == pytest.approx(5, abs=0.2)
    assert made.meta["start_frame_sent"] is True
    assert fal.Fal().missing_env() == ["FAL_KEY"]  # closed again


def test_only_one_rehearsal_runs_at_a_time():
    with rehearsal.opened(), pytest.raises(RuntimeError), rehearsal.opened():
        pass
    assert rehearsal.active() is None
