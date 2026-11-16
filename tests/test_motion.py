"""Motion transfer uses the regular provider contract, router, and cost estimate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fakes import Wire, context

from kalainova import config, media, trace
from kalainova.jobfs import Job
from kalainova.providers import base, fal, local, mac, router
from kalainova.providers.contract import Billable, MotionRequest


class MotionProvider(base.Provider):
    name = "motion-test"
    capabilities = ("motion",)
    free = True
    seen: tuple[Path, Path] | None = None

    def motion(self, req, ctx):
        type(self).seen = (req.character, req.driving)
        media.run(["-f", "lavfi", "-i", "testsrc2=s=64x64:d=1:r=8", str(req.dst)])
        return base.Result(path=req.dst, model="motion-test")


def _job(tmp_path: Path, provider: str) -> Job:
    folder = tmp_path / "jobs" / "motion"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(
        json.dumps(
            {
                "schema_version": "0.1",
                "job_id": "motion",
                "strategy": "generated",
                "media": ["video"],
                "rights": "owned",
                "distribution_identity": "test",
                "status": "draft",
                "providers": {"motion": [provider]},
            }
        )
    )
    return Job(folder)


def test_motion_routes_to_a_listed_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    monkeypatch.setitem(base._REGISTRY, MotionProvider.name, MotionProvider)
    job = _job(tmp_path, MotionProvider.name)
    character = job.work / "character.png"
    driving = job.work / "driving.mp4"
    character.write_bytes(b"character")
    media.run(["-f", "lavfi", "-i", "testsrc2=s=64x64:d=1:r=8", str(driving)])

    dst = job.work / "motion.mp4"
    assert router.motion(job, character, driving, dst) == dst
    assert dst.is_file()
    assert MotionProvider.seen == (character, driving)
    assert router.available(job, "motion")
    assert router.first_usable(job, "motion").name == MotionProvider.name
    assert trace.load(job)[0]["capability"] == "motion"


def test_motion_is_a_declared_provider_capability():
    assert "motion" in base.CAPABILITIES
    assert "motion" in fal.Fal.capabilities
    assert "motion" in mac.Mac.capabilities
    assert "motion" in local.LocalProvider.capabilities


def test_fal_motion_estimate_uses_the_fixed_price():
    assert config.price_for("fal", "motion")["cost_usd"] == pytest.approx(0.02)
    assert config.estimate("fal", "motion") == pytest.approx(0.02)
    assert fal.Fal().estimate(Billable(capability="motion")) == pytest.approx(0.02)


def test_fal_motion_sends_both_inputs_and_fetches_the_video(monkeypatch, tmp_path):
    fetched = []

    class Clips(Wire):
        def _upload(self, path):
            return f"https://example.test/{path.name}"

        def _download(self, url, dst):
            fetched.append((url, dst))
            Path(dst).write_bytes(b"clip")

    wire = Clips(default={"video": {"url": "https://example.test/result.mp4"}})
    monkeypatch.setattr(fal.Fal, "transport", wire)
    character = tmp_path / "character.png"
    driving = tmp_path / "driving.mp4"
    dst = tmp_path / "result.mp4"

    asked = MotionRequest(character=character, driving=driving, dst=dst)
    result = fal.Fal().motion(asked, context())

    assert wire.sent[-1]["endpoint"] == "fal-ai/live-portrait"
    assert wire.payloads[-1] == {
        "image_url": "https://example.test/character.png",
        "video_url": "https://example.test/driving.mp4",
    }
    assert fetched == [("https://example.test/result.mp4", dst)]
    assert result.path == dst
    assert result.cost == pytest.approx(0.02)
