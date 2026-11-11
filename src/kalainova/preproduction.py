"""PRE-PRODUCTION: a rough cut of the piece, watched before any video is paid for.

An animatic is the whole piece cut from stills and temporary sound, at the real timings. It is made
by the assets stage with every video call held back, drawn here with a camera move and the words,
and stamped ANIMATIC in its name, its picture, and its record, so it is never approved or published.

A brief can turn the animatic into a gate: the assets stage then refuses to pay for video until a
person has given the animatic they watched a verdict of `accept`.
"""

from __future__ import annotations

import datetime as dt
import subprocess
import textwrap
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image, ImageDraw

from . import media, motion, shotmake, takes, timeline
from .blobstore import sha256_file
from .jobfs import ContractError, Job
from .providers import router

Fields = dict[str, Any]
ANIMATIC_FILE = "animatic.mp4"
LONG_SIDE = 640  # an animatic is a sketch: small, and fast to make
FPS = 12
MOST_LINES = 3
CAPTION_BAND = (
    0.55,
    0.72,
)  # the caption sits in the lower-centre third, clear of interface overlays
WATERMARK = "ANIMATIC"
MOVES = ("push_in", "pan_right", "push_out", "pan_left")
CARD_COLOUR = (24, 24, 28)


class _Scene(Protocol):
    """What the assets stage hands over to be priced."""

    job: Job
    packet: Fields
    brief: Fields
    kinds: set[str]
    video_budget: int
    resolved: Any
    lock: Fields


def moves(beat: Fields, kinds: set[str]) -> bool:
    """Whether this shot is asked to move, and so will be paid for as a clip."""
    return beat.get("visual_kind") == "video" and not beat.get("graphics") and "video" in kinds


def estimated_length(beat: Fields) -> float:
    """How long a shot runs before the voice has set the timeline: its own length, or its words."""
    return float(beat.get("duration_sec") or max(2.0, len(beat["text"].split()) / 2.6))


def moving_quotes(
    piece: _Scene, spans: list[float] | None = None
) -> list[tuple[str, float | None]]:
    """What each moving shot should cost at the takes always made, shot by shot.

    None for a shot whose model has no price. The lip sync and the end frame count with the shot
    they belong to. Priced at the length each shot will be asked for: once the voice has set the
    timeline, pass its spans, and the price is for the generated length, not an estimate of it.
    """
    if "video" not in piece.kinds:
        return []
    always, _ = takes.counts(piece.brief)
    out: list[tuple[str, float | None]] = []
    for i, beat in enumerate(piece.packet["beats"]):
        if not moves(beat, piece.kinds) or len(out) >= max(piece.video_budget, 0):
            continue
        length = spans[i] if spans else estimated_length(beat)
        out.append((beat["id"], _shot_cost(piece, beat, length, always)))
    return out


def _shot_cost(piece: _Scene, beat: Fields, length: float, always: int) -> float | None:
    quote = router.quote(
        piece.job, "video", duration=length, image=True, references=bool(piece.resolved)
    )
    if quote is None or quote[1] is None:
        return None
    total = quote[1] * always
    if beat.get("on_camera"):
        sync = router.quote(piece.job, "lipsync", duration=length)
        if sync is not None and sync[1] is None:
            return None
        total += sync[1] if sync and sync[1] else 0.0
    kw = shotmake.shot_kw(piece.resolved, piece.lock, "video", beat)
    if shotmake.end_frame_used(piece.job, beat, kw):
        end = router.quote(piece.job, "image")
        if end is None or end[1] is None:
            return None
        total += end[1]
    return total


def total_of(quotes: list[tuple[str, float | None]]) -> float | None:
    """The sum of the shots, or None if any one of them has no price."""
    if any(cost is None for _, cost in quotes):
        return None
    return round(sum(cost or 0.0 for _, cost in quotes), 6)


# ------------------------------------------------------------------ the gate
def require_review(job: Job) -> None:
    """Refuse before any spend when the brief asks for an animatic and nobody has accepted it."""
    data = job.job
    if not (data.get("brief") or {}).get("animatic_gate") or "video" not in data.get("media", []):
        return
    steps = (
        f"`kalainova animatic {job.id}`, watch it, then "
        f"`kalainova verdict {job.id} accept --animatic --reviewer NAME`"
    )
    if not job.has("animatic"):
        raise ContractError(
            f"{job.id}: this job holds video until its animatic is accepted; run {steps}"
        )
    review = data.get("animatic_reviewed") or {}
    if review.get("verdict") != "accept":
        said = review.get("verdict")
        raise ContractError(
            f"{job.id}: the animatic "
            + (f"was judged {said}" if said else "has no verdict")
            + f"; video waits for an accept. {steps}"
        )
    if review.get("animatic_sha256") != job.read("animatic")["sha256"]:
        raise ContractError(
            f"{job.id}: the animatic was made again after it was accepted; "
            f"watch the new one, then {steps}"
        )


def refuse_animatic(job: Job, final: Path) -> None:
    """A rough cut of stills and temporary sound is a sketch of the piece, never the piece."""
    rough = job.read("animatic") if job.has("animatic") else {}
    named = final.name.startswith("animatic")
    if final.is_file() and (named or sha256_file(final) == rough.get("sha256")):
        raise ContractError(
            f"{job.id}: {final.name} is an animatic, a rough cut for review; it is never approved "
            "or published. Make the piece with `kalainova make`"
        )


# ------------------------------------------------------------------ the rough cut
def _size(width: int, height: int) -> tuple[int, int]:
    scale = LONG_SIDE / max(width, height)
    return max(round(width * scale / 2) * 2, 2), max(round(height * scale / 2) * 2, 2)


def _stamp(img: Image.Image, text: str) -> Image.Image:
    """The words, in the lower-centre band, and the mark that says this is not the piece."""
    draw = ImageDraw.Draw(img)
    w, h = img.size
    mark = timeline._label_font(max(w // 22, 11))
    draw.text(
        (8, 6), WATERMARK, fill=(255, 210, 60), font=mark, stroke_width=1, stroke_fill=(0, 0, 0)
    )
    size = max(w // 12, 12)
    font = timeline._label_font(size)
    lines = textwrap.wrap(text, width=max(int(w * 0.84 / (size * 0.55)), 12))
    if len(lines) > MOST_LINES:
        lines = [*lines[: MOST_LINES - 1], lines[MOST_LINES - 1].rstrip(" .,;") + "…"]
    for n, line in enumerate(lines):
        y = int(h * CAPTION_BAND[0]) + int(n * size * 1.25)
        draw.text((int(w * 0.08), y), line, fill=(255, 255, 255), font=font, stroke_width=2,
                  stroke_fill=(0, 0, 0))  # fmt: skip
    return img


def _shot_frames(
    still: Path | None, beat: Fields, n: int, seconds: float, size: tuple[int, int]
) -> Iterator[bytes]:
    """The frames of one shot, one at a time, so a long piece never sits in memory."""
    count = max(round(seconds * FPS), 1)
    w, h = size
    caption = str(beat.get("on_screen") or beat.get("text") or "")
    if still is None or not still.is_file():
        card = _stamp(Image.new("RGB", size, CARD_COLOUR), caption).tobytes()
        yield from (card for _ in range(count))
        return
    room = motion.HEADROOM * (1 + motion.ZOOM_PER_SEC) ** seconds
    src = motion.load_still(still, w, h, room=room)
    name = MOVES[n % len(MOVES)]
    for i in range(count):
        frame = motion.frame(src, motion.camera(name, i / FPS, seconds), w, h)
        img = Image.fromarray((np.clip(frame, 0, 1) * 255 + 0.5).astype(np.uint8), "RGB")
        yield _stamp(img, caption).tobytes()


def _command(size: tuple[int, int], sound: list[Path], total: float, dst: Path) -> list[str]:
    cmd = [media.FFMPEG, "-hide_banner", "-y", "-loglevel", "error", "-f", "rawvideo"]
    cmd += ["-pix_fmt", "rgb24", "-s", f"{size[0]}x{size[1]}", "-r", str(FPS), "-i", "-"]
    for path in sound:
        cmd += ["-i", str(path)]
    if sound:
        pads = "".join(f"[{i + 1}:a]aresample=48000,apad[a{i}];" for i in range(len(sound)))
        mixed = "".join(f"[a{i}]" for i in range(len(sound)))
        graph = f"{pads}{mixed}amix=inputs={len(sound)}:duration=longest[a]"
        cmd += ["-filter_complex", graph, "-map", "0:v", "-map", "[a]", "-c:a", "aac"]
    cmd += ["-t", f"{total:.3f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "30"]
    return [*cmd, "-pix_fmt", "yuv420p", str(dst)]


def render(job: Job, made: Fields) -> Path:
    """The rough cut: each shot's still under a camera move, the words, the voice, the track."""
    prof = made["profile"]
    size = _size(int(prof.get("width", 1080)), int(prof.get("height", 1920)))
    sound = [job.work / name for name in made.get("sound", []) if (job.work / name).is_file()]
    dst = job.work / ANIMATIC_FILE
    with subprocess.Popen(  # noqa: S603 - a fixed binary and our own argument list
        _command(size, sound, made["total"], dst), stdin=subprocess.PIPE, stderr=subprocess.PIPE
    ) as proc:
        assert proc.stdin is not None  # noqa: S101 - Popen was given a pipe
        for n, (cut, shot) in enumerate(zip(made["timeline"], made["shots"], strict=True)):
            still = job.work / shot["still"] if shot.get("still") else None
            beat = next(b for b in made["beats"] if b["id"] == shot["beat_id"])
            for frame in _shot_frames(still, beat, n, cut["end_sec"] - cut["start_sec"], size):
                proc.stdin.write(frame)
        proc.stdin.close()
        error = proc.stderr.read() if proc.stderr else b""
    if proc.returncode != 0:
        raise media.MediaError(f"ffmpeg failed making the animatic: {error[-800:]!r}")
    return dst


def write_record(job: Job, made: Fields, dst: Path) -> Fields:
    """The animatic's record: what it shows, what is still to be paid for, and at what price."""
    quotes = dict(made["quotes"])
    shots = [
        {
            **{k: v for k, v in shot.items() if v is not None},
            "start_sec": cut["start_sec"],
            "end_sec": cut["end_sec"],
            "moves": shot["beat_id"] in quotes,
            **(
                {"estimate_usd": quotes[shot["beat_id"]]}
                if quotes.get(shot["beat_id"]) is not None
                else {}
            ),
        }
        for cut, shot in zip(made["timeline"], made["shots"], strict=True)
    ]
    cap = job.job.get("cost_cap")
    record: Fields = {
        "schema_version": "0.1",
        "job_id": job.id,
        "is_animatic": True,
        "built_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "file": dst.name,
        "sha256": sha256_file(dst),
        "duration_sec": round(media.duration(dst), 3),
        "shots": shots,
        "unpriced_shots": [b for b, cost in made["quotes"] if cost is None],
        "committed_usd": round(job.committed(), 6),
    }
    estimate = total_of(made["quotes"])
    if estimate is not None:
        record["video_estimate_usd"] = estimate
    if cap is not None:
        record["cost_cap"] = cap
    job.write("animatic", record)
    return record


def cost_lines(record: Fields, cap: float | None, committed: float) -> list[str]:
    """What the video still to be bought would cost, shot by shot, and against the cap."""
    lines = []
    for shot in record["shots"]:
        if shot["moves"]:
            price = shot.get("estimate_usd")
            lines.append(
                f"  {shot['beat_id']:<12} {'no price' if price is None else f'${price:.2f}'}"
            )
    if not lines:
        return ["no shot is asked to move, so no video is left to pay for"]
    total = record.get("video_estimate_usd")
    worth = "unknown, a model has no price" if total is None else f"about ${total:.2f}"
    head = f"video still to pay for: {worth}"
    if cap is not None and total is not None:
        left = float(cap) - committed
        head += f" against ${max(left, 0):.2f} left of the ${float(cap):.2f} cap"
        if total > left:
            head += " (OVER THE CAP: raise it, or move fewer shots)"
    return [head, *lines]
