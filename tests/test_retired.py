"""A route the vendor says is gone (HTTP 410) is written down once and refused before spend: in
config for every studio, in the studio's own retired.json the first time a vendor answers 410."""

from __future__ import annotations

import json

import pytest
from fakes import make_job

from kalainova.providers import base, retired, router, transport
from kalainova.providers.contract import Pin, RetiredError, SongRequest


class _Gone(base.Provider):
    name = "gone"
    capabilities = ("song",)
    env_key = None
    free = True
    calls = 0

    def song(self, req, ctx):
        type(self).calls += 1
        raise RetiredError("gone answered 410: This endpoint is deprecated")


def test_a_route_retired_in_config_names_what_carries_on():
    said = retired.why("fal", "mureka/v9.5/generate/song")
    assert said and "410" in said and said.endswith("use mureka:mureka-9.5")
    assert retired.why("mureka", "mureka-9.5") is None
    assert retired.why("fal", None) is None


def test_a_410_is_read_as_retired():
    class Resp:
        status_code, text = 410, '{"detail": "This endpoint is deprecated"}'

    with pytest.raises(RetiredError):
        transport.raise_for(Resp(), "fal")


def test_a_410_is_written_down_once_and_the_next_job_stops_before_asking(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    monkeypatch.setitem(base._REGISTRY, "gone", _Gone)
    _Gone.calls = 0
    job = make_job(tmp_path, media=["song"], providers={"song": ["gone"]})
    ask = SongRequest(lyrics="w", dst=job.work / "s.wav", duration=60,
                      pin=Pin(provider="gone", model="m1"))  # fmt: skip
    with pytest.raises(router.ProviderError):
        router.generate(job, ask, only=["gone"])
    kept = json.loads((tmp_path / retired.FILE).read_text())
    assert list(kept) == ["gone:m1"] and "deprecated" in kept["gone:m1"]["said"]
    with pytest.raises(router.ProviderError, match="gone:m1 is retired"):
        router.generate(job, ask, only=["gone"])
    assert _Gone.calls == 1, "the second job never reached the vendor"
