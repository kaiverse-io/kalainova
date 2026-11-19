"""GENRES. The studio's genre profiles: what a song of one genre is written and made inside.

A profile lives under `genres:` in the studio's private config; the repo names none. A job names
one in `brief.genre` (`kalainova new --genre`, `kalainova request --media song --genre`). Then:

  the writer   is handed the profile and writes inside it: a tempo in its range, one of its keys,
               its structure and bar counts, its base style before its own words, its voice
  the engine   pins the profile's song model and takes, unless the brief already pins them
  the check    refuses, before any spend, a song file whose tempo is outside the profile's range,
               whose key is not one of its keys, or whose voice is not the profile's

The profile is the studio's decision about what its songs are. A brief still says what this one is
about, and a person still chooses among what comes back.
"""

from __future__ import annotations

import json
from typing import Any

from . import config, prompts
from .jobfs import ContractError

Profile = dict[str, Any]


def profile(name: str) -> Profile:
    """One genre's profile, refused by name when the studio has none."""
    known = dict(config.studio().get("genres") or {})
    if name not in known:
        have = ", ".join(sorted(known)) or "none: add them under genres in the studio config"
        raise ContractError(f"no genre profile {name!r}; the studio has {have}")
    return dict(known[name])


def for_brief(brief: dict[str, Any]) -> Profile | None:
    name = brief.get("genre")
    return profile(str(name)) if name else None


def apply(brief: dict[str, Any], name: str) -> dict[str, Any]:
    """The brief with its genre named, and the profile's song model, takes and length where the
    brief does not already set them. A person's own pin always stands."""
    found = profile(name)
    brief["genre"] = name
    if found.get("song_model") and not brief.get("song_model"):
        brief["song_model"] = dict(found["song_model"])
    if found.get("takes") and "takes" not in brief:
        brief["takes"] = brief["max_takes"] = int(found["takes"])
    if found.get("duration_sec"):
        brief["duration_sec"] = int(found["duration_sec"])
    return brief


def problems(song: dict[str, Any], found: Profile | None) -> list[str]:
    """Where a song file leaves its genre's profile. Each is refused before any spend."""
    if not found:
        return []
    out = []
    span = found.get("bpm")
    bpm = song.get("bpm")
    if span:
        low, high = float(span[0]), float(span[1])
        if bpm is None or not low <= float(bpm) <= high:
            out.append(f"the genre's tempo is {low:g} to {high:g} bpm; the song asks for {bpm}")
    keys = [str(k).casefold() for k in found.get("keys") or []]
    if keys and str(song.get("key") or "").casefold() not in keys:
        out.append(
            f"the genre's keys are {', '.join(found['keys'])}; the song is in {song.get('key')}"
        )
    voice = found.get("vocal_gender")
    if voice and not song.get("instrumental") and song.get("vocal_gender") != voice:
        out.append(f"the genre's voice is {voice}; the song asks for {song.get('vocal_gender')}")
    return out


def writer_text(brief: dict[str, Any]) -> str:
    """The profile as the writer is handed it, or nothing when the brief names no genre."""
    found = for_brief(brief)
    if not found:
        return ""
    shown = {k: v for k, v in found.items() if k not in ("song_model", "takes")}
    return prompts.load("genre_profile").format(
        profile=json.dumps(shown, indent=2, ensure_ascii=False)
    )
