"""Prompts are versioned files in prompts/, never strings in code."""

from __future__ import annotations

from . import resources


def load(name: str) -> str:
    return resources.path("prompts", f"{name}.md").read_text()
