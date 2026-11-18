"""What a vendor's account has left: read where the vendor says; unreadable, it never blocks."""

from __future__ import annotations

import io

from kalainova.providers import balances


def test_fal_balance_is_read_with_the_key_and_unknown_without_it(monkeypatch):
    assert balances._fal() is None, "no key loaded, no read"
    monkeypatch.setenv("FAL_KEY", "k")
    asked = {}

    def answer(request, timeout):
        asked["auth"] = request.headers["Authorization"]
        return io.BytesIO(b"5.016305489\n")

    monkeypatch.setattr(balances.urllib.request, "urlopen", answer)
    assert balances._fal() == 5.016305489 and asked["auth"] == "Key k"

    def refused(request, timeout):
        raise OSError("403")

    monkeypatch.setattr(balances.urllib.request, "urlopen", refused)
    assert balances._fal() is None, "a failed read is unknown, not zero"


def test_a_short_balance_is_said_and_an_unknown_one_is_not(monkeypatch):
    monkeypatch.setattr(balances, "READERS", {"v": lambda: 1.0})
    assert balances.short("v", 2.0, fresh=True) == (
        "v's balance is $1.00, below the $2.00 needed; top it up first"
    )
    assert balances.short("v", 0.5, fresh=True) is None
    assert balances.short("unlisted", 99.0) is None
