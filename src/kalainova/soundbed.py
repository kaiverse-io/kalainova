"""The sound under a piece: a kit's fixed file, a finished track, or a bed made for it."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import kits, media, shotmake
from .blobstore import sha256_file
from .jobfs import Job

Fields = dict[str, Any]
Gen = Callable[..., tuple[Any, Any]]
Add = Callable[..., Any]


def _kit_audio(root: Path, entry: Fields, dst: Path, seconds: float) -> None:
    """A fixed sound from the kit, looped or trimmed to length. Never regenerated."""
    src = kits.blob_path(root, entry)
    length = ["-stream_loop", "-1", "-i", str(src), "-t", f"{seconds:.3f}"]
    media.run([*length, "-ar", "48000", "-ac", "2", str(dst)])


def bed(
    job: Job,
    asset_id: str,
    role: str,
    fixed: Fields | None,
    secs: float,
    add: Add,
    gen: Gen,
    data: Fields,
) -> None:
    """The music bed or the transition: the kit's file when it fixes one, otherwise generated."""
    dst = job.work / f"{asset_id}.wav"
    common = {"id": asset_id, "kind": "audio", "role": role, "path": dst.name, "synthetic": True}
    if fixed:
        _kit_audio(job.folder.parents[1], fixed, dst, secs)
        add(
            **common,
            duration_sec=media.duration(dst),
            rights=shotmake.rights(data),
            provider="kit",
            model="kit",
            provenance={"kit_sha256": fixed["sha256"]},
        )
        return
    brief = data.get("brief") or {}
    text = (
        (brief.get("music") or "warm modern instrumental bed, steady pulse, no vocals")
        if role == "music"
        else "soft cinematic whoosh transition"
    )
    p, res = gen(role, role, text, dst, duration=secs, est={"duration": secs})
    add(
        **common,
        duration_sec=media.duration(dst),
        rights=shotmake.rights(data),
        provider=p.name,
        model=res.model,
        provenance=shotmake.made(res),
        prompt=text if role == "music" else None,
    )


def track_from_job(job: Job, track: str, total: float, add: Add, data: Fields) -> None:
    """A finished piece of music from another job: the picture is cut to it, and it is not remade"""
    src = job.work / track
    dst = job.work / "music.wav"
    media.run(["-i", str(src), "-t", f"{total + 1.0:.3f}", "-ar", "48000", "-ac", "2", str(dst)])
    add(
        id="music",
        kind="audio",
        role="music",
        path=dst.name,
        duration_sec=media.duration(dst),
        rights=shotmake.rights(data),
        provider="track",
        model=(data.get("brief") or {}).get("track_model", "a finished track"),
        provenance={"source_sha256": sha256_file(src), "parent_job": data.get("parent_job_id")},
        synthetic=True,
    )
