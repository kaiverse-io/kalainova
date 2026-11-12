"""The OpenAI-compatible LLM adapter, against a faked HTTP layer. No network."""

from __future__ import annotations

import pytest
from fakes import Reply

from kalainova import config
from kalainova.providers import base, compat


def _studio(monkeypatch, **sections):
    monkeypatch.setattr(config, "studio", lambda: sections)


@pytest.fixture
def sent(monkeypatch):
    calls: list[dict] = []
    replies: list[Reply] = []

    def post(url, **kw):
        calls.append({"url": url, **kw})
        return replies.pop(0)

    monkeypatch.setattr(compat.requests, "post", post)
    return calls, replies


def _answer(text="hi", p=1000, c=500):
    return Reply(
        body={
            "choices": [{"message": {"content": text}}],
            "usage": {"prompt_tokens": p, "completion_tokens": c},
        }
    )


def test_the_four_vendors_are_registered_for_llm_only():
    for name in ("gemini", "groq", "openrouter", "zai"):
        assert base.get(name).capabilities == ("llm",)
    assert base.get("groq").env_key == "GROQ_API_KEY"
    assert base.get("zai").env_key == "ZAI_API_KEY"
    assert base.get("gemini").env_key == "GEMINI_API_KEY"
    assert base.get("openrouter").env_key == "OPENROUTER_API_KEY"


def test_a_vendor_without_a_model_is_not_ready_even_with_a_key(monkeypatch):
    _studio(monkeypatch)
    monkeypatch.setenv("GROQ_API_KEY", "k")
    assert not base.get("groq").available()
    assert "models.groq.llm" in base.get("groq").missing_env()[0]


def test_it_posts_the_chat_shape_to_the_vendor_url_with_a_bearer_key(monkeypatch, sent):
    calls, replies = sent
    _studio(
        monkeypatch,
        models={"groq": {"llm": "m-1"}},
        prices={"groq": {"llm": {"input_per_mtok": 2.0, "output_per_mtok": 4.0}}},
    )
    monkeypatch.setenv("GROQ_API_KEY", "secret")
    replies.append(_answer("done"))
    res = base.get("groq").llm("Say it.", system="Be brief.", max_tokens=50)
    assert calls[0]["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer secret"
    assert calls[0]["json"] == {
        "model": "m-1",
        "max_tokens": 50,
        "messages": [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Say it."},
        ],
    }
    assert res.text == "done"
    assert res.model == "m-1"
    assert res.cost == pytest.approx(1000 / 1e6 * 2.0 + 500 / 1e6 * 4.0)


def test_a_free_tier_costs_nothing_and_estimates_zero(monkeypatch, sent):
    _, replies = sent
    _studio(
        monkeypatch,
        models={"gemini": {"llm": "m"}},
        prices={"gemini": {"llm": {"free": True}}},
    )
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    replies.append(_answer())
    provider = base.get("gemini")
    assert provider.free
    assert provider.estimate("llm") == 0.0
    assert provider.llm("x").cost == 0.0


def test_images_go_as_data_urls(monkeypatch, sent, tmp_path):
    calls, replies = sent
    _studio(monkeypatch, models={"openrouter": {"llm": "m"}})
    monkeypatch.setenv("OPENROUTER_API_KEY", "k")
    img = tmp_path / "a.png"
    img.write_bytes(b"png")
    replies.append(_answer())
    base.get("openrouter").llm("Look.", images=[img])
    parts = calls[0]["json"]["messages"][0]["content"]
    assert parts[0] == {"type": "text", "text": "Look."}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_a_vendor_failure_is_raised(monkeypatch, sent):
    _, replies = sent
    _studio(monkeypatch, models={"zai": {"llm": "m"}})
    monkeypatch.setenv("ZAI_API_KEY", "k")
    replies.append(Reply(status=429))
    with pytest.raises(OSError):
        base.get("zai").llm("x")


def test_the_config_can_add_a_vendor_or_move_a_url(monkeypatch):
    _studio(
        monkeypatch,
        openai_compat={
            "groq": {"base_url": "https://proxy.example/v1/"},
            "mine": {"base_url": "https://mine.example/v1", "env_key": "MINE_KEY"},
        },
    )
    vendors = compat._vendors()
    assert vendors["groq"]["base_url"] == "https://proxy.example/v1/"
    assert vendors["groq"]["env_key"] == "GROQ_API_KEY"
    assert vendors["mine"]["env_key"] == "MINE_KEY"
    assert compat.OpenAICompat("mine", **vendors["mine"]).base_url == "https://mine.example/v1"
