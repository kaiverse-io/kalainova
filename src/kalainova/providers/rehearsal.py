"""A run that sends nothing and spends nothing.

While a rehearsal is open, an adapter that can rehearse (`Provider.rehearses`) writes down each
request it would send through its transport (providers/transport.py): the model, every field, and
each file it would upload, named by its hash instead of sent. It gets back a stand-in file of the
shape the engine asked for, so the rest of the line runs on it. The router refuses any provider
that costs money and cannot rehearse, so a rehearsal reaches no vendor and needs no key.

The router opens a call under its attempt id with the engine's own request, its content key and its
model; the transport sends under the same attempt (`Context.attempt`), so each vendor request is
paired with the engine's request, the router's estimate and the adapter's own price. Nothing here
reads a vendor's fields: a stand-in's shape comes from the engine's request.
"""

from __future__ import annotations

import math
import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import media
from ..blobstore import sha256_file
from . import payloads
from .contract import (
    ImageRequest,
    LipsyncRequest,
    MotionRequest,
    Request,
    VideoRequest,
    VoiceRequest,
)

SCHEME = "rehearsal://"
PICTURES = (".png", ".jpg", ".jpeg", ".webp")
MOVING = (".mp4", ".mov", ".webm")
SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
LIFE = "mold=10:ratio=0.4:death_color=#202020:life_color=#e0e0e0"  # moves enough to read as moving

_guard = threading.Lock()
_active: Rehearsal | None = None


@dataclass
class Rehearsal:
    calls: dict[str, dict[str, Any]] = field(default_factory=dict)  # by the router's attempt id
    loose: list[dict[str, Any]] = field(default_factory=list)  # a request no router call opened
    phase: str = ""  # the stage being rehearsed (stills, motion), kept on each call
    _uploads: dict[str, Path] = field(default_factory=dict)
    _requests: dict[str, tuple[dict[str, Any], str]] = field(default_factory=dict)
    _asked: dict[str, Request] = field(default_factory=dict)

    def begin(
        self,
        attempt: str,
        request: Request,
        provider: str,
        estimate: float | None,
        note: str,
        *,
        key: str = "",
        model: str | None = None,
        routed: str = "",
        shot: str = "",
    ) -> None:
        with _guard:
            self._asked[attempt] = request
            self.calls[attempt] = {
                "n": len(self.calls) + 1,
                "capability": request.capability,
                "provider": provider,
                "model": model,
                "routed": routed or model or "",  # the model it is sent to, as a package binds it
                "note": note,
                "shot": shot,  # the beat it is for, from the router's labels
                "estimate": round(float(estimate or 0.0), 6),
                "key": key,
                "phase": self.phase,
                "asked": request.described(),
                "requests": [],
            }

    def settle(self, attempt: str, cost: float, model: str, meta: dict[str, Any]) -> None:
        with _guard:
            call = self.calls.get(attempt)
            if call is not None:
                call.update(cost=round(float(cost), 6), model=model, meta=dict(meta))

    def upload(self, path: Path) -> str:
        token = f"{SCHEME}upload/{path.name}#sha256={sha256_file(path)[:16]}"
        with _guard:
            self._uploads[token] = path
        return token

    def request(
        self,
        model: str,
        payload: dict[str, Any],
        problems: list[str] | None = None,
        *,
        attempt: str = "",
    ) -> str:
        """Write down what the adapter would send, with what the vendor's schema says of it, under
        the router's call for this attempt; answer with the address its file would come back at."""
        entry: dict[str, Any] = {
            "model": model,
            "payload": payload,
            "sealed": payloads.sealed(payload),  # each uploaded file named by its bytes
            "digest": payloads.digest(model, payload),  # what a package signs (ADR 0022)
        }
        if problems is not None:
            entry["schema"] = problems or "ok"
        with _guard:
            url = f"{SCHEME}result/{len(self._requests) + 1}"
            self._requests[url] = (entry, attempt)
            call = self.calls.get(attempt)
            if call is not None:
                call["requests"].append(entry)
            else:
                self.loose.append(entry)
        return url

    def stand_in(self, url: str, dst: Path) -> None:
        """A file of the shape the engine asked for, made locally, so the line can go on."""
        with _guard:
            entry, attempt = self._requests.get(url) or ({}, "")
            asked = self._asked.get(attempt)
        width, height = _size(asked)
        seconds = _sent_length(entry.get("payload") or {}) or _length(asked)
        if dst.suffix.lower() in PICTURES:
            media.run(["-f", "lavfi", "-i", f"testsrc2=size={width}x{height}", "-frames:v", "1",
                       str(dst)])  # fmt: skip
        elif dst.suffix.lower() in MOVING:
            media.run(["-f", "lavfi", "-i", f"life=size={width}x{height}:rate=24:{LIFE}",
                       "-t", f"{seconds:g}", "-c:v", "libx264", "-preset", "ultrafast",
                       "-pix_fmt", "yuv420p", str(dst)])  # fmt: skip
        else:
            media.run(["-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000",
                       "-t", f"{seconds:g}", "-f", "wav", str(dst)])  # fmt: skip

    def report(self) -> list[dict[str, Any]]:
        return sorted(self.calls.values(), key=lambda c: c["n"]) + [
            {"n": 0, "capability": "?", "note": "a request no router call opened", "requests": [e]}
            for e in self.loose
        ]


def _even(width: float, height: float) -> tuple[int, int]:
    return round(width) // 2 * 2, round(height) // 2 * 2


def _picture_size(path: Path | None) -> tuple[int, int] | None:
    if path is None or not path.is_file():
        return None
    info = media.summarize(path)
    w, h = int(info.get("width") or 1080), int(info.get("height") or 1920)
    scale = 1080 / min(w, h)
    return _even(w * scale, h * scale)


def _size(asked: Request | None) -> tuple[int, int]:
    """The shape the engine asked for: a still's size, a clip's aspect or its first frame's."""
    if isinstance(asked, ImageRequest):
        return _even(asked.width, asked.height)
    if isinstance(asked, VideoRequest):
        if asked.aspect in SIZES:
            return SIZES[asked.aspect]
        return _picture_size(asked.start) or SIZES["9:16"]
    if isinstance(asked, LipsyncRequest):
        return _picture_size(asked.video) or SIZES["9:16"]
    if isinstance(asked, MotionRequest):
        return _picture_size(asked.character) or SIZES["9:16"]
    return SIZES["9:16"]


def _sent_length(payload: dict[str, Any]) -> float | None:
    """The length the adapter asked the vendor for, which is the length its file comes back at.
    A vendor that only makes set lengths is asked for the next one up, so this is the length a
    call made on the file (a lip sync) is billed on."""
    found = re.match(r"\s*(\d+(?:\.\d+)?)", str(payload.get("duration", "")))
    return float(found.group(1)) if found and float(found.group(1)) > 0 else None


def _length(asked: Request | None) -> float:
    """How long the file is: what was asked for, in the whole seconds vendors bill."""
    if isinstance(asked, VoiceRequest):
        return max(1.0, round(len(asked.text) / 15, 1))
    seconds = asked.billable().duration if asked is not None else 0.0
    return float(math.ceil(seconds)) if seconds > 0 else 5.0


def active() -> Rehearsal | None:
    return _active


@contextmanager
def opened() -> Iterator[Rehearsal]:
    """Open a rehearsal for the length of the block. Only one runs at a time."""
    global _active
    with _guard:
        if _active is not None:
            raise RuntimeError("a rehearsal is already open")
        _active = found = Rehearsal()
    try:
        yield found
    finally:
        with _guard:
            _active = None
