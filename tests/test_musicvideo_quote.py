"""The quote a song video says before it runs counts every planned take."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kalainova.editor import musicvideo
from kalainova.jobfs import ContractError

SPANS = [{"start": 0.0, "end": 3.0}, {"start": 3.0, "end": 6.0}, {"start": 6.0, "end": 9.0}]
KINDS = ["video", "still", "video"]


@pytest.fixture
def per_clip(monkeypatch):
    """Every moving clip quoted at one dollar."""
    monkeypatch.setattr(musicvideo.router, "price", lambda job, asked, **kw: ("fal", 1.0, []))
    return SimpleNamespace(id="v1", job={})


def test_two_planned_takes_are_quoted_twice(per_clip):
    said: list[str] = []
    total = musicvideo.estimate(per_clip, SPANS, KINDS, 0.5, said.append, takes_each=2)
    assert total == 4.0
    assert "2 moving, 2 take(s) each: about $4.00" in said[0]


def test_the_cap_is_held_against_every_planned_take(per_clip):
    with pytest.raises(ContractError, match="over the \\$3.00 cap"):
        musicvideo.estimate(per_clip, SPANS, KINDS, 0.5, lambda _: None, cap=3.0, takes_each=2)


def test_a_missing_key_is_said_and_does_not_zero_the_quote(monkeypatch):
    from kalainova.providers import router

    monkeypatch.setattr(router, "price", lambda job, asked, **kw: ("fal", 1.0, ["FAL_KEY"]))
    said: list[str] = []
    spans = [{"start": 0.0, "end": 4.0}]
    total = musicvideo.estimate(
        SimpleNamespace(id="v1", job={}), spans, ["video"], 0.0, said.append
    )
    assert total == 1.0
    assert "fal needs FAL_KEY" in said[0]


def test_b_roll_is_priced_on_the_plain_model_and_each_shot_pays_for_its_still(monkeypatch):
    from kalainova.providers import router

    asked: list[tuple] = []

    def price(job, billable, **kw):
        pin = kw.get("pin")
        asked.append((billable.capability, billable.references, pin.model if pin else None))
        cost = 0.15 if billable.capability == "image" else (0.5 if billable.references else 1.0)
        return ("fal", cost, [])

    monkeypatch.setattr(router, "price", price)
    spans = [{"start": 0.0, "end": 3.0}, {"start": 3.0, "end": 6.0}]
    total = musicvideo.estimate(
        SimpleNamespace(id="v1", job={}), spans, ["video", "video"], 0.0, lambda _: None,
        model="pinned", only=["fal"], refs=[True, False], image_only=["fal"],
    )  # fmt: skip
    assert total == pytest.approx(0.5 + 1.0 + 2 * 0.15)
    assert ("video", True, "pinned") in asked and ("video", False, None) in asked
