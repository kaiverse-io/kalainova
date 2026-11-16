"""Fixtures any test can ask for by name: the fake studio, and a private home with kit models."""

from __future__ import annotations

import os
from collections.abc import Generator

# A shell that sourced a lab's settings must not reach the tests. This runs before any test module
# is imported, because some read the config at import, and a worker keeps what it read first.
LAB_SETTINGS = (
    "KALAINOVA_HOME",
    "KALAINOVA_CONFIG",
    "KALAINOVA_OUT",
    "KALAINOVA_MLX_PYTHON",
    "KALAINOVA_SONG_PYTHON",
    "KALAINOVA_SONG_CHECKPOINT",
)
for _name in LAB_SETTINGS:
    os.environ.pop(_name, None)

import pytest  # noqa: E402 - after the lab's settings are cleared, on purpose
from fakes import studio  # noqa: E402 - after the lab's settings are cleared, on purpose
from kit_fixtures import root  # noqa: E402 - after the lab's settings are cleared, on purpose

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


@pytest.fixture(autouse=True)
def _no_lab_and_output_in_a_temp_folder(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A shell that sourced a lab's settings must not point tests at a private home, its config,
    or its models; and what a test renders goes to a folder of its own, never the repo's out/.
    A fixture that wants a home or an output folder sets its own after this one."""
    for name in LAB_SETTINGS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path_factory.mktemp("out")))
