"""One adapter for any vendor that serves the OpenAI chat-completions shape (capability `llm`).

Each vendor is a name, a base URL, and the env var that holds its key. Defaults below cover
Gemini's OpenAI-compatible endpoint, Groq, OpenRouter and z.ai; `openai_compat:` in
config/studio.yaml adds or overrides a vendor without code. Model ids and prices live in `models:`
and `prices:` under the vendor's name, and stay empty until the operator fills them from the
vendor's current docs. A vendor with no model set is not ready, so it is never tried by accident.
A price row of `{free: true}` marks a free tier: it costs nothing, but a human still reads the
vendor's terms and rate limits.
"""

from __future__ import annotations

import base64
import os
from functools import partial
from pathlib import Path
from typing import Any

import requests

from .. import config
from .base import Provider, Result, register

TIMEOUT = 600

DEFAULTS: dict[str, dict[str, str]] = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "env_key": "GEMINI_API_KEY",
    },
    "groq": {"base_url": "https://api.groq.com/openai/v1", "env_key": "GROQ_API_KEY"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "env_key": "OPENROUTER_API_KEY"},
    "zai": {"base_url": "https://api.z.ai/api/paas/v4", "env_key": "ZAI_API_KEY"},
}


class OpenAICompat(Provider):
    """Text and vision through any OpenAI-compatible chat endpoint."""

    capabilities = ("llm", "judge")
    synthetic = False

    def __init__(self, name: str, base_url: str, env_key: str) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.env_key = env_key

    @property
    def free(self) -> bool:  # type: ignore[override]  # reason: the base class keeps a plain flag
        return bool(config.price_for(self.name, "llm").get("free"))

    def missing_env(self) -> list[str]:
        missing = super().missing_env()
        if not config.model_for(self.name, "llm"):
            missing.append(f"models.{self.name}.llm in config/studio.yaml")
        return missing

    def llm(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 4000,
        images: list[Path] | None = None,
        **kw: Any,
    ) -> Result:
        model = kw.get("model") or config.model_for(self.name, "llm")
        if not model:
            raise ValueError(f"{self.name}: set models.{self.name}.llm in config/studio.yaml")
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for img in images or []:
            mime = "image/jpeg" if img.suffix in (".jpg", ".jpeg") else "image/png"
            blob = base64.b64encode(img.read_bytes()).decode()
            content.append(
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{blob}"}}
            )
        messages: list[dict[str, Any]] = [{"role": "system", "content": system}] if system else []
        messages.append({"role": "user", "content": content if images else prompt})
        r = requests.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {os.environ[str(self.env_key)]}",
                "content-type": "application/json",
            },
            json={"model": model, "max_tokens": max_tokens, "messages": messages},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        text = str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "")
        u = data.get("usage") or {}
        p = config.price_for(self.name, "llm", model)
        cost = u.get("prompt_tokens", 0) / 1e6 * p.get("input_per_mtok", 0) + u.get(
            "completion_tokens", 0
        ) / 1e6 * p.get("output_per_mtok", 0)
        return Result(text=text, cost=cost, model=str(model), meta={"usage": u})

    judge = llm


def _vendors() -> dict[str, dict[str, str]]:
    merged = {name: dict(spec) for name, spec in DEFAULTS.items()}
    for name, spec in (config.studio().get("openai_compat") or {}).items():
        merged[name] = {**merged.get(name, {}), **(spec or {})}
    return merged


def _register_all() -> None:
    for name, spec in _vendors().items():
        if spec.get("base_url") and spec.get("env_key"):
            register(partial(OpenAICompat, name, spec["base_url"], spec["env_key"]))


_register_all()
