"""How a transport moves a call: errors in the engine's terms, replies read by path, a lost file."""

from __future__ import annotations

import pytest
from fakes import Reply, context

from kalainova.providers import transport
from kalainova.providers.contract import (
    BilledError,
    InvalidRequestError,
    RateLimitedError,
    RefusalError,
    UnauthorizedError,
    UnavailableError,
)


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (400, InvalidRequestError),
        (404, InvalidRequestError),
        (422, InvalidRequestError),
        (401, UnauthorizedError),
        (403, UnauthorizedError),
        (429, RateLimitedError),
        (500, UnavailableError),
        (503, UnavailableError),
    ],
)
def test_an_http_failure_is_said_in_the_engines_terms_with_what_the_vendor_said(status, kind):
    with pytest.raises(kind, match=f"answered {status}: the field `tail` is not allowed"):
        transport.raise_for(Reply(status=status, text="the field `tail` is not allowed"), "v")
    transport.raise_for(Reply(status=200), "v")  # a success raises nothing


def test_a_models_moderation_is_a_refusal_and_not_a_malformed_request():
    said = '{"detail":[{"msg":"cannot be processed","type":"content_policy_violation"}]}'
    with pytest.raises(RefusalError, match="answered 422"):
        transport.raise_for(Reply(status=422, text=said), "v")


def test_a_reply_is_read_by_path_and_a_missing_file_is_malformed():
    reply = transport.Reply(data={"images": [{"url": "u"}], "seed": 7})
    assert reply.get("images.0.url") == "u" and reply.get("seed") == 7
    assert reply.get("images.3.url", "none") == "none" and reply.get("video.url") is None
    assert reply.file("video.url", "images.0.url") == "u"
    with pytest.raises(ValueError, match="no file"):
        reply.file("video.url")


def test_a_rehearsed_reply_has_an_address_and_no_values():
    reply = transport.Reply(rehearsed="rehearsal://result/1")
    assert reply.file("anything.url") == "rehearsal://result/1"
    assert reply.get("seed", 3) == 3


class Lost(transport.Transport):
    platform = "lost"

    def _download(self, url, dst):
        raise OSError("connection reset")


def test_a_file_that_does_not_arrive_after_the_vendor_finished_is_billed(tmp_path):
    finished = transport.Reply(data={"video": {"url": "u"}})
    with pytest.raises(BilledError, match="did not arrive") as caught:
        Lost().fetch(finished, tmp_path / "a.mp4", at=("video.url",), billed=1.4)
    assert caught.value.billed == 1.4
    with pytest.raises(BilledError, match="empty file"):
        Lost().fetch(transport.Reply(content=b""), tmp_path / "b.wav", billed=0.2)


def test_the_vendors_request_id_is_kept_even_when_the_call_fails(monkeypatch):
    refused = Reply(status=422, text="bad field")
    refused.headers = {"request-id": "req-9"}
    monkeypatch.setattr(transport.requests, "post", lambda *a, **kw: refused)
    ctx = context()
    with pytest.raises(InvalidRequestError):
        transport.Https("v", "https://v.example", dict).send("x", {}, ctx)
    assert ctx.receipt.request_id == "req-9"
