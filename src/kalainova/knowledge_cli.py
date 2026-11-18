"""CLI for what the engine knows (ADR 0027), so any agent or person on any machine reads it from the
installed tool, never from a checkout's files.

kalainova guide                 every direction, its version and where it comes from
kalainova guide <kind>          one kind of shot's direction, such as `sing`, with why it reads so
kalainova guide <model>         what a model takes: its fields and every limit with its source, or
                                "unknown" where no source states one
kalainova models refresh        each model's recorded prompt limit against its vendor's schema now;
                                reports, and changes nothing
"""

from __future__ import annotations

import argparse
from typing import Any

from . import knowledge
from .jobfs import ContractError

FIELDS = ("image_param", "images_param", "audio_param", "audios_param", "prompt_param",
          "aspect_param", "durations", "min_audio_sec", "short_side")  # fmt: skip


def add_parsers(sub: Any) -> None:
    guide = sub.add_parser("guide")
    guide.add_argument("name", nargs="?", default="", help="a kind of shot (sing) or a model")
    models = sub.add_parser("models")
    models.add_argument("action", choices=["refresh"])


def guide_lines(name: str) -> list[str]:
    """What `kalainova guide` prints."""
    known = knowledge.directions()
    if not name:
        return [f"{d.ref}  ({d.layer})" for d in known.values()]
    if f"perform.{name}" in known or name in known:
        found = known.get(name) or known[f"perform.{name}"]
        return [
            f"{found.ref}  ({found.layer})",
            found.text,
            *([f"why: {found.why}"] if found.why else []),
        ]
    model = knowledge.models().get(name)
    if not model:
        raise ContractError(f"{name} is neither a kind of shot nor a model in the config")
    capability, provider, row = model
    out = [f"{name}: {capability} on {provider}"]
    out += [f"  {key}: {row[key]}" for key in FIELDS if row.get(key) not in (None, "")]
    field = knowledge.prompt_field(capability, row)
    if field:
        out.append(
            f"  prompt ({field}): {knowledge.claim_text(knowledge.limit(row, 'prompt_chars'))}"
        )
    else:
        out.append("  prompt: it takes none")
    return out


def _guide(a: argparse.Namespace) -> int:
    for line in guide_lines(a.name):
        print(line)
    return 0


def _models(a: argparse.Namespace) -> int:
    from .providers import fal_catalog  # reads fal's public schemas, free and with no key

    for line in knowledge.refresh(fal_catalog.input_fields):
        print(line)
    return 0


def dispatch(a: argparse.Namespace) -> int | None:
    command = {"guide": _guide, "models": _models}.get(a.cmd)
    return command(a) if command else None
