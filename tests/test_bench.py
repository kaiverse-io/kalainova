"""A camera test: one shot on several models, with a record of each."""

from __future__ import annotations

import json

import pytest
from fakes import make_job, needs_ffmpeg

from kalainova import assets, bench, config, media, takes, verdicts
from kalainova.jobfs import ContractError
from kalainova.providers import base

pytestmark = needs_ffmpeg

PRICES = {"cam-a": 0.10, "cam-b": 0.50}


class Camera(base.Provider):
    name = "camera"
    capabilities = ("video",)
    calls: list[dict] = []

    def estimate(self, capability, **request):
        return PRICES[request.get("model", "cam-a")] * float(request["duration"])

    def video(self, prompt, dst, *, duration, aspect, image=None, **kw):
        Camera.calls.append({"model": kw.get("model"), "seed": kw.get("seed"), "image": image})
        media.run(
            ["-f", "lavfi", "-i", f"testsrc2=s=320x180:d={duration + 0.5:.2f}:r=24",
             "-pix_fmt", "yuv420p", str(dst)]
        )  # fmt: skip
        cost = PRICES[kw.get("model", "cam-a")] * duration
        return base.Result(
            path=dst, cost=cost, model=kw.get("model", "cam-a"), meta={"seed": kw.get("seed")}
        )


@pytest.fixture
def stage(tmp_path, studio, monkeypatch):
    """A job with its stills made and no clip yet, and two camera models to compare."""
    monkeypatch.setitem(base._REGISTRY, "camera", Camera)
    Camera.calls = []
    real = config.studio()
    patched = {
        **real,
        "video_models": {"camera": {"cam-a": {}, "cam-b": {}}},
        "prices": {**real.get("prices", {}), "camera": {"cam-a": {"per_sec": 0.1}, "cam-b": {}}},
    }
    monkeypatch.setattr(config, "studio", lambda: patched)
    beat = {
        "id": "b1",
        "role": "hook",
        "text": "A line.",
        "visual_kind": "video",
        "visual_cue": "Waves rolling in",
    }
    job = make_job(
        tmp_path,
        beats=[beat],
        cost_cap=5.0,
        brief={"subject": "a test", "max_video_beats": 0, "allow_stills": True},
        providers={"video": ["camera"], "image": ["fake"], "voice": ["fake"]},
    )
    assets.run(job)
    assert studio.calls and not [c for c in studio.calls if c["capability"] == "video"]
    return job


def test_every_model_makes_a_normal_take_with_its_model_seed_and_cost(stage):
    found = bench.run(stage, "b1", ["cam-a", "cam-b"], 1, say=lambda _: None)
    entry = takes.load(stage)["shots"]["b1"]
    assert [t["model"] for t in entry["takes"]] == ["cam-a", "cam-b"]
    assert all(t["bench"] and t["ok"] and t["seed"] >= 0 and t["cost"] > 0 for t in entry["takes"])
    seeds = {t["seed"] for t in entry["takes"]}
    assert len(seeds) == 1, "the same seed on every model, so the model is the difference"
    assert stage.spent() == pytest.approx(sum(t["cost"] for t in entry["takes"]))
    assert found["sheet"].exists()
    assert {c["model"] for c in Camera.calls} == {"cam-a", "cam-b"}


def test_the_estimate_is_said_per_model_and_an_unpriced_model_is_marked(stage):
    said = []
    bench.estimate(stage, "b1", ["cam-a", "cam-b"], 2, say=said.append)
    text = "\n".join(said)
    assert "cam-a: about" in text and "cam-b: about" in text and "bench total" in text
    assert "no price of its own" in text.split("cam-b")[1]
    assert "no price of its own" not in text.split("cam-b")[0]


def test_a_bench_over_the_cap_is_refused_before_any_call(stage):
    cheap = stage.job["cost_cap"]
    with pytest.raises(ContractError, match="estimated at"):
        bench.run(stage, "b1", ["cam-a", "cam-b"], 200, say=lambda _: None)
    assert Camera.calls == []
    assert stage.committed() == 0.0 and cheap == 5.0


def test_a_bench_needs_a_cap(stage):
    data = stage.job
    data["cost_cap"] = None
    (stage.folder / "job.json").write_text(json.dumps(data))
    with pytest.raises(ContractError, match="cost_cap"):
        bench.run(stage, "b1", ["cam-a", "cam-b"], 1, say=lambda _: None)
    assert Camera.calls == []


def test_an_unlisted_model_is_refused(stage):
    with pytest.raises(ContractError, match="not under video_models"):
        bench.run(stage, "b1", ["cam-a", "mystery"], 1, say=lambda _: None)
    assert Camera.calls == []


def test_a_bench_needs_at_least_two_models():
    with pytest.raises(ContractError, match="at least two"):
        bench.parse_models("cam-a")
    assert bench.parse_models("cam-a, cam-b,cam-a") == ["cam-a", "cam-b"]


def test_bench_takes_do_not_displace_or_use_up_the_real_takes(stage, studio):
    bench.run(stage, "b1", ["cam-a", "cam-b"], 2, say=lambda _: None)
    from kalainova import shotmake

    shotmake.retake(stage, "b1")  # a real take, numbered after the four bench takes
    entry = takes.load(stage)["shots"]["b1"]
    real = [t for t in entry["takes"] if not t.get("bench")]
    assert len(real) == 1 and entry["chosen"] == real[0]["n"]
    chosen = takes.make_until_good(
        stage,
        "b1",
        {},
        suffix=".mp4",
        make=lambda seed, dst: pytest.fail("a real take already stands"),
        assess=takes.assess_clip,
    )
    assert chosen["n"] == real[0]["n"]


def test_a_verdict_can_name_a_take(stage):
    bench.run(stage, "b1", ["cam-a", "cam-b"], 1, say=lambda _: None)
    entry = verdicts.record(stage, "accept", reviewer="r", shot="b1", take=1)
    assert entry["take"] == 1
    with pytest.raises(ContractError, match="no take 9"):
        verdicts.record(stage, "fix", reviewer="r", shot="b1", take=9)
    with pytest.raises(ContractError, match="names the shot"):
        verdicts.record(stage, "fix", reviewer="r", take=1)
    points = verdicts._shot_points(stage.folder, "b1", "accept", 1)
    assert "shot.shot_motion" in points


def test_a_models_own_price_row_beats_the_capability_row(monkeypatch):
    table = {"prices": {"fal": {"image_to_video": {"per_sec": 0.28}, "m/x": {"per_sec": 1.0}}}}
    monkeypatch.setattr(config, "studio", lambda: table)
    assert config.price_for("fal", "image_to_video")["per_sec"] == 0.28
    assert config.price_for("fal", "image_to_video", "m/x")["per_sec"] == 1.0
    assert config.price_for("fal", "image_to_video", "m/other")["per_sec"] == 0.28


def test_a_fal_clip_is_estimated_at_the_length_it_is_billed(monkeypatch):
    table = {
        "prices": {"fal": {"image_to_video": {"per_sec": 0.5}, "m/x": {"per_sec": 1.0}}},
        "video_models": {"fal": {"m/x": {"durations": "5,10"}}},
    }
    monkeypatch.setattr(config, "studio", lambda: table)
    fal = base.get("fal")
    assert fal.estimate("video", duration=3.0, image=True, model="m/x") == 5.0
    assert fal.estimate("video", duration=6.0, image=True, model="m/x") == 10.0
