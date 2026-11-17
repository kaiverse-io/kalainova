"""What a vendor's account has left to spend, where the vendor will say.

A paid stage that runs out of money part way stops with half a piece made. So the balance is read
when a package is built, again when a person signs it off, and before each paid call. A balance that
cannot be read, because the vendor has no such read, no key is loaded, or the read fails, is None,
and None never blocks: the vendor's own refusal stays the backstop, and what it refuses is not
billed.
"""

from __future__ import annotations

import os
import time
import urllib.request
from collections.abc import Callable

CACHE_SEC = 60.0  # a balance read this recently stands for the next call
FAL_BALANCE_URL = (
    "https://rest.alpha.fal.ai/billing/user_balance"  # answers this key; v1 billing 403s
)

_seen: dict[str, tuple[float, float | None]] = {}


def _fal() -> float | None:
    key = os.environ.get("FAL_KEY")
    if not key:
        return None
    ask = urllib.request.Request(FAL_BALANCE_URL, headers={"Authorization": f"Key {key}"})
    try:
        with urllib.request.urlopen(ask, timeout=10) as reply:  # noqa: S310 - a fixed https URL
            return float(reply.read().decode().strip())
    except (OSError, ValueError):
        return None


READERS: dict[str, Callable[[], float | None]] = {"fal": _fal}


def of(provider: str, *, fresh: bool = False) -> float | None:
    """The provider's balance in dollars, or None when it cannot be read."""
    read = READERS.get(provider)
    if read is None:
        return None
    at, found = _seen.get(provider, (0.0, None))
    if fresh or time.monotonic() - at > CACHE_SEC:
        found = read()
        _seen[provider] = (time.monotonic(), found)
    return found


def short(provider: str, needed: float, *, fresh: bool = False) -> str | None:
    """Why `needed` dollars cannot be spent at this provider now; None when they can, or unknown."""
    left = of(provider, fresh=fresh)
    if left is None or left + 1e-6 >= needed:
        return None
    return f"{provider}'s balance is ${left:.2f}, below the ${needed:.2f} needed; top it up first"
