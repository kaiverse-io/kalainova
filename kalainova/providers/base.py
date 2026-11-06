"""Provider contract.

A provider turns a request for one capability into a local file plus metadata.
The engine never cares which vendor made the bytes; it records provider, model,
prompt, cost, and rights on the asset so the job folder stays the source of truth.

Capabilities: llm, voice, image, video, music, sfx, transcribe.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .. import config

CAPABILITIES = ("llm", "voice", "image", "video", "music", "sfx", "transcribe")


@dataclass
class Result:
    path: Path | None = None
    cost: float = 0.0
    model: str = ""
    meta: dict[str, Any] = field(default_factory=dict)
    # word timings, seconds relative to the start of this file
    words: list[dict] = field(default_factory=list)
    text: str = ""


class Provider:
    name = "base"
    capabilities: tuple[str, ...] = ()
    env_key: str | None = None  # env var that must be set for the provider to be usable
    synthetic = True  # output is AI-generated and must be declared where platforms ask
    free = False  # calls cost nothing, so no price is needed under a cost cap
    placeholder = False  # output never counts as a real result

    def available(self) -> bool:
        return self.env_key is None or bool(os.environ.get(self.env_key))

    def price_key(self, capability: str, request: dict) -> str:
        """The row in config/studio.yaml that prices this request."""
        return capability

    def estimate(self, capability: str, **request) -> float | None:
        """Pre-call cost in dollars. None means this provider has no price for the request."""
        if self.free:
            return 0.0
        key = self.price_key(capability, request)
        if not config.price_for(self.name, key):
            return None
        return config.estimate(self.name, capability, key=key, chars=request.get("chars", 0),
                               duration=request.get("duration", 0.0))

    # Each capability is a method. Unimplemented ones raise.
    def llm(self, prompt: str, *, system: str = "", max_tokens: int = 4000, images: list[Path] | None = None, **kw) -> Result:
        raise NotImplementedError

    def voice(self, text: str, dst: Path, *, voice: str | None = None, **kw) -> Result:
        raise NotImplementedError

    def image(self, prompt: str, dst: Path, *, width: int, height: int, **kw) -> Result:
        raise NotImplementedError

    def video(self, prompt: str, dst: Path, *, duration: float, aspect: str, image: Path | None = None, **kw) -> Result:
        raise NotImplementedError

    def music(self, prompt: str, dst: Path, *, duration: float, **kw) -> Result:
        raise NotImplementedError

    def sfx(self, prompt: str, dst: Path, *, duration: float, **kw) -> Result:
        raise NotImplementedError

    def transcribe(self, src: Path, **kw) -> Result:
        raise NotImplementedError


_REGISTRY: dict[str, Callable[[], Provider]] = {}


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


def _load_builtin() -> None:
    if _REGISTRY:
        return
    from . import local, remote  # noqa: F401  (register on import)


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
            tried.append(f"{name} (missing {p.env_key})")
            continue
        return p
    raise LookupError(f"no provider for {capability}: tried {', '.join(tried) or 'nothing'}")
