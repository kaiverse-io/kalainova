"""Routes a vendor has said are gone (HTTP 410), so no plan sends to one again.

On 2026-11-20 fal's catalog still listed its Mureka song routes as active, and only a paid submit
found them gone: a 410, billing nothing. A route (a provider and a model) is retired two ways:

- **In config**, `retired: "<date>: <what the vendor said>"` on the model's row in audio_models,
  video_models or sing_models, with `instead: <provider>:<model>` where one carries on. Every
  studio that pulls the engine knows it.
- **In the studio**, the first time a vendor answers 410: the route goes into
  `<studio>/retired.json` with the day and what was said, so every later job stops before it
  reserves money or asks for a sign-off. A person deletes the line if the route comes back.

`why` says why a route cannot be used, or None; the router, a rehearsal and `kalainova pin` ask it.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

from .. import config
from ..jobfs import home

FILE = "retired.json"


def _path() -> Path:
    return home() / FILE


def _studio() -> dict[str, dict[str, Any]]:
    path = _path()
    try:
        return dict(json.loads(path.read_text())) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def _row(provider: str, model: str) -> dict[str, Any]:
    for read in (config.audio_spec, config.video_spec, config.sing_spec):
        row = read(provider, model)
        if row.get("retired"):
            return dict(row)
    return {}


def why(provider: str, model: str | None) -> str | None:
    """Why this route cannot be used: what the vendor said and when, and what carries on."""
    if not model:
        return None
    row = _row(provider, model)
    said = row.get("retired") or (_studio().get(f"{provider}:{model}") or {}).get("said")
    if not said:
        return None
    instead = row.get("instead")
    return f"{provider}:{model} is retired ({said})" + (f"; use {instead}" if instead else "")


def note(provider: str, model: str | None, said: str) -> None:
    """Write down a route the vendor answered 410 for, once, in the studio."""
    if not model or why(provider, model):
        return
    found = _studio()
    found[f"{provider}:{model}"] = {"said": f"{dt.date.today().isoformat()}: {said[:200]}"}
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    spare = path.with_suffix(".json.tmp")
    spare.write_text(json.dumps(found, indent=1, ensure_ascii=False) + "\n")
    spare.replace(path)
