"""Every agent skill loads in every harness, not only the most forgiving one.

Claude Code reads a skill with no frontmatter, or with YAML a strict parser rejects. Other
harnesses follow the Agent Skills format and refuse such a skill, so these checks are strict.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILLS = sorted((Path(__file__).resolve().parents[1] / ".agents" / "skills").glob("*/SKILL.md"))
NAME = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


def _frontmatter(path: Path) -> dict:
    match = re.match(r"^---\n(.*?)\n---\n", path.read_text(), re.S)
    assert match, f"{path.parent.name}: SKILL.md must open with a --- frontmatter block"
    data = yaml.safe_load(match.group(1))
    assert isinstance(data, dict), f"{path.parent.name}: frontmatter is not a mapping"
    return data


def test_there_are_skills_to_check():
    assert SKILLS


@pytest.mark.parametrize("path", SKILLS, ids=lambda p: p.parent.name)
def test_a_skill_has_a_name_and_a_description_a_strict_harness_accepts(path):
    data = _frontmatter(path)
    name, description = data.get("name"), data.get("description")
    assert name == path.parent.name, f"name {name!r} must match its folder"
    assert NAME.match(name) and len(name) <= 64, f"{name!r}: lowercase words joined by hyphens"
    assert isinstance(description, str) and description.strip(), "a description is required"
    assert len(description) <= 1024, f"description is {len(description)} characters, over 1024"
