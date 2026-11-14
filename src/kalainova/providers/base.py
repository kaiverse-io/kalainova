"""Provider contract.

A provider turns a request for one capability into a local file plus metadata.
The engine never cares which vendor made the bytes; it records provider, model,
prompt, cost, and rights on the asset so the job folder stays the source of truth.

Capabilities: llm, voice, image, video, music, song, sfx, transcribe.

To add a provider, put a module in this package or name one under provider_modules in
config/studio.yaml. It registers a Provider subclass, and config/studio.yaml lists it and prices it.
"""

from __future__ import annotations

import importlib
import os
import pkgutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import config

CAPABILITIES = (
    "llm",
    "voice",
    "image",
    "video",
    "music",
    "song",
    "sfx",
    "transcribe",
    "lipsync",
    "separate",
    "graphics",
    "search",
)


class BilledError(RuntimeError):
    """The vendor charged for this call, and then the file could not be fetched.

    Raised by an adapter so the ledger still records the money.
    """

    def __init__(self, billed: float, message: str) -> None:
        super().__init__(message)
        self.billed = billed


class RefusalError(RuntimeError):
    """The model or provider declined the request under its policy."""


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
    env_keys: tuple[str, ...] = ()  # for a provider that needs more than one
    synthetic = True  # output is AI-generated and must be declared where platforms ask
    free = False  # calls cost nothing, so no price is needed under a cost cap
    placeholder = False  # output never counts as a real result
    # Keeps its own deadline, so time queued for a shared GPU does not count against the call, and a
    # call that runs out can really be stopped. Python cannot kill a worker thread.
    self_timed = False

    def missing_env(self) -> list[str]:
        needed = ((self.env_key,) if self.env_key else ()) + tuple(self.env_keys)
        return [key for key in needed if not os.environ.get(key)]

    def available(self) -> bool:
        return not self.missing_env()

    def price_key(self, capability: str, request: dict) -> str:
        """The row in config/studio.yaml that prices this request."""
        return capability

    def estimate(self, capability: str, **request) -> float | None:
        """Pre-call cost in dollars. None means this provider has no price for the request."""
        if self.free:
            return 0.0
        key = self.price_key(capability, request)
        model = request.get("model")
        row = config.price_for(self.name, key, model) if model else config.price_for(self.name, key)
        if not row:
            return None
        return config.estimate(
            self.name,
            capability,
            key=key,
            chars=request.get("chars", 0),
            duration=request.get("duration", 0.0),
            model=model,
        )

    def reference_support(self, capability: str, model: str) -> dict[str, Any]:
        """How this provider's model takes reference images. Empty means it cannot hold a face."""
        return {}

    def takes_end_image(self, capability: str, model: str | None = None) -> bool:
        """Whether this provider's model can be given a last frame as an image."""
        return False

    # Each capability is a method. Unimplemented ones raise.
    def llm(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 4000,
        images: list[Path] | None = None,
        **kw,
    ) -> Result:
        raise NotImplementedError

    def voice(self, text: str, dst: Path, *, voice: str | None = None, **kw) -> Result:
        raise NotImplementedError

    def image(self, prompt: str, dst: Path, *, width: int, height: int, **kw) -> Result:
        raise NotImplementedError

    def video(
        self,
        prompt: str,
        dst: Path,
        *,
        duration: float,
        aspect: str,
        image: Path | None = None,
        **kw,
    ) -> Result:
        raise NotImplementedError

    def music(self, prompt: str, dst: Path, *, duration: float, **kw) -> Result:
        raise NotImplementedError

    def song(
        self, lyrics: str, dst: Path, *, style: str = "", duration: float | None = None, **kw
    ) -> Result:
        raise NotImplementedError

    def sfx(self, prompt: str, dst: Path, *, duration: float, **kw) -> Result:
        raise NotImplementedError

    def transcribe(self, src: Path, **kw) -> Result:
        raise NotImplementedError

    def lipsync(self, video: Path, audio: Path, dst: Path, **kw) -> Result:
        raise NotImplementedError

    def separate(self, src: Path, vocals: Path, rest: Path, **kw) -> Result:
        """Split a mix into its vocals and everything else."""
        raise NotImplementedError

    def graphics(self, folder: Path, dst: Path, **kw) -> Result:
        """Render a composition folder to a file."""
        raise NotImplementedError

    def search(self, query: str, *, limit: int = 5, **kw) -> Result:
        """Find sources. meta["hits"] holds url, title, publisher, snippet, and text when known."""
        raise NotImplementedError


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


def _load_builtin() -> None:
    """Import every provider module once. A plug-in registered first must not hide the others, and one
    module with a missing dependency must not take the rest down."""
    global _loaded
    if _loaded:
        return
    _loaded = True
    package = __name__.rsplit(".", 1)[0]
    modules = [
        f"{package}.{m.name}"
        for m in pkgutil.iter_modules([str(Path(__file__).parent)])
        if m.name not in ("base", "router")
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
