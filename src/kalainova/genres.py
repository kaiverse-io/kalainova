"""GENRES. The studio's genre profiles: where a song of one genre usually sits, and the few things
the studio holds every song of it to.

A profile lives under `genres:` in the studio's private config; the repo names none. A job names
one in `brief.genre` (`kalainova new --genre`, `kalainova request <stream> --media song --genre`).
Then:

  the writer   is handed the profile as the genre's usual ground: a tempo range, keys, a usual
               arrangement, base sound words, what to keep out, the voice. It leads from there and
               chooses this song's own (song_lead, ADR 0032)
  the engine   pins the profile's song model and takes, unless the brief already pins them
  the check    refuses, before any spend, only what the profile `holds`: a tempo outside its
               range, a key not among its keys, another voice, or another run of sections

The profile is the studio's notes on a genre, not a template. A brief says what this song is
about, the writer decides what it is, and a person still chooses among what comes back.
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


def holds(found: Profile | None) -> list[str]:
    """What the studio holds every song of this genre to; the rest of the profile is notes."""
    named = [str(h) for h in (found or {}).get("holds") or []]
    unknown = [h for h in named if h not in HELD]
    if unknown:
        raise ContractError(f"a genre holds only {', '.join(HELD)}, not {', '.join(unknown)}")
    return named


def _tempo(song: dict[str, Any], found: Profile) -> str:
    low, high = (float(v) for v in found.get("bpm") or (0, float("inf")))
    bpm = song.get("bpm")
    if bpm is None or not low <= float(bpm) <= high:
        return f"the genre holds its tempo to {low:g} to {high:g} bpm; the song asks {bpm}"
    return ""


def _key(song: dict[str, Any], found: Profile) -> str:
    keys = [str(k).casefold() for k in found.get("keys") or []]
    if keys and str(song.get("key") or "").casefold() not in keys:
        held = ", ".join(found["keys"])
        return f"the genre holds its keys to {held}; the song is in {song.get('key')}"
    return ""


def _voice(song: dict[str, Any], found: Profile) -> str:
    voice = found.get("vocal_gender")
    if voice and not song.get("instrumental") and song.get("vocal_gender") != voice:
        return f"the genre holds its voice {voice}; the song asks {song.get('vocal_gender')}"
    return ""


def _sections(song: dict[str, Any], found: Profile) -> str:
    usual = [str(s.get("kind")) for s in found.get("structure") or []]
    if usual and [str(s.get("kind")) for s in song["sections"]] != usual:
        return f"the genre holds its sections to {', '.join(usual)}"
    return ""


HELD = {"bpm": _tempo, "key": _key, "vocal_gender": _voice, "structure": _sections}


def problems(song: dict[str, Any], found: Profile | None) -> list[str]:
    """Where a song file leaves what its genre's profile holds. Each is refused before any spend."""
    if not found:
        return []
    return [said for said in (HELD[h](song, found) for h in holds(found)) if said]


def writer_text(brief: dict[str, Any]) -> str:
    """The profile as the writer is handed it, or nothing when the brief names no genre."""
    found = for_brief(brief)
    if not found:
        return ""
    shown = {k: v for k, v in found.items() if k not in ("song_model", "takes", "holds")}
    held = holds(found)
    return prompts.load("genre_profile").format(
        profile=json.dumps(shown, indent=2, ensure_ascii=False),
        holds=f"The studio holds every song of it to its {', '.join(held)}; a song outside them is "
        "refused. The rest is yours to choose."
        if held
        else "The studio holds nothing of it: every choice is yours.",
    )
