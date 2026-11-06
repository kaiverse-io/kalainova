"""Prompts are versioned files in prompts/, never strings in code."""

from __future__ import annotations

from .jobfs import REPO


def load(name: str) -> str:
    return (REPO / "prompts" / f"{name}.md").read_text()
