"""How an adapter reaches its vendor: a send, files up and down, what the vendor said (ADR 0023).

An adapter maps the engine's request to its vendor's payload and maps the reply back; a transport
moves bytes. Everything every vendor needs the same way lives here once, so a new adapter gets it by
using a transport rather than by rewriting it:

- **Rehearsal.** While one is open (providers/rehearsal.py), `send` writes the payload down,
  `upload` names a file by its hash, and `fetch` makes a stand-in of the shape the engine asked
  for. Nothing leaves the machine. `problems` reads the vendor's published schema, so a rehearsal
  can say which field the vendor would refuse.
- **The receipt.** `send` fills `Context.receipt` (the vendor's request id, billed units, and what
  they cost at the account's unit price) as soon as each is known, so a failed call keeps them.
- **Labels.** The router's labels go with the request where the vendor takes them.
- **Errors in the engine's terms.** An HTTP failure becomes `InvalidRequestError`,
  `UnauthorizedError`, `RateLimitedError` or `UnavailableError` (providers/contract.py), keeping
  what the vendor said.
- **A billed failure.** A file that does not arrive after the vendor finished is `BilledError`.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from . import rehearsal
from .contract import (
    BilledError,
    Context,
    InvalidRequestError,
    RateLimitedError,
    UnauthorizedError,
    UnavailableError,
    VendorError,
)

TIMEOUT = 120
REQUEST_ID_HEADERS = ("x-fal-request-id", "request-id", "x-request-id")
INVALID = (400, 404, 405, 409, 413, 415, 422)


@dataclass
class Reply:
    """What a vendor sent back: its JSON, or the file itself as bytes."""

    data: Any = None
    content: bytes = b""
    rehearsed: str = ""  # in a rehearsal, the address its stand-in comes from

    def get(self, path: str, default: Any = None) -> Any:
        """A value by dotted path ("video.url", "images.0.url"); the default when it is missing,
        and always in a rehearsal, where nothing came back."""
        if self.rehearsed:
            return default
        found: Any = self.data
        for part in path.split("."):
            if isinstance(found, dict):
                found = found.get(part)
            elif isinstance(found, list) and part.isdigit() and int(part) < len(found):
                found = found[int(part)]
            else:
                return default
            if found is None:
                return default
        return found

    def file(self, *paths: str) -> str:
        """Where the vendor put its file: the first of `paths` that holds an address. A reply with
        none is malformed (ValueError)."""
        if self.rehearsed:
            return self.rehearsed
        for path in paths:
            found = self.get(path)
            if isinstance(found, str) and found:
                return found
        raise ValueError(f"the reply has no file at {', '.join(paths)}")


def raise_for(resp: Any, platform: str) -> None:
    """An HTTP failure in the engine's terms, keeping what the vendor said: a 422 names the field
    it refused, and the status line alone does not."""
    status = int(getattr(resp, "status_code", 200) or 200)
    if status < 400:
        return
    said = str(getattr(resp, "text", "") or "")[:400]
    message = f"{platform} answered {status}" + (f": {said}" if said else "")
    if status in INVALID:
        raise InvalidRequestError(message)
    if status in (401, 403):
        raise UnauthorizedError(message)
    if status == 429:
        raise RateLimitedError(message)
    raise UnavailableError(message)


def request_id(headers: Any) -> str | None:
    for name in REQUEST_ID_HEADERS:
        found = headers.get(name) if hasattr(headers, "get") else None
        if found:
            return str(found)
    return None


class Transport:
    """One vendor platform's way in and out. A subclass implements `_send`, and `_upload` and
    `_download` where the platform moves files; this class makes each rehearsable."""

    platform = "vendor"

    def send(
        self,
        endpoint: str,
        payload: dict[str, Any],
        ctx: Context,
        *,
        model: str | None = None,
        wait: float = TIMEOUT,
        params: dict[str, str] | None = None,
    ) -> Reply:
        dry = rehearsal.active()
        if dry is not None:
            return Reply(rehearsed=dry.request(model or endpoint, payload, attempt=ctx.attempt))
        return self._send(endpoint, payload, ctx, wait=wait, params=params or {})

    def upload(self, path: Path) -> str:
        dry = rehearsal.active()
        if dry is not None:
            return dry.upload(path)
        return self._upload(path)

    def fetch(
        self,
        reply: Reply,
        dst: Path,
        *,
        at: tuple[str, ...] = (),
        encoded: str = "",
        billed: float = 0.0,
    ) -> None:
        """Write the vendor's file to dst: downloaded from the first address in `at`, decoded from
        the base64 field `encoded`, or the reply's own bytes. The vendor has charged already, so a
        file that does not arrive is billed."""
        dry = rehearsal.active()
        if reply.rehearsed and dry is not None:
            dry.stand_in(reply.rehearsed, dst)
            return
        try:
            if at:
                self._download(reply.file(*at), dst)
            elif encoded:
                dst.write_bytes(base64.b64decode(str(reply.get(encoded) or "")))
            else:
                dst.write_bytes(reply.content)
        except (OSError, ValueError, VendorError) as exc:  # after the vendor finished: billed
            raise BilledError(
                billed, f"{self.platform} finished but the file did not arrive: {exc}"
            ) from exc
        if not dst.is_file() or dst.stat().st_size == 0:
            raise BilledError(billed, f"{self.platform} finished but sent an empty file")

    def problems(self, model: str, payload: dict[str, Any]) -> list[str]:
        """What the vendor's published schema would refuse; empty when it publishes none."""
        return []

    def list_price(self, model: str) -> dict[str, Any] | None:
        """This account's price per billing unit for a model, when the vendor says."""
        return None

    # ---------------------------------------------------------------- the platform's own
    def _send(
        self,
        endpoint: str,
        payload: dict[str, Any],
        ctx: Context,
        *,
        wait: float,
        params: dict[str, str],
    ) -> Reply:
        raise NotImplementedError

    def _upload(self, path: Path) -> str:
        raise NotImplementedError(f"{self.platform} takes no uploaded files")

    def _download(self, url: str, dst: Path) -> None:
        with requests.get(url, stream=True, timeout=TIMEOUT) as r:
            raise_for(r, self.platform)
            with open(dst, "wb") as fh:
                for chunk in r.iter_content(1 << 16):
                    fh.write(chunk)


class Https(Transport):
    """A vendor that answers one POST with JSON or with the file itself."""

    def __init__(self, platform: str, base_url: str, headers: Any) -> None:
        self.platform = platform
        self.base_url = base_url.rstrip("/")
        self._headers = headers  # a callable, so the key is read at call time, never stored

    def _send(
        self,
        endpoint: str,
        payload: dict[str, Any],
        ctx: Context,
        *,
        wait: float,
        params: dict[str, str],
    ) -> Reply:
        url = f"{self.base_url}/{endpoint}" if endpoint else self.base_url
        r = requests.post(url, headers=self._headers(), json=payload, params=params, timeout=wait)
        ctx.receipt.request_id = request_id(getattr(r, "headers", None) or {})
        raise_for(r, self.platform)
        kind = str((getattr(r, "headers", None) or {}).get("content-type", ""))
        if "json" in kind or not getattr(r, "content", b""):
            return Reply(data=r.json())
        return Reply(content=r.content)
