"""Repair a chosen song take by repainting one section into a new take."""

from __future__ import annotations

import hashlib
from typing import Any

from . import config, media, takes
from .bar import song as musicbar
from .jobfs import ContractError, Job
from .providers import base, router

SHOT = "song"


def _repainter(job: Job) -> str:
    """The first ready song provider that can repaint a span. Refused before any work if none can.

    A repair never falls back to copying the take: a copy would be recorded as a repaired take
    that changed nothing.
    """
    tried = []
    for name in config.preference("song", job.job):
        try:
            p = base.get(name)
        except KeyError:
            continue
        if "song" not in p.capabilities or not p.available("song"):
            continue
        if getattr(p, "supports_song_repaint", lambda: False)():
            return name
        tried.append(name)
    raise ContractError(
        f"{job.id}: no ready song provider can repaint a section "
        f"(ready: {', '.join(tried) or 'none'}). The local ACE-Step route can: "
        "set models.mac.song to ace-step and put mac in the song preference."
    )


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
    painter = _repainter(job)
    new_n = max(t["n"] for t in existing) + 1
    dst = takes.take_path(job, SHOT, new_n, "-repaired.wav")
    style = prompt or style_text(song)
    seconds = media.duration(original)
    provider, result = router.generate(
        job,
        "song",
        "song",
        lyrics_text(song),
        dst,
        style=style,
        duration=seconds,
        seed=takes.seed_for(prompt or style, new_n),
        task_type="repaint",
        src_audio_path=original,
        repainting_start=start,
        repainting_end=end,
        est={"duration": seconds},
        only=[painter],
        note="song repair",
    )
    # measured like any take, so the person compares two takes on the same readings
    report = musicbar.measure(dst, song, None)
    misses = [r["id"] for r in report["readings"] if not r["ok"]]
    new_take: dict[str, Any] = {
        "n": new_n,
        "seed": int((result.meta or {}).get("seed", 0)),
        "file": str(dst.relative_to(job.work)),
        "sha256": hashlib.sha256(dst.read_bytes()).hexdigest(),
        "ok": not misses,
        "readings": {
            "score": musicbar.score(report),
            "misses": misses,
            "readings": report["readings"],
        },
        "provider": provider.name,
        "model": result.model,
        "prompt": prompt,
        "repaired_from": target["n"],
        "repair_section": section,
        "repair_span": [start, end],
    }
    takes.record(job, SHOT, new_take)
    return new_take
