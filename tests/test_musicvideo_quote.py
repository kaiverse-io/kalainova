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
    monkeypatch.setattr(musicvideo.router, "quote", lambda job, cap, **kw: ("fal", 1.0))
    return SimpleNamespace(id="v1", job={})


def test_two_planned_takes_are_quoted_twice(per_clip):
    said: list[str] = []
    total = musicvideo.estimate(per_clip, SPANS, KINDS, 0.5, said.append, takes_each=2)
    assert total == 4.0
    assert "2 moving, 2 take(s) each: about $4.00" in said[0]


def test_the_cap_is_held_against_every_planned_take(per_clip):
    with pytest.raises(ContractError, match="over the \\$3.00 cap"):
        musicvideo.estimate(per_clip, SPANS, KINDS, 0.5, lambda _: None, cap=3.0, takes_each=2)
