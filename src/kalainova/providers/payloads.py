"""A vendor payload as a signature binds it: the same in a rehearsal and in the paid run (ADR 0022).

A rehearsal names an uploaded file by a token, and the paid run by the vendor's address for it or by
the file inlined as a data URI. Both go through `Transport.upload`, which remembers each answer with
the file's hash, so `sealed` can name every uploaded file by its bytes and the two payloads come out
the same. A data URI an adapter inlines itself is named by the hash of its text, so a package stays
readable. `digest` is what a package signs and what the transport checks before it sends.
"""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path
from typing import Any

from ..blobstore import sha256_file

_guard = threading.Lock()
_uploaded: dict[str, str] = {}  # sha256 of an upload's address -> sha256 of the file's bytes


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def remember(address: str, path: Path) -> None:
    """An uploaded file's address, kept with the file's hash, so a payload names it by its bytes."""
    if not path.is_file():  # nothing was read from it, so there are no bytes to name
        return
    found = sha256_file(path)
    with _guard:
        _uploaded[_hash(address)] = found


def sealed(value: Any) -> Any:
    """The payload with every uploaded file named by its bytes and every data URI by its hash."""
    if isinstance(value, dict):
        return {str(k): sealed(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [sealed(v) for v in value]
    if isinstance(value, str):
        with _guard:
            found = _uploaded.get(_hash(value))
        if found:
            return f"file:sha256:{found}"
        if value.startswith("data:"):
            return f"data:sha256:{_hash(value)}"
    return value


def digest(model: str, payload: dict[str, Any]) -> str:
    """The hash a package signs for one request: the model it goes to and the sealed payload."""
    body = {"model": model, "payload": sealed(payload)}
    return _hash(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str))
