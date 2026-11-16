"""The locked still is a reference clip's first frame when the model has a field for one."""

from __future__ import annotations

from pathlib import Path

import pytest
import requests
from fakes import Wire, context

from kalainova import config
from kalainova.providers import fal
from kalainova.providers.contract import Billable, InvalidRequestError, Reference, VideoRequest

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
    wire = Wire(default={"video": {"url": "u"}}, files={"u": b"clip"})
    monkeypatch.setattr(fal.Fal, "transport", wire)
    posted: dict = {}

    class Last(dict):
        def __getitem__(self, key):
            return wire.payloads[-1][key]

        def __contains__(self, key):
            return key in wire.payloads[-1]

    return Last(posted)


def clip(model, tmp_path, **kw):
    face = Reference(path=tmp_path / "face.png", sha256="a", label="the lead's face")
    asked = VideoRequest(
        prompt="she plays the drop",
        dst=tmp_path / "clip.mp4",
        duration=5,
        aspect="9:16",
        start=tmp_path / "still.png",
        references=(face,),
        **kw,
    )
    return fal.Fal().video(asked, context(model=model))


def test_a_model_with_a_first_frame_field_starts_on_the_locked_still(sent, tmp_path):
    result = clip(STARTS_APART, tmp_path, end=tmp_path / "last.png")
    assert sent["start_image_url"] == "up:still.png"
    assert sent["end_image_url"] == "up:last.png"
    assert sent["image_urls"] == ["up:face.png"]
    assert result.recorded()["start_frame_sent"] is True
    assert result.recorded()["end_frame_sent"] is True


def test_its_own_price_row_bills_it_not_the_capability_rate(sent, tmp_path):
    assert clip(STARTS_APART, tmp_path).cost == pytest.approx(5 * 0.112)


def test_a_model_without_one_says_the_still_was_not_its_first_frame(sent, tmp_path):
    result = clip(REFS_ONLY, tmp_path, end=tmp_path / "last.png")
    assert "start_image_url" not in sent
    assert "end_image_url" not in sent
    assert result.recorded()["start_frame_sent"] is False
    assert result.recorded()["end_frame_sent"] is False


def test_a_bench_take_says_what_its_model_was_given(monkeypatch):
    from kalainova import bench, shotmake

    monkeypatch.setattr(config, "studio", lambda: TABLE)
    refs = (
        Reference(path=Path("f.png"), label="face"),
        Reference(path=Path("s.png"), label="side"),
    )
    two = shotmake.Held(refs)
    assert bench.conditioning("fal", STARTS_APART, two) == "the start frame and 2 kit reference(s)"
    assert bench.conditioning("fal", REFS_ONLY, two) == (
        "2 reference(s), the still among them; no start frame"
    )
    assert bench.conditioning("fal", REFS_ONLY, shotmake.Held()) == "the start frame only"


def test_a_reference_model_with_an_end_field_can_be_given_a_last_frame(monkeypatch):
    monkeypatch.setattr(config, "studio", lambda: TABLE)
    assert fal.Fal().inputs("video", STARTS_APART).end_frame
    assert not fal.Fal().inputs("video", REFS_ONLY).end_frame


def test_a_model_with_no_seed_field_is_sent_none_and_the_take_says_so(sent, tmp_path):
    result = clip(UNSEEDED, tmp_path, seed=42)
    assert "seed" not in sent
    recorded = result.recorded()
    assert recorded["seed_sent"] is False and "seed" not in recorded
    clip(STARTS_APART, tmp_path, seed=42)
    assert sent["seed"] == 42


def test_a_reference_clip_is_priced_at_its_own_rate_and_billed_length(monkeypatch):
    monkeypatch.setattr(config, "studio", lambda: TABLE)
    asked = Billable(capability="video", duration=1.9, image=True, references=True)
    assert fal.Fal().estimate(asked, STARTS_APART) == pytest.approx(5 * 0.112)


class _Reply:
    def __init__(self, body, status=200, text=""):
        self.body, self.status_code, self.text = body, status, text

    def json(self):
        return self.body


def test_fal_keeps_its_request_id_and_what_a_refusal_said(monkeypatch):
    # The request id is what fal's bill lists; the 422's body names the field it refused
    monkeypatch.setenv("FAL_KEY", "k")
    sub = {"request_id": "req-1", "status_url": "s", "response_url": "r"}
    monkeypatch.setattr(requests, "post", lambda *a, **kw: _Reply(sub))
    said = '{"detail":[{"msg":"Either frontal_image_url and reference_image_urls"}]}'
    replies = {"s": _Reply({"status": "COMPLETED"}), "r": _Reply({}, 422, said)}
    monkeypatch.setattr(requests, "get", lambda url, **kw: replies[url])
    ctx = context()
    with pytest.raises(InvalidRequestError, match="reference_image_urls"):
        fal.FalQueue().send("some/model", {}, ctx)
    assert ctx.receipt.request_id == "req-1"  # kept although the call failed


def test_fal_sends_the_labels_and_charges_what_it_billed(monkeypatch):
    # The vendor's own usage report carries our labels; the ledger settles at its billed units
    monkeypatch.setenv("FAL_KEY", "k")
    sent = {}

    def post(url, headers=None, **kw):
        sent.update(headers or {})
        return _Reply({"request_id": "req-2", "status_url": "s", "response_url": "r"})

    done = _Reply({"video": {"url": "u"}})
    done.headers = {"x-fal-billable-units": "5"}
    replies = {"s": _Reply({"status": "COMPLETED"}), "r": done}
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(requests, "get", lambda url, **kw: replies[url])
    monkeypatch.setattr(fal, "unit_price", lambda model: 0.14)
    ctx = context(labels={"job": "j1", "stage": "assets", "shot": "s,00", "attempt": "a1"})
    fal.FalQueue().send("some/model", {}, ctx)
    assert sent["X-Fal-Tags"] == "job=j1,stage=assets,shot=s00,attempt=a1"  # no comma in a value
    assert ctx.receipt.billed_units == 5 and ctx.receipt.vendor_cost == pytest.approx(0.70)


def test_with_no_billed_units_the_price_table_stands(monkeypatch):
    monkeypatch.setenv("FAL_KEY", "k")
    monkeypatch.setattr(
        requests, "post", lambda *a, **kw: _Reply({"status_url": "s", "response_url": "r"})
    )
    replies = {"s": _Reply({"status": "COMPLETED"}), "r": _Reply({})}
    monkeypatch.setattr(requests, "get", lambda url, **kw: replies[url])
    ctx = context()
    fal.FalQueue().send("some/model", {}, ctx)
    assert ctx.receipt.vendor_cost is None and ctx.receipt.billed_units is None
