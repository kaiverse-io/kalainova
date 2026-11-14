"""Every paid call the config can route to has a price, so a capped job can reserve for it.

A paid provider with no price row is refused under a cost cap (`router.generate`), and every paid
job has a cap. A missing row therefore turns a step off silently: the model check had no `judge`
row, and a row for fal's transcription once slid under the free `local` provider.
"""

from __future__ import annotations

import pytest

from kalainova import config
from kalainova.providers import base, remote

base.names()
ROUTES = [
    (capability, name)
    for capability, names in config.studio().get("preference", {}).items()
    for name in names
]


@pytest.mark.parametrize(("capability", "name"), ROUTES, ids=[f"{c}-{n}" for c, n in ROUTES])
def test_every_paid_provider_in_the_preference_order_can_price_a_call(capability, name):
    provider = base.get(name)
    if capability not in provider.capabilities or provider.free:
        return
    assert provider.estimate(capability) is not None, (
        f"{name} has no price for {capability} in config/studio.yaml, "
        "so a job with a cost cap refuses it"
    )


class _Answered:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "content": [{"type": "text", "text": "{}"}],
            "usage": {"input_tokens": 1_000_000, "output_tokens": 100_000},
        }


@pytest.mark.parametrize(
    ("method", "model", "expected"),
    [
        ("judge", config.model_for("anthropic", "judge"), 1.0 + 0.5),
        ("llm", config.model_for("anthropic", "llm"), 4.0 + 2.0),
    ],
)
def test_a_call_settles_at_the_price_of_the_model_that_answered(
    monkeypatch, method, model, expected
):
    sent: dict = {}

    def post(url, headers, json, timeout):
        sent.update(json)
        return _Answered()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(remote.requests, "post", post)
    result = getattr(remote.Anthropic(), method)("check this")
    assert sent["model"] == model
    assert result.cost == pytest.approx(expected)
