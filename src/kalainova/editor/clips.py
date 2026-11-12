"""A long source to short pieces, each one a thought that stands on its own.

A model picks the moments when one is available. With none, the agent writes clips.json by hand, or
the fallback picks the densest stretches of speech. Every clip starts and ends on a word, and
becomes its own job, so it passes the same gates as anything else.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import blobstore, config, consistency, edit, media, prompts
from ..jobfs import ContractError, Job, open_child
from ..providers import router
from ..render import drawn
from . import speech

CLIPS_FILE = "clips.json"
SHORTEST_SEC, LONGEST_SEC = 15.0, 60.0
SENTENCE_END = re.compile(r"[.!?]$")
PROFILE = "short-9x16"
HOOK_CARD_SEC, CLOSE_CARD_SEC = 1.6, 2.5
# Words that open a clip with nothing in it. A clip that begins on one starts a beat late.
OPENING_FILLERS = {"um", "uh", "er", "erm", "hmm", "so", "well", "okay", "ok", "yeah", "like"}
OPENING_PAIRS = {("you", "know"), ("i", "mean")}


def require_source(job: Job) -> dict[str, Any]:
    """Refuse to cut anything the job has no record of being allowed to use.

    The job's contract already names its rights. `brief.source` adds where the file came from
    (`origin`) and which file in the job folder covers its use (`reference`: the brief or the
    licence). The engine never fetches a source: the file is the one the brief provides.
    """
    source = (job.job.get("brief") or {}).get("source")
    if not isinstance(source, dict) or not all(
        str(source.get(k) or "").strip() for k in ("origin", "reference")
    ):
        raise ContractError(
            f"{job.id}: clips need brief.source with `origin` (where the file came from) and "
            "`reference` (the brief or licence file in the job folder)"
        )
    folder = job.folder.resolve()
    ref = (folder / str(source["reference"])).resolve()
    if not ref.is_relative_to(folder) or not ref.is_file():
        raise ContractError(
            f"{job.id}: brief.source.reference {source['reference']!r} is not a file "
            "in the job folder"
        )
    return dict(source)


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
        chunk = _drop_opening_fillers(chunk)
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


def _bare(word: speech.Word) -> str:
    return re.sub(r"[^a-z']", "", str(word.get("text", "")).lower())


def _drop_opening_fillers(words: list[speech.Word]) -> list[speech.Word]:
    """Take "so, um, you know," off the front, and never the last words of a clip."""
    n = 0
    while n < len(words) - 2:
        if _bare(words[n]) in OPENING_FILLERS:
            n += 1
        elif (_bare(words[n]), _bare(words[n + 1])) in OPENING_PAIRS:
            n += 2
        else:
            break
    return words[n:]


def tidy(clip: dict[str, Any], words: list[speech.Word]) -> dict[str, Any]:
    """Start a clip where a sentence starts and not on a filler. No model.

    A start inside a sentence moves back to that sentence's first word when the clip stays within
    the longest allowed, else forward to the next sentence start when the clip stays above the
    shortest. Then any opening fillers go. The end is left where the chooser put it.
    """
    start, end = float(clip["start_sec"]), float(clip["end_sec"])
    firsts = [float(s[0]["start_sec"]) for s in _sentences(words)]
    if start not in firsts:
        earlier = [f for f in firsts if f < start]
        later = [f for f in firsts if start < f < end]
        if earlier and end - earlier[-1] <= LONGEST_SEC:
            start = earlier[-1]
        elif later and end - later[0] >= SHORTEST_SEC:
            start = later[0]
    inside = [w for w in words if float(w["start_sec"]) >= start and float(w["end_sec"]) <= end]
    inside = _drop_opening_fillers(inside)
    if inside:
        start = float(inside[0]["start_sec"])
    return {**clip, "start_sec": start}


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
    return tidy(
        {
            **clip,
            "start_sec": float(inside[0]["start_sec"]),
            "end_sec": float(inside[-1]["end_sec"]),
        },
        words,
    )


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
    require_source(job)
    words = speech.transcript(job, source)
    if not words:
        raise ContractError(
            f"{job.id}: finding clips needs a transcript, and nothing could make one"
        )
    clips = choose(job, words, count)
    (job.folder / CLIPS_FILE).write_text(json.dumps(clips, indent=2, ensure_ascii=False) + "\n")
    return clips


def _manifest(
    job_id: str, source_rel: str, data: dict[str, Any], length: float, lock_sha: str | None = None
) -> dict[str, Any]:
    manifest: dict[str, Any] = {
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
    if lock_sha:  # the same field the generated path writes, so the kit check at publish passes
        manifest["kit_lock_sha256"] = lock_sha
    return manifest


def motion_centre(parent: Job, source: Path, clip: dict[str, Any]) -> float | None:
    """Where the shots under a clip say the action is, from ingest. A motion centre, not a face."""
    path = parent.folder / "footage.json"
    if not path.exists():
        return None
    footage = json.loads(path.read_text())
    ids = {s["id"] for s in footage["sources"] if Path(str(s["path"])).name == source.name}
    total = x = 0.0
    for shot in footage["shots"]:
        if shot["source"] not in ids or shot.get("subject_x") is None:
            continue
        overlap = min(float(shot["out_sec"]), clip["end_sec"]) - max(
            float(shot["in_sec"]), clip["start_sec"]
        )
        if overlap > 0:
            total += overlap
            x += overlap * float(shot["subject_x"])
    return round(x / total, 3) if total else None


def face_centre(parent: Job, source: Path, clip: dict[str, Any]) -> float | None:
    """A face's horizontal centre from a detector the operator runs as a command, or None.

    `clips.face_command` in config/studio.yaml is an argument list; `{source}`, `{start}` and
    `{end}` are filled in. The command prints one JSON object, `{"x": 0.0-1.0}`. Nothing is
    configured by default, and no detector is a dependency of the engine.
    """
    template = (config.studio().get("clips") or {}).get("face_command")
    if not template:
        return None
    fill = {
        "source": str(source),
        "start": f"{clip['start_sec']:.3f}",
        "end": f"{clip['end_sec']:.3f}",
    }
    argv = [str(a).format(**fill) for a in template]
    try:
        # an argument list from config, never a shell string
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=300, check=True)  # noqa: S603
        x = float(json.loads(proc.stdout)["x"])
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        return None
    return round(x, 3) if 0.0 <= x <= 1.0 else None


# One seam, two adapters. The in-house motion centre stays the default; `face` runs first when asked
# and falls back to it, and the manifest records which one produced the number.
CROP_ADAPTERS: dict[str, Callable[[Job, Path, dict[str, Any]], float | None]] = {
    "motion_centre": motion_centre,
    "face": face_centre,
}
CROP_ORDER = {"motion": ("motion_centre",), "face": ("face", "motion_centre")}


def choose_crop(
    parent: Job, source: Path, clip: dict[str, Any], crop: str, crop_x: float | None
) -> tuple[float, str]:
    if crop not in CROP_ORDER:
        raise ContractError(f"crop must be one of {', '.join(CROP_ORDER)}, not {crop!r}")
    if crop_x is not None:
        return crop_x, "given"
    for name in CROP_ORDER[crop]:
        found = CROP_ADAPTERS[name](parent, source, clip)
        if found is not None:
            return found, name
    return 0.5, "default"


def _render_card(child: Job, name: str, text: str, seconds: float) -> dict[str, Any]:
    """Draw one title card with the graphics provider and return its asset record."""
    prof = config.profile(PROFILE)
    folder = child.folder / "graphics" / name
    drawn.write_card(
        folder, "title", {"text": text}, int(prof["width"]), int(prof["height"]), seconds,
        float(prof["fps"]),
    )  # fmt: skip
    dst = child.work / f"{name}.mp4"
    provider, res = router.generate(
        child, "graphics", "graphics", folder, dst, fps=float(prof["fps"]), note=f"clips {name}"
    )
    return {
        "id": name,
        "kind": "video",
        "role": "visual",
        "path": dst.name,
        "duration_sec": media.duration(dst),
        "rights": child.job["rights"],
        "provider": provider.name,
        "model": res.model,
        "synthetic": False,
    }


def open_job(
    parent: Job,
    source: Path,
    clip: dict[str, Any],
    new_id: str,
    *,
    crop_x: float | None = None,
    crop: str = "motion",
    hook_text: str | None = None,
    close_text: str | None = None,
) -> Job:
    """A short piece from one chosen moment, with its speech cut clean and its words as captions."""
    record = require_source(parent)
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
    seen = {"file": source.name, "sha256": blobstore.sha256_file(source)}
    brief = {**(parent.job.get("brief") or {}), "subject": title, "source": {**record, **seen}}
    child = open_child(parent, new_id, profile=PROFILE, brief=brief)
    shutil.copyfile(parent.folder / record["reference"], child.folder / record["reference"])
    copied = child.work / f"source{source.suffix}"
    if not copied.exists():
        copied.hardlink_to(source)
    length = sum(b - a for a, b in keeps)
    lock = consistency.lock_sha256(child) if child.has("kit_lock") else None
    child.write("asset_manifest", _manifest(new_id, copied.name, child.job, length, lock))
    child.write(
        "script_packet",
        {
            "schema_version": "0.1",
            "job_id": new_id,
            "title": title,
            "beats": [{"id": "c1", "role": "hook", "text": title}],
        },
    )
    at, basis = choose_crop(parent, source, clip, crop, crop_x)
    wanted = (("hook-card", hook_text, HOOK_CARD_SEC), ("close-card", close_text, CLOSE_CARD_SEC))
    drawn_cards = [_render_card(child, name, text, sec) for name, text, sec in wanted if text]
    if drawn_cards:
        record = child.read("asset_manifest")
        record["assets"] += drawn_cards
        record["duration_sec"] = round(length + sum(c["duration_sec"] for c in drawn_cards), 3)
        child.write("asset_manifest", record)
    _write_edit(child, keeps, span, at, basis, drawn_cards)
    return child


def _card_cut(card: dict[str, Any], at: float, role: str) -> dict[str, Any]:
    return {
        "id": f"cut-{card['id']}",
        "source": card["id"],
        "in_sec": 0.0,
        "out_sec": card["duration_sec"],
        "role": role,
        "start_sec": round(at, 3),
        "keep_audio": False,
    }


def _write_edit(
    child: Job,
    keeps: list[tuple[float, float]],
    words: list[speech.Word],
    crop_x: float,
    crop_basis: str,
    cards: list[dict[str, Any]] | None = None,
) -> None:
    prof = config.profile(PROFILE)
    cuts, at = [], 0.0
    opening = [c for c in cards or [] if c["id"] == "hook-card"]
    closing = [c for c in cards or [] if c["id"] == "close-card"]
    for card in opening:
        cuts.append(_card_cut(card, at, "hook"))
        at += card["duration_sec"]
    lead = at
    for n, (start, end) in enumerate(keeps):
        cuts.append(
            {
                "id": f"cut-{n:03d}",
                "source": "source",
                "in_sec": start,
                "out_sec": end,
                "role": "hook" if n == 0 and not opening else "body",
                "start_sec": round(at, 3),
                "crop_x": crop_x,
                "crop_basis": crop_basis,
                "keep_audio": True,
                **({"zoom": 1.08} if n % 2 else {}),
            }
        )
        at += end - start
    for card in closing:
        cuts.append(_card_cut(card, at, "cta"))
        at += card["duration_sec"]
    placed = [
        {
            **w,
            "start_sec": round(w["start_sec"] + lead, 3),
            "end_sec": round(w["end_sec"] + lead, 3),
        }
        for w in speech.on_output_timeline(words, keeps)
    ]
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
