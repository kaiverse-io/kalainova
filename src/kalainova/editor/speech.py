"""Cut speech at word boundaries, from what was really said.

Rules from video-use (MIT), learned the hard way there: never cut inside a word, pad every edge
because timestamps drift, and cut only at a real gap in speech. A silence detector cannot tell a
thinking pause from a breath before a punchline, and it knows nothing about words, so its cuts read
as choppy.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .. import media
from ..jobfs import Job
from ..providers import router

Word = dict[str, Any]
PAD_BEFORE_SEC = 0.05
PAD_AFTER_SEC = 0.08
LEAST_GAP_TO_CUT_SEC = 0.4  # shorter silences are mid-phrase, and cutting them reads as choppy
LEAST_SPAN_SEC = 0.5
FILLERS = {"um", "uh", "er", "erm", "hmm", "mm", "uhh", "umm"}


def transcript(job: Job, source: Path) -> list[Word] | None:
    """Word timings for a source, kept by its bytes so nothing is transcribed twice."""
    folder = job.work / "transcripts"
    folder.mkdir(exist_ok=True)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()[:16]
    saved = folder / f"{digest}.json"
    if saved.exists():
        return list(json.loads(saved.read_text()))
    if not router.available(job, "transcribe"):
        return None
    try:
        _, res = router.generate(
            job,
            "transcribe",
            "transcribe",
            source,
            est={"duration": media.duration(source)},
            note="transcript",
        )
    except (router.ProviderError, OSError) as exc:
        print(f"{job.id}: no transcript of {source.name}: {exc}")
        return None
    saved.write_text(json.dumps(res.words))
    return list(res.words)


def _is_filler(word: Word) -> bool:
    return str(word.get("text", "")).strip(" ,.?!").lower() in FILLERS


def keeps(
    words: list[Word], duration: float, *, drop_fillers: bool = True
) -> list[tuple[float, float]]:
    """What to keep: runs of speech, each padded, with a cut only at a real gap or a filler."""
    spoken = [w for w in words if not (drop_fillers and _is_filler(w))]
    if not spoken:
        return []
    spans: list[list[float]] = []
    for word in spoken:
        start, end = float(word["start_sec"]), float(word["end_sec"])
        if spans and start - spans[-1][1] < LEAST_GAP_TO_CUT_SEC:
            spans[-1][1] = end
        else:
            spans.append([start, end])
    padded = [
        (round(max(a - PAD_BEFORE_SEC, 0.0), 3), round(min(b + PAD_AFTER_SEC, duration), 3))
        for a, b in spans
    ]
    return [(a, b) for a, b in padded if b - a >= LEAST_SPAN_SEC]


def on_output_timeline(words: list[Word], spans: list[tuple[float, float]]) -> list[Word]:
    """Words at their time in the finished cut. A word in a part that was cut out is dropped."""
    out, offset = [], 0.0
    for start, end in spans:
        for word in words:
            at = float(word["start_sec"])
            if start <= at and float(word["end_sec"]) <= end:
                out.append(
                    {
                        **word,
                        "start_sec": round(at - start + offset, 3),
                        "end_sec": round(float(word["end_sec"]) - start + offset, 3),
                    }
                )
        offset += end - start
    return out
