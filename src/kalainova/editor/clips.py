"""A long source to short pieces, each one a thought that stands on its own.

A model picks the moments when one is available. With none, the agent writes clips.json by hand, or
the fallback picks the densest stretches of speech. Every clip starts and ends on a word, and
becomes its own job, so it passes the same gates as anything else.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .. import config, edit, media, prompts
from ..jobfs import ContractError, Job, open_child
from ..providers import router
from . import speech

CLIPS_FILE = "clips.json"
SHORTEST_SEC, LONGEST_SEC = 15.0, 60.0
SENTENCE_END = re.compile(r"[.!?]$")
PROFILE = "short-9x16"


def _sentences(words: list[speech.Word]) -> list[list[speech.Word]]:
    out: list[list[speech.Word]] = [[]]
    for word in words:
        out[-1].append(word)
        if SENTENCE_END.search(str(word.get("text", ""))):
            out.append([])
    return [s for s in out if s]


def _window_score(chunk: list[speech.Word]) -> float:
    """Speech per second, with a nudge for questions and numbers, which tend to hold attention."""
    length = max(float(chunk[-1]["end_sec"]) - float(chunk[0]["start_sec"]), 1.0)
    text = " ".join(str(w.get("text", "")) for w in chunk)
    return len(chunk) / length + 0.5 * text.count("?") + 0.25 * len(re.findall(r"\d", text))


def _windows(sentences: list[list[speech.Word]]) -> list[list[speech.Word]]:
    out = []
    for first in range(len(sentences)):
        chunk: list[speech.Word] = []
        for sentence in sentences[first:]:
            chunk += sentence
            length = float(chunk[-1]["end_sec"]) - float(chunk[0]["start_sec"])
            if length > LONGEST_SEC:
                break
            if length >= SHORTEST_SEC:
                out.append(list(chunk))
    return out


def densest(words: list[speech.Word], count: int) -> list[dict[str, Any]]:
    """With no model: the stretches with the most in them, in whole sentences, never overlapping."""
    ranked = sorted(_windows(_sentences(words)), key=_window_score, reverse=True)
    chosen: list[dict[str, Any]] = []
    for chunk in ranked:
        start, end = float(chunk[0]["start_sec"]), float(chunk[-1]["end_sec"])
        if any(start < c["end_sec"] and end > c["start_sec"] for c in chosen):
            continue
        title = " ".join(str(w.get("text", "")) for w in chunk[:6]).rstrip(",.")
        chosen.append(
            {"start_sec": start, "end_sec": end, "title": title, "why": "dense with speech"}
        )
        if len(chosen) == count:
            break
    return sorted(chosen, key=lambda c: c["start_sec"])


def snap(clip: dict[str, Any], words: list[speech.Word]) -> dict[str, Any] | None:
    """Move a chosen clip's edges onto words. A clip with no words in it is not a clip."""
    inside = [
        w
        for w in words
        if float(w["end_sec"]) > float(clip["start_sec"])
        and float(w["start_sec"]) < float(clip["end_sec"])
    ]
    if not inside:
        return None
    return {
        **clip,
        "start_sec": float(inside[0]["start_sec"]),
        "end_sec": float(inside[-1]["end_sec"]),
    }


def _packed(words: list[speech.Word]) -> str:
    """The transcript by sentence with its times, which is far fewer tokens than every word."""
    return "\n".join(
        f"[{float(s[0]['start_sec']):.1f}-{float(s[-1]['end_sec']):.1f}] "
        + " ".join(str(w.get("text", "")) for w in s)
        for s in _sentences(words)
    )


def choose(job: Job, words: list[speech.Word], count: int) -> list[dict[str, Any]]:
    from ..plan import extract_json

    if not router.available(job, "llm"):
        return densest(words, count)
    text = prompts.load("clip_finder").format(
        count=count, shortest=SHORTEST_SEC, longest=LONGEST_SEC, transcript=_packed(words)
    )
    _, res = router.generate(job, "llm", "llm", text, max_tokens=2000, note="clips")
    picked = [snap(c, words) for c in extract_json(res.text).get("clips", [])]
    return [c for c in picked if c][:count]


def find(job: Job, source: Path, *, count: int = 3) -> list[dict[str, Any]]:
    """Choose the moments and save them, where a person or an agent can change them."""
    words = speech.transcript(job, source)
    if not words:
        raise ContractError(
            f"{job.id}: finding clips needs a transcript, and nothing could make one"
        )
    clips = choose(job, words, count)
    (job.folder / CLIPS_FILE).write_text(json.dumps(clips, indent=2, ensure_ascii=False) + "\n")
    return clips


def _manifest(job_id: str, source_rel: str, data: dict[str, Any], length: float) -> dict[str, Any]:
    return {
        "schema_version": "0.1",
        "job_id": job_id,
        "duration_sec": round(length, 3),
        "assets": [
            {
                "id": "source",
                "kind": "video",
                "role": "visual",
                "path": source_rel,
                "rights": data["rights"],
                "provider": "operator",
                "synthetic": False,
            }
        ],
    }


def open_job(
    parent: Job, source: Path, clip: dict[str, Any], new_id: str, *, crop_x: float = 0.5
) -> Job:
    """A short piece from one chosen moment, with its speech cut clean and its words as captions."""
    words = speech.transcript(parent, source) or []
    span = [
        w
        for w in words
        if clip["start_sec"] <= float(w["start_sec"]) and float(w["end_sec"]) <= clip["end_sec"]
    ]
    keeps = speech.keeps(span, media.duration(source))
    if not keeps:
        raise ContractError(f"{parent.id}: nothing to keep in {clip.get('title', 'that clip')}")
    title = str(clip.get("title") or new_id)
    child = open_child(parent, new_id, profile=PROFILE, brief={"subject": title})
    copied = child.work / f"source{source.suffix}"
    if not copied.exists():
        copied.hardlink_to(source)
    length = sum(b - a for a, b in keeps)
    child.write("asset_manifest", _manifest(new_id, copied.name, child.job, length))
    child.write(
        "script_packet",
        {
            "schema_version": "0.1",
            "job_id": new_id,
            "title": title,
            "beats": [{"id": "c1", "role": "hook", "text": title}],
        },
    )
    _write_edit(child, keeps, span, crop_x)
    return child


def _write_edit(
    child: Job, keeps: list[tuple[float, float]], words: list[speech.Word], crop_x: float
) -> None:
    prof = config.profile(PROFILE)
    cuts, at = [], 0.0
    for n, (start, end) in enumerate(keeps):
        cuts.append(
            {
                "id": f"cut-{n:03d}",
                "source": "source",
                "in_sec": start,
                "out_sec": end,
                "role": "hook" if n == 0 else "body",
                "start_sec": round(at, 3),
                "crop_x": crop_x,
                "keep_audio": True,
                **({"zoom": 1.08} if n % 2 else {}),
            }
        )
        at += end - start
    placed = speech.on_output_timeline(words, keeps)
    child.write(
        "edit_manifest",
        {
            "schema_version": "0.1",
            "job_id": child.id,
            "runtime": "ffmpeg",
            "duration_sec": round(at, 3),
            "profile": {
                "aspect": prof["aspect"],
                "width": int(prof["width"]),
                "height": int(prof["height"]),
                "fps": float(prof["fps"]),
                "target_lufs": float(prof["target_lufs"]),
                "true_peak_dbtp_max": float(prof["true_peak_dbtp_max"]),
            },
            "theme": "studio",
            "transition": "cut",
            "caption_style": "studio",
            "cuts": cuts,
            "captions": edit.caption_cards(placed, set(), 4, 22),
            "overlays": [],
            "audio": {},
            "original_audio": True,
            "speech": True,
            "fade_out_sec": 0.3,
        },
    )
