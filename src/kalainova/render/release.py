"""RELEASE FILES. A finished master as the audio files a music distributor accepts.

From the master it writes a 16-bit 44.1 kHz WAV, a FLAC, and a 320 kbps MP3, tags them, embeds a
cover in the FLAC and MP3 when there is one, and keeps the lyrics beside them. A cover that is too
small or not square is warned about, not refused: the distributor's current rule decides.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from .. import media
from ..jobfs import ContractError, Job
from .spec import safe_path

RATE = 44100
MP3_KBPS = "320k"
COVER_MIN_PX = 3000  # a common distributor floor. Re-read the distributor's current rule
FOLDER = "release"
AI_NOTE = "contains AI-generated media"
AI_USE = "ai_use.json"
WORDS = {
    "person": "a person",
    "model": "a model",
    "person_edited_model": "a person, from a model's draft",
}


def ai_use(song: dict[str, Any], made_by: str, master: dict[str, Any] | None) -> dict[str, Any]:
    """What was made by AI, part by part, as a distributor's AI credits ask: the words, the music,
    the vocal, and how it was finished. The answers a form wants are suggested, never sent: the
    person uploading maps them onto the distributor's live form."""
    words = str(song.get("words_by") or "")
    sung = not song.get("instrumental")
    parts: dict[str, Any] = {
        "lyrics": {"by": WORDS.get(words, "not recorded"), "ai": words != "person"}
        if sung
        else None,
        "music": {"by": made_by, "ai": True},
        "vocals": {"by": made_by, "ai": True} if sung else None,
        "mastering": {
            "by": "the engine's own processing, no generative model",
            "chosen_by": (master or {}).get("chosen_by", "the engine's default"),
            "ai": False,
        },
    }
    asks = ["All of the audio"] + (["The lyrics"] if sung and words != "person" else [])
    return {
        "parts": {k: v for k, v in parts.items() if v is not None},
        "suggested_ai_credits": asks,
        "note": "Mixing and mastering by the engine are processing, not generation. Whether the "
        "artist is a person or an AI persona is the uploader's answer, not the engine's.",
    }


def cover_warnings(cover: Path) -> list[str]:
    """What is wrong with a cover for release. An unreadable file is a warning too."""
    try:
        with Image.open(cover) as im:
            width, height = im.size
    except OSError as exc:
        return [f"cover {cover.name} cannot be read: {exc}"]
    found = []
    if width != height:
        found.append(f"cover is {width}x{height}; a release cover is square")
    if min(width, height) < COVER_MIN_PX:
        found.append(f"cover is {width}x{height}; at least {COVER_MIN_PX} px a side is usual")
    return found


def _tags(song: dict[str, Any], lyrics: str) -> dict[str, str]:
    rel = song.get("release") or {}
    tags = {
        "title": song["title"],
        "album": rel.get("album") or song["title"],
        "comment": AI_NOTE,
    }
    if song.get("byline"):
        tags["artist"] = str(song["byline"])
    if rel.get("year"):
        tags["date"] = str(rel["year"])
    if rel.get("track"):
        tags["track"] = str(rel["track"])
    if lyrics.strip():
        tags["lyrics"] = lyrics
    return tags


def _meta_args(tags: dict[str, str]) -> list[str]:
    return [arg for key, value in tags.items() for arg in ("-metadata", f"{key}={value}")]


def _encode(
    master: Path, dst: Path, codec: list[str], tags: dict[str, str], cover: Path | None
) -> None:
    """One output, with the cover attached when the container takes one."""
    cmd = ["-i", str(master)]
    if cover:
        cmd += ["-i", str(cover), "-map", "0:a", "-map", "1:v", "-c:v", "copy"]
        cmd += ["-disposition:v", "attached_pic"]
    cmd += ["-af", f"aresample={RATE}:dither_method=triangular", *codec, *_meta_args(tags)]
    media.run([*cmd, str(dst)])


def write(
    work: Path,
    master: Path,
    song: dict[str, Any],
    *,
    lyrics: str,
    cover: Path | None = None,
    lrc: Path | None = None,
) -> dict[str, Any]:
    """Write the release folder under the job's work folder. Returns its files and warnings."""
    out = work / FOLDER
    out.mkdir(parents=True, exist_ok=True)
    tags = _tags(song, lyrics)
    warnings = cover_warnings(cover) if cover else []
    files: dict[str, str] = {}
    plan: dict[str, tuple[list[str], Path | None]] = {
        "wav": (["-ar", str(RATE), "-c:a", "pcm_s16le"], None),  # a WAV carries no picture
        "flac": (["-sample_fmt", "s16", "-c:a", "flac"], cover),
        "mp3": (["-c:a", "libmp3lame", "-b:a", MP3_KBPS, "-id3v2_version", "3"], cover),
    }
    for kind, (codec, art) in plan.items():
        dst = out / f"final.{kind}"
        _encode(master, dst, codec, tags, art)
        files[kind] = f"{FOLDER}/{dst.name}"
    (out / "lyrics.txt").write_text(lyrics)
    files["lyrics"] = f"{FOLDER}/lyrics.txt"
    if lrc and lrc.exists():
        (out / "lyrics.lrc").write_text(lrc.read_text())
        files["lyrics_timed"] = f"{FOLDER}/lyrics.lrc"
    return {"files": files, "warnings": warnings, "cover": bool(cover)}


def for_job(
    job: Job,
    song: dict[str, Any],
    lyrics: str,
    *,
    made_by: str = "",
    master: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The release folder for a song, with its cover from the job folder when it names one, and
    the record of what in it AI made (`ai_use.json`)."""
    named = (song.get("release") or {}).get("cover")
    cover = safe_path(job.folder, named) if named else None
    if cover and not cover.exists():
        raise ContractError(f"{job.id}: the cover {named} is not in the job folder")
    made = write(
        job.work,
        job.work / "final.wav",
        song,
        lyrics=lyrics,
        cover=cover,
        lrc=job.work / "final.lrc",
    )
    for warning in made["warnings"]:
        print(f"{job.id}: {warning}")
    record = ai_use(song, made_by or "a generative song model", master)
    (job.work / FOLDER / AI_USE).write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n")
    made["files"]["ai_use"] = f"{FOLDER}/{AI_USE}"
    return made
