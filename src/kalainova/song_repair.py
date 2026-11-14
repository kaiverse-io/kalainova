"""Repair a chosen song take by repainting one section into a new take."""

from __future__ import annotations

import hashlib
import shutil
from typing import Any

from . import takes
from .jobfs import ContractError, Job
from .providers import router

SHOT = "song"


def _repair_span(
    song: dict[str, Any],
    *,
    section_name: str | None,
    start_sec: float | None,
    end_sec: float | None,
) -> tuple[float, float]:
    """Resolve a named section to seconds from its bar count, or use an explicit span."""
    if section_name:
        sections = song.get("sections", [])
        bpm = float(song.get("bpm") or 0)
        if bpm <= 0:
            raise ContractError("section repair needs song.bpm to resolve section bars to seconds")
        elapsed = 0.0
        for item in sections:
            bars = item.get("bars")
            if item.get("kind", "").casefold() == section_name.casefold():
                if not bars:
                    raise ContractError(f"section {section_name!r} has no bar count")
                return elapsed, elapsed + int(bars) * 4 * 60 / bpm
            if bars:
                elapsed += int(bars) * 4 * 60 / bpm
        raise ContractError(f"song has no section {section_name!r}")
    if start_sec is None or end_sec is None:
        raise ContractError("give --section or both --start and --end")
    if start_sec < 0 or end_sec <= start_sec:
        raise ContractError("repair span must have end greater than a nonnegative start")
    return float(start_sec), float(end_sec)


def repair_take(
    job: Job,
    *,
    section: str | None = None,
    start_sec: float | None = None,
    end_sec: float | None = None,
    prompt: str = "",
    take_n: int | None = None,
) -> dict[str, Any]:
    """Repaint one section of a take into a new take, preserving every existing take."""
    from .songs import lyrics_text, style_text

    entry = takes.load(job)["shots"].get(SHOT)
    existing = list(entry.get("takes", [])) if entry else []
    if not existing:
        raise ContractError(f"{job.id}: no song takes to repair")
    target = (
        next((t for t in existing if t["n"] == take_n), None)
        if take_n is not None
        else takes.chosen(job, SHOT)
    )
    if target is None:
        raise ContractError(f"{job.id}: song has no take {take_n}")
    song = job.read("song")
    start, end = _repair_span(song, section_name=section, start_sec=start_sec, end_sec=end_sec)
    original = job.work / target["file"]
    if not original.is_file():
        raise ContractError(f"{job.id}: missing audio for song take {target['n']}: {original}")
    new_n = max(t["n"] for t in existing) + 1
    dst = takes.take_path(job, SHOT, new_n, "-repaired.wav")
    style = prompt or style_text(song)
    generated: tuple[Any, Any] | None = None
    provider_runner = router.first_usable(job, "song")
    can_repaint = bool(
        provider_runner and getattr(provider_runner, "supports_song_repaint", lambda: False)()
    )
    if can_repaint:
        generated = router.generate(
            job,
            "song",
            "song",
            lyrics_text(song),
            dst,
            style=style,
            duration=float(song.get("duration_sec") or end),
            seed=takes.seed_for(prompt or style, new_n),
            task_type="repaint",
            src_audio_path=original,
            repainting_start=start,
            repainting_end=end,
            est={"duration": float(song.get("duration_sec") or end)},
            note="song repair",
        )
    if generated:
        provider, result = generated
        seed = int((result.meta or {}).get("seed", 0))
        extra = {"provider": provider.name, "model": result.model}
    else:
        shutil.copy2(original, dst)
        seed = int(target.get("seed", 0))
        extra = {"provider": "copy", "model": "copy"}
    new_take: dict[str, Any] = {
        "n": new_n,
        "seed": seed,
        "file": str(dst.relative_to(job.work)),
        "sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
        "ok": True,
        "readings": {},
        **extra,
        "prompt": prompt,
        "repaired_from": target["n"],
        "repair_section": section,
        "repair_span": [start, end],
    }
    takes.record(job, SHOT, new_take)
    return new_take
