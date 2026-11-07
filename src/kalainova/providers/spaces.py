"""Hosted Gradio apps, free and rate limited, for models this machine cannot run.

Words sent here leave the machine and reach whoever runs the app, so it is never listed by default:
name it in a job's providers. How each app takes a request lives in config/studio.yaml, because a
community app can change at any time. Needs the "spaces" extra.
"""

from __future__ import annotations

import importlib
import importlib.util
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .. import config, media
from .base import Provider, Result, register


def _first_path(output: Any) -> str:
    """The audio file in whatever shape an app returns: a path, a dict, or a tuple holding one."""
    if isinstance(output, str):
        return output
    if isinstance(output, dict) and output.get("path"):
        return str(output["path"])
    if isinstance(output, Iterable):
        for item in output:
            if isinstance(item, str | dict):
                return _first_path(item)
    raise ValueError(f"the app returned no file: {str(output)[:200]}")


def _song_request(
    spec: dict[str, Any], lyrics: str, style: str, duration: float | None, seed: int | None
) -> dict[str, Any]:
    """The app's own names for what is being asked. A request an app cannot take leaves it out."""
    request = {
        str(spec["lyrics_param"]): lyrics,
        str(spec["style_param"]): style,
        **dict(spec.get("extra") or {}),
    }
    if duration and spec.get("duration_param"):
        request[str(spec["duration_param"])] = int(duration)
    if seed is not None and spec.get("seed_param"):
        request[str(spec["seed_param"])] = seed
    return request


@register
class Spaces(Provider):
    name = "spaces"
    capabilities = ("song",)
    free = True

    def missing_env(self) -> list[str]:
        if importlib.util.find_spec("gradio_client"):
            return []
        return ["gradio_client (install the spaces extra)"]

    def song(
        self, lyrics: str, dst: Path, *, style: str = "", duration: float | None = None, **kw: Any
    ) -> Result:
        spec = config.space_spec("song")
        if not spec.get("space"):
            raise ValueError("models.spaces.song names no app in config/studio.yaml")
        request = _song_request(spec, lyrics, style, duration, kw.get("seed"))
        client = importlib.import_module("gradio_client").Client(spec["space"], verbose=False)
        made = _first_path(client.predict(api_name=spec["api_name"], **request))
        media.run(["-i", made, "-ar", "48000", "-ac", "2", str(dst)])
        meta = {"seed": kw["seed"]} if kw.get("seed") is not None else {}
        return Result(path=dst, model=str(spec["space"]), meta=meta)
