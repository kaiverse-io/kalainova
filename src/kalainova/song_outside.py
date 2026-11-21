"""A song made by another tool, read as a take of a job: the same readings, judges and review as a
take the engine made, so a person can compare them. Nothing here spends."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import config, knowledge, media, takes
from .bar import judges
from .bar import song as musicbar
from .blobstore import sha256_file
from .jobfs import Job
from .providers.contract import TranscribeRequest

SHOT = "song"


def free_heard(path: Path) -> list[dict[str, Any]] | None:
    """What a listener would pick out, read by a free local transcriber and never a paid one, for
    a review that spends nothing. None when no free reader is ready."""
    from .providers import base
    from .providers.results import Context

    names = dict.fromkeys([*config.preference("transcribe"), "whispercpp", "mac"])
    usable = []
    for name in names:
        try:
            if base.get(name).free and "transcribe" in base.get(name).capabilities:
                usable.append(name)
        except KeyError:
            continue
    try:
        res = base.resolve("transcribe", usable).transcribe(TranscribeRequest(src=path), Context())
    except (LookupError, RuntimeError, OSError) as exc:
        print(f"the words were not read, so the word readings are left out: {exc}")
        return None
    return [dict(w) for w in res.words]


def add_outside_take(job: Job, audio: Path, made_by: str) -> dict[str, Any]:
    """A song made elsewhere, as a take of this job: read against the job's song file with the same
    readings and judges as a take the engine made, so a person can compare them side by side.
    Nothing is spent, and it never changes which take is chosen."""
    song = dict(job.read("song"))
    n = takes.next_take_number(job, SHOT)
    dst = takes.take_path(job, SHOT, n, ".wav")
    media.run(["-i", str(audio), "-vn", "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", str(dst)])
    heard = free_heard(dst)
    if heard is not None:
        dst.with_suffix(".heard.json").write_text(json.dumps(heard))
    found, ok = musicbar.assessed(dst, song, heard)
    take: dict[str, Any] = {
        "n": n,
        "seed": 0,
        "file": str(dst.relative_to(job.work)),
        "sha256": sha256_file(dst),
        "provider": "outside",
        "model": made_by,
        "readings": {**found, **judges.of_take("song", dst)},
        "ok": bool(ok),
        "bench": True,  # set beside the chosen take, never chosen on its own
        "made_with": knowledge.stamp(),
        "note": f"made outside the engine by {made_by}; read the same way",
    }
    takes.record(job, SHOT, take)
    return take
