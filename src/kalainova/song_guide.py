"""A paid song that follows a track made before anything was paid for (ADR 0016's free draft).

brief.song_guide names another song job of this studio and how its track is used:

- `reference`: a clip of it, whose sound and groove the new song takes up;
- `remix`: the whole of it, sung and produced again from the words and the style.

The engine owns the guide: it opens the other job, checks the studio may use its track, cuts the
clip the pinned model takes (where the most words are heard sung, on a bar), and records both
files by their bytes. The provider only uploads the clip. A model that takes no such track is
refused before anything is cut or sent.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np

from . import media, takes
from .bar import song as musicbar
from .blobstore import sha256_file
from .jobfs import ContractError, Job, open_job
from .providers import base
from .providers.contract import GUIDE_USES, Guide, Pin

SHOT = "song"
RIGHTS = ("owned", "licensed")


def window(source: Job, length: float) -> tuple[float, float]:
    """Where a clip of a guide track is cut: on a bar, where the most of its words are heard sung,
    the chorus counting double. The start of the track when it has no bars or nothing was heard."""
    from .editor import musiccuts
    from .editor.singing import best_window

    final = source.artifact()
    total = media.duration(final)
    if total <= length:
        return 0.0, total
    take = takes.chosen(source, SHOT) or {}
    played = source.work / str(take.get("file", ""))
    grid = played.with_suffix(".grid.json")
    found = json.loads(grid.read_text()) if grid.is_file() else musiccuts.analyse(final, total)
    heard = (musicbar.saved_heard(played) if take else None) or []
    try:
        start, _ = best_window(found, length, source.read("song"), heard, (np.zeros(1), 1.0))
    except ContractError:
        start = 0.0
    start = min(start, total - length)
    return start, start + length


def _asked(job: Job, brief: dict[str, Any], pin: Pin | None) -> tuple[str, Job, float]:
    asked = brief.get("song_guide")
    if not isinstance(asked, dict) or not asked.get("job") or asked.get("use") not in GUIDE_USES:
        raise ContractError(
            f'brief.song_guide is {{"job": "...", "use": "{" or ".join(GUIDE_USES)}"}}'
        )
    use = str(asked["use"])
    if pin is None:
        raise ContractError(
            f"{job.id}: a song that follows a track names its model (brief.song_model), so the "
            "track goes only to a model that takes it"
        )
    takes_in = base.get(pin.provider).inputs("song", pin.model).guides
    if use not in takes_in:
        raise ContractError(
            f"{job.id}: {pin.model} takes no {use} track; it takes: "
            f"{', '.join(sorted(takes_in)) or 'none'}"
        )
    source = open_job(job.studio / "jobs" / str(asked["job"]))
    if source.id == job.id:
        raise ContractError(f"{job.id}: a song cannot follow itself")
    if source.job.get("rights") not in RIGHTS:
        raise ContractError(
            f"{job.id}: {source.id} is {source.job.get('rights')!r}; a guide must be "
            f"{' or '.join(RIGHTS)}"
        )
    if not source.artifact().exists():
        raise ContractError(f"{job.id}: {source.id} has no finished song to follow; make it first")
    return use, source, float(takes_in[use])


def follow(job: Job, brief: dict[str, Any], pin: Pin | None) -> tuple[Guide | None, dict[str, Any]]:
    """The guide for a song's takes and its record, or (None, {}) when the brief names none."""
    if not brief.get("song_guide"):
        return None, {}
    use, source, clip_sec = _asked(job, brief, pin)
    final = source.artifact()
    start, end = window(source, clip_sec) if clip_sec else (0.0, media.duration(final))
    clip = job.work / f"guide.{use}.m4a"
    cut = ["-ss", f"{start:.3f}", "-t", f"{end - start:.3f}"] if clip_sec else []
    media.run(
        [*cut, "-i", str(final), "-map_metadata", "-1", "-ac", "2", "-ar", "48000",
         "-c:a", "aac", "-b:a", "256k", "-fflags", "+bitexact", "-flags:a", "+bitexact",
         str(clip)]
    )  # fmt: skip
    take = takes.chosen(source, SHOT) or {}
    record = {
        "job": source.id,
        "use": use,
        "source_sha256": sha256_file(final),
        "take": take.get("n"),
        "chosen_by": takes.load(source)["shots"].get(SHOT, {}).get("chosen_by"),
        "model": take.get("model"),
        "start_sec": round(start, 3),
        "end_sec": round(end, 3),
        "file": clip.name,
        "sha256": sha256_file(clip),
    }
    return Guide(source=clip, use=use), record
