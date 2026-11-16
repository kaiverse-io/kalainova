"""The contract every vendor adapter must meet (ADR 0023). A new adapter is done when this passes.

The engine speaks to models only in its own terms (providers/contract.py), so swapping a vendor is
an adapter and its config rows, and nothing else. These checks hold for every provider the engine
registers, the ones added later included:

- each capability it declares is one the engine knows, with a method taking a request and a context;
- it prices and describes each capability in the engine's terms, without a call;
- a paid one reaches its vendor only through a transport, so it can rehearse;
- rehearsing each paid capability sends nothing, writes the vendor request under the router's
  attempt, makes the file the engine asked for, and leaves the engine's own record names alone.
"""

from __future__ import annotations

import inspect
import shutil
from dataclasses import fields
from pathlib import Path

import pytest
import requests

from kalainova import media
from kalainova.providers import base, contract, rehearsal
from kalainova.providers.contract import (
    RECORDED,
    Billable,
    Context,
    ImageRequest,
    Inputs,
    JudgeRequest,
    LipsyncRequest,
    MotionRequest,
    MusicRequest,
    Request,
    SearchRequest,
    SeparateRequest,
    SfxRequest,
    SongRequest,
    TextRequest,
    TranscribeRequest,
    VideoRequest,
    VoiceRequest,
)
from kalainova.providers.transport import Transport

base.names()
BUILT_IN = sorted(
    name
    for name, make in base._REGISTRY.items()
    if type(make()).__module__.startswith("kalainova.")
)
PAID = [name for name in BUILT_IN if not base.get(name).free]
REQUESTS = [c for c in vars(contract).values() if isinstance(c, type) and issubclass(c, Request)]


def _pairs(names: list[str]) -> list[tuple[str, str]]:
    return [(n, c) for n in names for c in base.get(n).capabilities]


@pytest.mark.parametrize(("name", "capability"), _pairs(BUILT_IN))
def test_each_capability_is_the_engines_and_takes_a_request_and_a_context(name, capability):
    provider = base.get(name)
    assert capability in base.CAPABILITIES, f"{name} declares {capability}, which the engine lacks"
    method = getattr(type(provider), capability)
    assert method is not getattr(base.Provider, capability), f"{name} declares {capability} only"
    assert list(inspect.signature(method).parameters) == ["self", "req", "ctx"]


@pytest.mark.parametrize(("name", "capability"), _pairs(BUILT_IN))
def test_each_capability_is_priced_and_described_in_the_engines_terms(name, capability):
    provider = base.get(name)
    price = provider.estimate(Billable(capability=capability, duration=5.0, chars=10))
    assert price is None or price >= 0
    assert isinstance(provider.inputs(capability), Inputs)


@pytest.mark.parametrize("name", PAID)
def test_a_paid_provider_reaches_its_vendor_only_through_a_transport(name):
    provider = base.get(name)
    assert isinstance(provider.transport, Transport), f"{name} spends money outside a transport"
    assert provider.rehearses, f"{name} spends money and cannot show what it would send"


def test_every_request_names_a_capability_the_port_has():
    for kind in REQUESTS:
        if kind is Request:
            continue
        assert kind.capability in base.CAPABILITIES, kind.__name__
        assert kind.OUTPUTS == () or all(f in {x.name for x in fields(kind)} for f in kind.OUTPUTS)


@pytest.fixture
def inputs(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    still, clip, wav = tmp_path / "still.png", tmp_path / "clip.mp4", tmp_path / "line.wav"
    media.run(["-f", "lavfi", "-i", "testsrc2=size=320x568", "-frames:v", "1", str(still)])
    media.run(["-f", "lavfi", "-i", "testsrc2=size=320x568:d=1:r=8", "-pix_fmt", "yuv420p",
               str(clip)])  # fmt: skip
    media.run(["-f", "lavfi", "-i", "sine=d=1:r=16000", str(wav)])
    return tmp_path, still, clip, wav


def _ask(capability: str, folder: Path, still: Path, clip: Path, wav: Path) -> Request:
    asks: dict[str, Request] = {
        "llm": TextRequest(prompt="Reply with ok."),
        "judge": JudgeRequest(prompt="Reply with ok."),
        "voice": VoiceRequest(text="A line.", dst=folder / "v.wav"),
        "image": ImageRequest(prompt="a wall", dst=folder / "i.png", width=576, height=1024),
        "video": VideoRequest(
            prompt="a wall", dst=folder / "c.mp4", duration=2.0, aspect="9:16", start=still
        ),  # fmt: skip
        "motion": MotionRequest(character=still, driving=clip, dst=folder / "m.mp4"),
        "music": MusicRequest(prompt="a bed", dst=folder / "music.wav", duration=2.0),
        "sfx": SfxRequest(prompt="rain", dst=folder / "sfx.wav", duration=2.0),
        "song": SongRequest(lyrics="la la", dst=folder / "song.wav", style="pop", duration=10.0),
        "transcribe": TranscribeRequest(src=wav),
        "lipsync": LipsyncRequest(video=clip, audio=wav, dst=folder / "synced.mp4"),
        "separate": SeparateRequest(
            src=wav, vocals=folder / "vocals.wav", rest=folder / "rest.wav"
        ),
        "search": SearchRequest(query="water", limit=1),
    }
    return asks[capability]


@pytest.mark.parametrize(("name", "capability"), _pairs(PAID))
def test_rehearsing_a_paid_call_sends_nothing_and_makes_what_was_asked(
    name, capability, inputs, monkeypatch
):
    def sent(*a, **kw):
        raise AssertionError(f"{name} reached the network in a rehearsal")

    for verb in ("get", "post", "put"):
        monkeypatch.setattr(requests, verb, sent)
    provider = base.get(name)
    asked = _ask(capability, *inputs)
    with rehearsal.opened() as dry:
        if provider.missing_env(capability):
            pytest.skip(f"{name} is not set up here: {provider.missing_env(capability)}")
        dry.begin("t1", asked, name, 0.0, "contract")
        res = getattr(provider, capability)(asked, Context(attempt="t1"))
    assert dry.calls["t1"]["requests"], f"{name} {capability} wrote down no vendor request"
    assert not dry.loose
    made = asked.output()
    if made is not None:
        assert made.is_file()
        assert isinstance(asked, ImageRequest) or media.duration(made) > 0
    assert not set(res.meta) & set(RECORDED), f"{name} writes names the engine records itself"


def test_an_openai_compatible_vendor_rehearses_once_it_has_a_model(monkeypatch):
    from kalainova.providers import compat

    def sent(*a, **kw):
        raise AssertionError("reached the network in a rehearsal")

    monkeypatch.setattr(requests, "post", sent)
    monkeypatch.setattr(compat.config, "model_for", lambda name, key: "m-1" if key == "llm" else "")
    provider = base.get("groq")
    with rehearsal.opened() as dry:
        assert not provider.missing_env("llm")
        dry.begin("t1", TextRequest(prompt="ok"), "groq", 0.0, "contract")
        provider.llm(TextRequest(prompt="ok"), Context(attempt="t1"))
    (sent_request,) = dry.calls["t1"]["requests"]
    assert sent_request["model"] == "m-1" and sent_request["payload"]["model"] == "m-1"
