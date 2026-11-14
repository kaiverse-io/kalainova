"""Fixtures any test can ask for by name: the fake studio, and a private home with kit models."""

from __future__ import annotations

import os
from collections.abc import Generator

import pytest
from fakes import studio
from kit_fixtures import root

__all__ = ["root", "studio"]

PROVIDER_KEYS = (
    "FAL_KEY",
    "ELEVENLABS_API_KEY",
    "ELEVENLABS_VOICE_ID",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "EXA_API_KEY",
    "GEMINI_API_KEY",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "ZAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _isolate_provider_keys() -> Generator[None, None, None]:
    """Ensure real provider credentials never reach tests or alter provider availability."""
    saved = {k: os.environ[k] for k in PROVIDER_KEYS if k in os.environ}
    for k in PROVIDER_KEYS:
        os.environ.pop(k, None)
    try:
        yield
    finally:
        for k in PROVIDER_KEYS:
            os.environ.pop(k, None)
        os.environ.update(saved)
