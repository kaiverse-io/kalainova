"""The locked still is a reference clip's first frame when the model has a field for one."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests

from kalainova import config
from kalainova.providers import fal

STARTS_APART = "vendor/refs-and-first-frame"
REFS_ONLY = "vendor/refs-only"
UNSEEDED = "vendor/no-seed"

TABLE = {
    "prices": {"fal": {"reference_to_video": {"per_sec": 0.28}, STARTS_APART: {"per_sec": 0.112}}},
    "reference_models": {
        "fal": {
            "video": {
                STARTS_APART: {
                    "images_param": "image_urls",
                    "max_images": 4,
                    "tag": "@Image{n}",
                    "start_image_param": "start_image_url",
                    "end_image_param": "end_image_url",
                    "durations": "5,10",
                },
                UNSEEDED: {
                    "images_param": "image_urls",
                    "max_images": 4,
                    "tag": "@Image{n}",
                    "takes_seed": False,
                },
                REFS_ONLY: {
                    "images_param": "reference_image_urls",
                    "max_images": 10,
                    "tag": "Image {n}",
                    "durations": "5,10",
                },
            }
        }
    },
}


@pytest.fixture
def sent(monkeypatch):
    """What the adapter posts to fal, with uploads named after the file."""
    monkeypatch.setattr(config, "studio", lambda: TABLE)
    posted: dict = {}

    def run(self, model, payload, timeout=0):
        posted.update(payload, model=model)
        return {"video": {"url": "https://example.invalid/clip.mp4"}}

    monkeypatch.setattr(fal.Fal, "_upload", lambda self, path: f"up:{Path(path).name}")
    monkeypatch.setattr(fal.Fal, "_run", run)
    monkeypatch.setattr(fal.Fal, "_fetch", lambda self, url, dst, cost: None)
    return posted


def clip(model, tmp_path, **kw):
    face = {"path": tmp_path / "face.png", "sha256": "a", "label": "the lead's face", "group": ""}
    return fal.Fal().video(
        "she plays the drop",
        tmp_path / "clip.mp4",
        duration=5,
        aspect="9:16",
        image=tmp_path / "still.png",
        references=[face],
        model=model,
        **kw,
    )


def test_a_model_with_a_first_frame_field_starts_on_the_locked_still(sent, tmp_path):
    result = clip(STARTS_APART, tmp_path, end_image=tmp_path / "last.png")
    assert sent["start_image_url"] == "up:still.png"
    assert sent["end_image_url"] == "up:last.png"
    assert sent["image_urls"] == ["up:face.png"]
    assert result.meta["start_frame_sent"] is True
    assert result.meta["end_frame_sent"] is True


def test_its_own_price_row_bills_it_not_the_capability_rate(sent, tmp_path):
    assert clip(STARTS_APART, tmp_path).cost == pytest.approx(5 * 0.112)


def test_a_model_without_one_says_the_still_was_not_its_first_frame(sent, tmp_path):
    result = clip(REFS_ONLY, tmp_path, end_image=tmp_path / "last.png")
    assert "start_image_url" not in sent
    assert "end_image_url" not in sent
    assert result.meta["start_frame_sent"] is False
    assert result.meta["end_frame_sent"] is False


def test_a_bench_take_says_what_its_model_was_given(monkeypatch):
    from kalainova import bench

    monkeypatch.setattr(config, "studio", lambda: TABLE)
    two = {"references": [{"label": "face"}, {"label": "side"}]}
    assert bench.conditioning("fal", STARTS_APART, two) == "the start frame and 2 kit reference(s)"
    assert bench.conditioning("fal", REFS_ONLY, two) == (
        "2 reference(s), the still among them; no start frame"
    )
    assert bench.conditioning("fal", REFS_ONLY, {}) == "the start frame only"


def test_a_reference_model_with_an_end_field_can_be_given_a_last_frame(monkeypatch):
    monkeypatch.setattr(config, "studio", lambda: TABLE)
    assert fal.Fal().takes_end_image("video", STARTS_APART)
    assert not fal.Fal().takes_end_image("video", REFS_ONLY)


def test_a_model_with_no_seed_field_is_sent_none_and_the_take_says_so(sent, tmp_path):
    result = clip(UNSEEDED, tmp_path, seed=42)
    assert "seed" not in sent
    assert result.meta["seed_sent"] is False and "seed" not in result.meta
    clip(STARTS_APART, tmp_path, seed=42)
    assert sent["seed"] == 42


def test_a_reference_clip_is_priced_at_its_own_rate_and_billed_length(monkeypatch):
    monkeypatch.setattr(config, "studio", lambda: TABLE)
    asked = {"duration": 1.9, "image": True, "references": True}
    assert fal.Fal().estimate("video", model=STARTS_APART, **asked) == pytest.approx(5 * 0.112)


class _Reply:
    def __init__(self, body, status=200, text=""):
        self.body, self.status_code, self.text = body, status, text

    def json(self):
        return self.body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Client Error")


def test_fal_keeps_its_request_id_and_what_a_refusal_said(monkeypatch):
    # The request id is what fal's bill lists; the 422's body names the field it refused
    monkeypatch.setenv("FAL_KEY", "k")
    sub = {"request_id": "req-1", "status_url": "s", "response_url": "r"}
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _Reply(sub))
    said = '{"detail":[{"msg":"Either frontal_image_url and reference_image_urls"}]}'
    replies = {"s": _Reply({"status": "COMPLETED"}), "r": _Reply({}, 422, said)}
    monkeypatch.setattr(requests, "get", lambda url, **kw: replies[url])
    provider = fal.Fal()
    with pytest.raises(requests.HTTPError, match="reference_image_urls"):
        provider._run("some/model", {})
    assert provider.request_id == "req-1"
