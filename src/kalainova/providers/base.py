"""Provider contract: the port every vendor adapter implements (ADR 0023).

A provider turns one typed request (providers/contract.py) into a local file and a `Result`. The
engine never sees a vendor's payload or reply: an adapter maps the engine's request to its vendor's
fields and maps the reply back. What a model can be given is said in the engine's terms
(`inputs`), and so is what a call costs (`estimate` on a `Billable`).

Capabilities: llm, judge, voice, image, video, motion, music, song, sfx, transcribe, lipsync,
separate, graphics, search. Each is a method taking its request and the router's `Context`.

To add a provider, put a module in this package or name one under provider_modules in
config/studio.yaml. It registers a Provider subclass, and config/studio.yaml lists it and prices it.
tests/boundary/test_provider_contract.py is the suite every registered adapter must pass.
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import config
from .contract import (
    Billable,
    BilledError,
    Context,
    GraphicsRequest,
    ImageRequest,
    Inputs,
    LipsyncRequest,
    MotionRequest,
    MusicRequest,
    RefusalError,
    Result,
    SearchRequest,
    SeparateRequest,
    SfxRequest,
    SingRequest,
    SongRequest,
    TextRequest,
    TranscribeRequest,
    VideoRequest,
    VoiceRequest,
)
from .transport import Transport

__all__ = ["BilledError", "Provider", "RefusalError", "Result", "get", "names", "register"]

CAPABILITIES = (
    "llm",
    "judge",
    "voice",
    "image",
    "video",
    "motion",
    "music",
    "song",
    "sfx",
    "transcribe",
    "lipsync",
    "sing",
    "separate",
    "graphics",
    "search",
)


class Provider:
    name = "base"
    capabilities: tuple[str, ...] = ()
    env_key: str | None = None  # env var that must be set for the provider to be usable
    env_keys: tuple[str, ...] = ()  # for a provider that needs more than one
    env_file_key: str | None = None  # env var naming an existing file that must be readable
    synthetic = True  # output is AI-generated and must be declared where platforms ask
    free = False  # calls cost nothing, so no price is needed under a cost cap
    placeholder = False  # output never counts as a real result
    # Keeps its own deadline (Context.deadline_sec), so time queued for a shared GPU does not count
    # against the call, and a call that runs out can really be stopped. Python cannot kill a thread.
    self_timed = False
    # Can write down what it would send instead of sending it (providers/rehearsal.py). Every
    # adapter that reaches its vendor through a transport can.
    rehearses = False
    # How it reaches its vendor (providers/transport.py); None for one that runs on this machine.
    transport: Transport | None = None

    def missing_env(self, capability: str = "") -> list[str]:
        from . import rehearsal

        if self.rehearses and rehearsal.active() is not None:
            return []  # a rehearsal sends nothing, so it needs no key
        needed = ((self.env_key,) if self.env_key else ()) + tuple(self.env_keys)
        missing = [key for key in needed if not os.environ.get(key)]
        if self.env_file_key and not missing:
            val = os.environ.get(self.env_file_key)
            if not val or not Path(val).is_file():
                missing.append(f"{self.env_file_key} names no file")
        return missing

    def available(self, capability: str = "") -> bool:
        try:
            return not self.missing_env(capability)
        except TypeError:  # a plug-in written before missing_env took the capability
            return not self.missing_env()

    # ---------------------------------------------------------------- what it costs
    def price_key(self, billable: Billable) -> str:
        """The row in config/studio.yaml that prices this call."""
        return billable.capability

    def billed_seconds(self, billable: Billable, model: str | None = None) -> float:
        """How long the file this call returns will be. A vendor that only makes set lengths
        returns the next one up, and a call made on that file (a lip sync) is billed on it."""
        return float(billable.duration or 0.0)

    def estimate(self, billable: Billable, model: str | None = None) -> float | None:
        """Pre-call cost in dollars. None means this provider has no price for the call."""
        if self.free:
            return 0.0
        key = self.price_key(billable)
        row = config.price_for(self.name, key, model) if model else config.price_for(self.name, key)
        if not row:
            return None
        return float(
            config.estimate(
                self.name,
                billable.capability,
                key=key,
                chars=billable.chars,
                duration=billable.duration,
                model=model,
            )
        )

    def list_price(self, model: str) -> dict[str, Any] | None:
        """The vendor's own unit price for a model, when it publishes one: unit_price and unit."""
        return self.transport.list_price(model) if self.transport else None

    # ---------------------------------------------------------------- what it takes
    def default_model(self, capability: str, *, references: bool = False) -> str:
        key = capability
        if capability == "video":
            key = "reference_to_video" if references else "image_to_video"
        return config.model_for(self.name, key) or config.model_for(self.name, capability)

    def inputs(self, capability: str, model: str | None = None) -> Inputs:
        """What a model of this provider can be given, from config/studio.yaml's model tables.

        The tables hold the vendor's field names; only this package reads them. With no model, the
        provider's default for a plain call is described."""
        name = model or self.default_model(capability)
        refs = config.reference_spec(self.name, capability, name)
        plain = (
            config.video_spec(self.name, name)
            if capability == "video"
            else config.sing_spec(self.name, name)
            if capability == "sing"
            else {}
        )
        sound = config.audio_spec(self.name, name) if capability in ("song", "music") else {}
        most = sound.get("max_sec")
        return Inputs(
            references=int(refs.get("max_images") or plain.get("max_images") or 0),
            characters=int(refs["max_characters"]) if refs.get("max_characters") else None,
            start_with_references=bool(refs.get("start_image_param")),
            end_frame=bool(plain.get("end_image_param") or refs.get("end_image_param")),
            seed=bool(plain.get("takes_seed", refs.get("takes_seed", capability != "sing"))),
            longest_sec=float(most) if most else None,
            repaint=bool(sound.get("edit_with") or sound.get("edits")),
            guides={
                use: float(how.get("clip_sec") or 0)
                for use, how in (sound.get("guide") or {}).items()
            },
        )

    def models(self, capability: str) -> list[str]:
        """The models config/studio.yaml describes for this provider and capability."""
        tables = config.studio()
        listed = {"video": "video_models", "sing": "sing_models"}.get(capability)
        found = list((tables.get(listed) or {}).get(self.name) or {}) if listed else []
        found += list(
            ((tables.get("reference_models") or {}).get(self.name) or {}).get(capability) or {}
        )
        return list(dict.fromkeys(found))

    def problems(self, model: str, payload: dict[str, Any]) -> list[str]:
        """What the vendor would refuse in a payload before it is sent, from its published schema.
        Empty when it publishes none."""
        return self.transport.problems(model, payload) if self.transport else []

    # ---------------------------------------------------------------- capabilities
    def _unsupported(self, capability: str) -> Result:
        raise NotImplementedError(f"{self.name} does not implement {capability}")

    def llm(self, req: TextRequest, ctx: Context) -> Result:
        return self._unsupported("llm")

    def judge(self, req: TextRequest, ctx: Context) -> Result:
        return self._unsupported("judge")

    def voice(self, req: VoiceRequest, ctx: Context) -> Result:
        return self._unsupported("voice")

    def image(self, req: ImageRequest, ctx: Context) -> Result:
        return self._unsupported("image")

    def video(self, req: VideoRequest, ctx: Context) -> Result:
        return self._unsupported("video")

    def motion(self, req: MotionRequest, ctx: Context) -> Result:
        return self._unsupported("motion")

    def music(self, req: MusicRequest, ctx: Context) -> Result:
        return self._unsupported("music")

    def song(self, req: SongRequest, ctx: Context) -> Result:
        return self._unsupported("song")

    def sfx(self, req: SfxRequest, ctx: Context) -> Result:
        return self._unsupported("sfx")

    def transcribe(self, req: TranscribeRequest, ctx: Context) -> Result:
        return self._unsupported("transcribe")

    def lipsync(self, req: LipsyncRequest, ctx: Context) -> Result:
        return self._unsupported("lipsync")

    def sing(self, req: SingRequest, ctx: Context) -> Result:
        """A shot sung in one call, from its still and its line."""
        return self._unsupported("sing")

    def separate(self, req: SeparateRequest, ctx: Context) -> Result:
        """Split a mix into its vocals and everything else."""
        return self._unsupported("separate")

    def graphics(self, req: GraphicsRequest, ctx: Context) -> Result:
        """Render a composition folder to a file."""
        return self._unsupported("graphics")

    def search(self, req: SearchRequest, ctx: Context) -> Result:
        """Find sources, as `Result.hits`."""
        return self._unsupported("search")


_REGISTRY: dict[str, Callable[[], Provider]] = {}
_loaded = False


def register(factory: Callable[[], Provider]) -> Callable[[], Provider]:
    inst = factory()
    _REGISTRY[inst.name] = factory
    return factory


def get(name: str) -> Provider:
    _load_builtin()
    if name not in _REGISTRY:
        raise KeyError(f"unknown provider {name!r}; known: {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def names() -> list[str]:
    _load_builtin()
    return sorted(_REGISTRY)


# Modules in this package that are not adapters: the port, the router, and what they share.
NOT_ADAPTERS = (
    "base",
    "router",
    "contract",
    "errors",
    "results",
    "transport",
    "records",
    "prices",
    "rehearsal",
    "check",
    "retired",
    "outputs",
)


def _load_builtin() -> None:
    """Import every provider module once. A plug-in registered first must not hide the others, and
    one module with a missing dependency must not take the rest down."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    package = __name__.rsplit(".", 1)[0]
    modules = [
        f"{package}.{m.name}"
        for m in pkgutil.iter_modules([str(Path(__file__).parent)])
        if m.name not in NOT_ADAPTERS
    ]
    for module in modules + list(config.studio().get("provider_modules") or []):
        try:
            importlib.import_module(module)
        except ImportError as exc:
            print(f"provider module {module} not loaded: {exc}", file=sys.stderr)


def resolve(capability: str, preference: list[str]) -> Provider:
    """First available provider in the preference list that implements the capability."""
    _load_builtin()
    tried = []
    for name in preference:
        if name not in _REGISTRY:
            tried.append(f"{name} (unknown)")
            continue
        p = _REGISTRY[name]()
        if capability not in p.capabilities:
            tried.append(f"{name} (no {capability})")
            continue
        if not p.available():
            tried.append(f"{name} (missing {', '.join(p.missing_env())})")
            continue
        return p
    raise LookupError(f"no provider for {capability}: tried {', '.join(tried) or 'nothing'}")
