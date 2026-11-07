"""How a clip is priced, and how a queued call to fal ends: done, refused, or timed out."""

from __future__ import annotations

import pytest
from fakes import Reply

from kalainova.providers import fal


@pytest.mark.parametrize(
    ("request_", "expected"),
    [
        ({}, "video"),
        ({"image": True}, "image_to_video"),
        ({"references": True}, "reference_to_video"),
        ({"references": True, "image": True}, "reference_to_video"),
    ],
)
def test_a_clip_is_priced_by_what_it_was_given(request_, expected):
    assert fal.Fal().price_key("video", request_) == expected


def test_only_a_clip_changes_its_price_key():
    assert fal.Fal().price_key("image", {"references": True}) == "image"


class Queue:
    """The fal queue, as a list of replies to each poll."""

    def __init__(self, monkeypatch, statuses):
        self.statuses = list(statuses)
        self.cancelled = []
        monkeypatch.setenv("FAL_KEY", "k")
        monkeypatch.setattr(fal.time, "sleep", lambda s: None)
        monkeypatch.setattr(fal.requests, "post", self.post)
        monkeypatch.setattr(fal.requests, "get", self.get)
        monkeypatch.setattr(fal.requests, "put", lambda url, **k: self.cancelled.append(url))

    def post(self, url, **kw):
        body = {"status_url": "s", "response_url": "r", "cancel_url": "c"}
        return Reply(body=body)

    def get(self, url, **kw):
        if url == "r":
            return Reply(body={"done": True})
        return self.statuses.pop(0)


def test_a_queued_call_polls_until_the_model_is_done(monkeypatch):
    Queue(monkeypatch, [Reply(body={"status": "IN_QUEUE"}), Reply(body={"status": "COMPLETED"})])
    assert fal.Fal()._run("m", {}) == {"done": True}


def test_a_bad_key_fails_at_once_and_not_after_the_timeout(monkeypatch):
    Queue(monkeypatch, [Reply(status=401)])
    with pytest.raises(OSError, match="401"):
        fal.Fal()._run("m", {})


def test_a_timed_out_call_is_cancelled_so_nobody_pays_for_it(monkeypatch):
    queue = Queue(monkeypatch, [])
    with pytest.raises(TimeoutError):
        fal.Fal()._run("m", {}, timeout=-1)
    assert queue.cancelled == ["c"]
