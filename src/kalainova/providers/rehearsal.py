"""A run that sends nothing and spends nothing.

While a rehearsal is open, an adapter that can rehearse (`Provider.rehearses`) writes down each
request it would send: the model, every field, and each file it would upload, named by its hash
instead of sent. It gets back a stand-in file of the shape it asked for, so the rest of the line
runs on it. The router refuses any provider that costs money and cannot rehearse, so a rehearsal
reaches no vendor and needs no key.

The router opens a call with the file it is waiting for, and the adapter's stand-in names that same
file, so each request is paired with the router's estimate and the adapter's own price.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import media
from ..blobstore import sha256_file

SCHEME = "rehearsal://"
PICTURES = (".png", ".jpg", ".jpeg", ".webp")
MOVING = (".mp4", ".mov", ".webm")
SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
LIFE = "mold=10:ratio=0.4:death_color=#202020:life_color=#e0e0e0"  # moves enough to read as moving

_guard = threading.Lock()
_active: Rehearsal | None = None


@dataclass
class Rehearsal:
    calls: dict[str, dict[str, Any]] = field(default_factory=dict)
    loose: list[dict[str, Any]] = field(default_factory=list)  # a request no router call opened
    _uploads: dict[str, Path] = field(default_factory=dict)
    _requests: dict[str, dict[str, Any]] = field(default_factory=dict)

    def begin(
        self, dst: Path, capability: str, provider: str, estimate: float | None, note: str
    ) -> None:
        with _guard:
            self.calls[dst.name] = {
                "n": len(self.calls) + 1,
                "capability": capability,
                "provider": provider,
                "note": note,
                "estimate": round(float(estimate or 0.0), 6),
                "requests": [],
            }

    def settle(self, dst: Path, cost: float, model: str, meta: dict[str, Any]) -> None:
        with _guard:
            call = self.calls.get(dst.name)
            if call is not None:
                call.update(cost=round(float(cost), 6), model=model, meta=dict(meta))

    def upload(self, path: Path) -> str:
        token = f"{SCHEME}upload/{path.name}#sha256={sha256_file(path)[:16]}"
        with _guard:
            self._uploads[token] = path
        return token

    def request(self, model: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Write the request down, and answer with every reply shape the adapter reads."""
        with _guard:
            url = f"{SCHEME}result/{len(self._requests) + 1}"
            self._requests[url] = {"model": model, "payload": payload}
        found = {"url": url}
        return {"images": [found], "video": found, "audio": found, "audio_file": found}

    def stand_in(self, url: str, dst: Path) -> None:
        """A file of the shape the request asked for, made locally, so the line can go on."""
        with _guard:
            entry = self._requests.get(url) or {}
        payload = entry.get("payload") or {}
        if dst.suffix.lower() in PICTURES:
            width, height = self._size(payload)
            media.run(["-f", "lavfi", "-i", f"testsrc2=size={width}x{height}", "-frames:v", "1",
                       str(dst)])  # fmt: skip
        elif dst.suffix.lower() in MOVING:
            width, height = self._size(payload)
            seconds = float(str(payload.get("duration") or 5).rstrip("s") or 5)
            media.run(["-f", "lavfi", "-i", f"life=size={width}x{height}:rate=24:{LIFE}",
                       "-t", f"{seconds:g}", "-c:v", "libx264", "-preset", "ultrafast",
                       "-pix_fmt", "yuv420p", str(dst)])  # fmt: skip
        else:
            seconds = float(str(payload.get("duration") or 5).rstrip("s") or 5)
            media.run(["-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000",
                       "-t", f"{seconds:g}", "-f", "wav", str(dst)])  # fmt: skip
        with _guard:
            call = self.calls.get(dst.name)
            if call is not None:
                call["requests"].append(entry)
            else:
                self.loose.append(entry)

    def _size(self, payload: dict[str, Any]) -> tuple[int, int]:
        """The shape asked for, else the first uploaded picture's, else a vertical frame."""
        asked = payload.get("aspect_ratio")
        if asked in SIZES:
            return SIZES[asked]
        size = payload.get("image_size")
        if isinstance(size, dict) and size.get("width") and size.get("height"):
            return int(size["width"]) // 2 * 2, int(size["height"]) // 2 * 2
        for value in payload.values():
            path = self._uploads.get(value) if isinstance(value, str) else None
            if path is not None and path.suffix.lower() in PICTURES:
                info = media.summarize(path)
                w, h = int(info.get("width") or 1080), int(info.get("height") or 1920)
                scale = 1080 / min(w, h)
                return round(w * scale) // 2 * 2, round(h * scale) // 2 * 2
        return SIZES["9:16"]

    def report(self) -> list[dict[str, Any]]:
        return sorted(self.calls.values(), key=lambda c: c["n"]) + [
            {"n": 0, "capability": "?", "note": "a request no router call opened", "requests": [e]}
            for e in self.loose
        ]


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
