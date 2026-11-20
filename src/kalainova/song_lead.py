"""SONG LEAD. What the writer of a fresh song leads from, and the few things it is held to beyond a
song's own rules (ADR 0032).

The writer is the song's creative lead: from the person's brief it decides the idea, the sound,
the tempo, the key, the length and the arrangement, and the engine makes exactly what it wrote.
This module hands it the ground to decide on:

  earlier   the songs its stream already has, newest first, so a new one can stand apart
  window    the lengths the pinned model makes, so the song asks for one it can

and refuses a draft only where it cannot go or would repeat: a length the model does not make, or
the same tempo, key and run of sections as an earlier song of the stream. A draft's brief is also
held to its vendor's guide (draft_problems): short, no tempo in words, brief section notes.
Nothing here chooses a sound; a genre's usual ground is in its profile, held only where the studio
says so (genres).
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import config
from .jobfs import Job

Song = dict[str, Any]
EARLIER_MOST = 12  # the stream's newest songs the writer is shown
# A drafted brief, held to its vendor's guide (ADR 0031): a short brief keeps its few traits clear,
# and a section's note rides on its lyric tag, which the guide shows as a few words.
STYLE_MOST_CHARS = 450
NOTE_MOST_CHARS = 80
TEMPO_IN_WORDS = re.compile(r"\b(?:bpm|beats? per minute)\b", re.I)


def _summary(song: Song, job_id: str) -> Song:
    sections = song.get("sections") or []
    return {
        "job": job_id,
        "title": song.get("title"),
        **({"concept": song["concept"]} if song.get("concept") else {}),
        "bpm": song.get("bpm"),
        "key": song.get("key"),
        "duration_sec": song.get("duration_sec"),
        "sections": ", ".join(f"{s.get('kind')} {s.get('bars', '?')}" for s in sections),
        "style": str(song.get("style") or ""),
    }


def earlier(job: Job, own: bool = True) -> list[Song]:
    """The songs this job's stream already has, newest first: every job of the stream with a song
    file, read as written, this job's own among them when it has one, since a song written again
    replaces it and must stand apart from it too (own=False leaves it out). A job outside a stream
    has none."""
    stream = job.job.get("stream")
    if not stream:
        return []
    found = []
    for folder in (job.studio / "jobs").iterdir():
        song_file, job_file = folder / "song.json", folder / "job.json"
        mine = folder == job.folder
        if (mine and not own) or not song_file.is_file() or not job_file.is_file():
            continue
        try:
            if json.loads(job_file.read_text()).get("stream") != stream:
                continue
            song = json.loads(song_file.read_text())
        except (OSError, ValueError):
            continue
        label = f"{folder.name}, the song this one replaces" if mine else folder.name
        found.append((song_file.stat().st_mtime, _summary(song, label)))
    found.sort(key=lambda pair: pair[0], reverse=True)
    return [summary for _, summary in found[:EARLIER_MOST]]


def window(brief: dict[str, Any]) -> tuple[float, float] | None:
    """The shortest and longest song the brief's pinned model makes, from its row."""
    pinned = brief.get("song_model") or {}
    if not pinned.get("provider") or not pinned.get("model"):
        return None
    spec = config.audio_spec(str(pinned["provider"]), str(pinned["model"]))
    if not spec.get("max_sec"):
        return None
    return float(spec.get("min_sec") or 0), float(spec["max_sec"])


def length_problems(brief: dict[str, Any], song: Song) -> list[str]:
    """A length the pinned model does not make, as the run would ask it, refused before spend."""
    span = window(brief)
    seconds = float(song.get("duration_sec") or brief.get("duration_sec") or 120)
    if span and not span[0] <= seconds <= span[1]:
        return [f"the model makes {span[0]:g} to {span[1]:g} s; the song asks for {seconds:g}"]
    return []


def writer_text(job: Job, own: bool = True) -> str:
    """What the writer is shown to lead from, beyond the brief and the genre."""
    out = []
    span = window(job.job.get("brief") or {})
    if span:
        out.append(
            f'The model that sings it makes {span[0]:g} to {span[1]:g} seconds; "duration_sec" is '
            "inside that."
        )
    songs = earlier(job, own=own)
    if songs:
        out.append(
            "Songs this stream already has, newest first (JSON). Stand apart from them:\n"
            + json.dumps(songs, indent=1, ensure_ascii=False)
        )
    return "\n\n".join(out)


def _kinds(song: Song) -> list[str]:
    return [str(s.get("kind")) for s in song.get("sections") or []]


def problems(job: Job, draft: Song, own: bool = True) -> list[str]:
    """Where a fresh draft cannot go, leaves out its concept, or would repeat a song its stream
    has (own=False: not counting the song it revises)."""
    found = length_problems(job.job.get("brief") or {}, draft)
    if not str(draft.get("concept") or "").strip():
        found.append('write the song\'s "concept": its idea and what sets it apart')
    if not all(s.get("energy") for s in draft.get("sections") or []):
        found.append('give every section its "energy", 1 to 5, as you plan the song\'s arc')
    run = ", ".join(_kinds(draft))
    for other in earlier(job, own=own):
        same = (
            other.get("bpm") == draft.get("bpm")
            and str(other.get("key") or "").casefold() == str(draft.get("key") or "").casefold()
            and ", ".join(k.split(" ")[0] for k in str(other["sections"]).split(", ")) == run
        )
        if same:
            found.append(
                f"this repeats {other['title']!r} ({other['job']}): the same tempo, key and run of "
                "sections. Make this song its own"
            )
        elif str(other.get("title") or "").casefold() == str(draft.get("title") or "").casefold():
            found.append(f"the stream already has a song called {other['title']!r}")
    return found


def draft_problems(song: Song) -> list[str]:
    """Where a drafted song file strays from a brief a model follows well (its vendor's guide):
    a writer's draft is written again for these. A person's own song file is not held to them."""
    found = []
    style = str(song["style"])
    if len(style) > STYLE_MOST_CHARS:
        found.append(
            f"the style runs {len(style)} characters; keep it under {STYLE_MOST_CHARS}, with the "
            "few traits that matter most, and put what changes in each section's style"
        )
    if TEMPO_IN_WORDS.search(style):
        found.append("the style names a tempo; the tempo goes in bpm, as a number")
    long = [
        s["kind"] for s in song.get("sections") or [] if len(s.get("style") or "") > NOTE_MOST_CHARS
    ]
    if long:
        found.append(
            f"a section's style is a few words, under {NOTE_MOST_CHARS} characters: "
            f"{', '.join(long)} run longer"
        )
    return found
