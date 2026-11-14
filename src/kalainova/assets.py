"""SCRIPT -> ASSET. Generates voice, visuals, music and sfx; writes asset_manifest.json.

Asset paths are relative to the job's work dir (out/<job_id>/), which is gitignored.
Each beat gets its own voice clip; the clips are joined into one voice track so
word timings live on a single timeline the editor can cut against.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import config, consistency, media, preproduction, shotmake, shots, soundbed, takes
from .jobfs import ContractError, Job
from .providers import router

Fields = dict[str, Any]

# Air after a line follows how it ends: a full stop takes a breath, a clause runs on.
PAUSE_AFTER = {".": 0.34, "?": 0.38, "!": 0.34, "…": 0.45, ",": 0.14, ":": 0.2, ";": 0.2}
PAUSE_DEFAULT = 0.18


def _pause(text: str) -> float:
    return PAUSE_AFTER.get(text.rstrip()[-1:], PAUSE_DEFAULT)


@dataclass
class _Piece:
    """One run of this stage: what it was asked for, and what it has made so far."""

    job: Job
    force: bool
    data: Fields
    packet: Fields
    prof: Fields
    brief: Fields
    kinds: set[str]
    resolved: Any = None
    lock: Fields = field(default_factory=dict)
    allow_stills: bool = False
    video_budget: int = 0
    assets: list[Fields] = field(default_factory=list)
    words: list[Fields] = field(default_factory=list)
    timeline: list[Fields] = field(default_factory=list)
    breaks: list[Fields] = field(default_factory=list)
    kit_voices: dict[str, str] = field(default_factory=dict)
    sketch: list[Fields] = field(default_factory=list)

    @property
    def has_sound(self) -> bool:
        return bool(self.kinds & {"audio", "video"})

    def gen(self, capability: str, fn_name: str, *args: Any, **kw: Any) -> tuple[Any, Any]:
        return router.generate(self.job, capability, fn_name, *args, fresh=self.force, **kw)

    def add(self, **fields: Any) -> Fields:
        kept = {k: v for k, v in fields.items() if v not in (None, "", [])}
        self.assets.append(kept)
        return kept

    def span(self, i: int) -> float:
        return float(self.timeline[i]["end_sec"] - self.timeline[i]["start_sec"])


def _open_piece(job: Job, force: bool) -> _Piece:
    data = job.job
    brief = data.get("brief") or {}
    resolved, lock = consistency.for_job(job) or (None, {})
    return _Piece(
        job=job,
        force=force,
        data=data,
        packet=job.read("script_packet"),
        prof=config.profile(data.get("profile") or "short-9x16"),
        brief=brief,
        kinds=set(data.get("media", [])),
        resolved=resolved,
        lock=lock,
        allow_stills=bool(brief.get("allow_stills")),
        video_budget=shots.video_budget(data),
    )


def _review_the_plan(piece: _Piece, *, hold_to_the_cap: bool = True) -> None:
    """Warn about what can be made badly, and refuse what cannot be made, before any spend."""
    found = shots.review(
        piece.packet,
        budget=piece.video_budget,
        allow_stills=piece.allow_stills,
        wants_video="video" in piece.kinds,
        style=shotmake.style(piece.data),
        limit=shots.word_limit(config.preference("video", piece.data)),
        character_max_sec=shots.character_ceiling(piece.data),
    )
    for problem in found:
        if problem["status"] == "warn":
            print(f"{piece.job.id}: [{problem['id']}] {problem['detail']}", file=sys.stderr)
    refused = [p["detail"] for p in found if p["status"] == "fail"]
    if refused:
        raise ContractError(
            f"{piece.job.id}: the plan cannot be made as written: " + "; ".join(refused)
        )
    if hold_to_the_cap:
        preproduction.refuse_over_the_cap(piece)


# ------------------------------------------------------------------ voice
@dataclass
class _Narration:
    parts: list[Path] = field(default_factory=list)
    makers: list[tuple[Any, Any]] = field(default_factory=list)
    pauses: list[float] = field(default_factory=list)


def _voice_request(piece: _Piece, n: int) -> Fields:
    beats = piece.packet["beats"]
    beat = beats[n]
    request: Fields = {"voice": piece.brief.get("voice")}
    if piece.resolved:
        fixed = consistency.voice_for(piece.resolved, beat, piece.lock.get("cast", []))
        piece.kit_voices[beat["id"]] = fixed["voice_id"]
        request = {
            "voice": fixed["voice_id"],
            "model": fixed["model"],
            "only": [fixed["provider"]],
        }
        if fixed.get("settings"):
            request["settings"] = fixed["settings"]
    return {
        **request,
        "previous_text": beats[n - 1]["text"] if n else None,
        "next_text": beats[n + 1]["text"] if n + 1 < len(beats) else None,
    }


def _say_line(piece: _Piece, n: int, at: float, lines: _Narration) -> float:
    """Voice one beat, with its words on the piece's clock. Returns its length, with its pause."""
    beat = piece.packet["beats"][n]
    dst = piece.job.work / "beats" / f"{beat['id']}.voice.wav"
    made, res = piece.gen(
        "voice",
        "voice",
        beat["text"],
        dst,
        est={"chars": len(beat["text"])},
        **_voice_request(piece, n),
    )
    piece.words += [
        {**w, "start_sec": round(w["start_sec"] + at, 3), "end_sec": round(w["end_sec"] + at, 3)}
        for w in res.words
    ]
    lines.parts.append(dst)
    lines.makers.append((made, res))
    lines.pauses.append(_pause(beat["text"]))
    return media.duration(dst) + lines.pauses[-1]


def _join_voice(piece: _Piece, lines: _Narration, opening_ms: int) -> None:
    """One track, so word timings live on a single timeline the editor can cut against."""
    work = piece.job.work
    count = len(lines.parts)
    # pad each clip with its pause, then concat via the concat filter (no list files, no shell)
    inputs = [arg for part in lines.parts for arg in ("-i", str(part))]
    pads = "".join(
        f"[{i}:a]aresample=48000,{f'adelay={opening_ms}:all=1,' if opening_ms and not i else ''}"
        f"apad=pad_dur={lines.pauses[i]}[a{i}];"
        for i in range(count)
    )
    joined = "".join(f"[a{i}]" for i in range(count)) + f"concat=n={count}:v=0:a=1[out]"
    out = work / "voice.wav"
    media.run([*inputs, "-filter_complex", pads + joined, "-map", "[out]", "-ac", "1", str(out)])
    # one manifest entry covers every beat, so one local beat after a fallback marks the whole track
    made, res = next((m for m in lines.makers if m[0].name == "local"), lines.makers[-1])
    piece.add(
        id="voice",
        kind="audio",
        role="voice",
        path="voice.wav",
        duration_sec=media.duration(out),
        rights=shotmake.rights(piece.data),
        provider=made.name,
        model=res.model,
        provenance={"kit_voices": piece.kit_voices} if piece.kit_voices else shotmake.made(res),
        synthetic=True,
        probe=media.summarize(out),
    )


def _make_voice(piece: _Piece) -> float:
    """Every line, and the timeline they set. Returns the length of the whole piece."""
    # a film opens on picture and music, and holds after its last word; a reel starts on the words
    narrated = piece.brief.get("narration", True) is not False  # a cut track starts when it does
    at = float(piece.prof.get("open_sec", 0.0)) if narrated else 0.0
    closing = float(piece.prof.get("close_sec", 0.0)) if narrated else 0.0
    opening_ms = int(at * 1000)
    silent = bool(piece.resolved and getattr(piece.resolved, "silent", False))
    speaks = narrated and piece.has_sound and not silent
    lines = _Narration()
    for n, beat in enumerate(piece.packet["beats"]):
        start = at
        at += _say_line(piece, n, start, lines) if speaks else preproduction.estimated_length(beat)
        piece.timeline.append(
            {
                "beat_id": beat["id"],
                "start_sec": round(start if n else 0.0, 3),
                "end_sec": round(at, 3),
            }
        )
    total = round(at + closing, 3)
    if piece.timeline:
        piece.timeline[-1]["end_sec"] = total
    if lines.parts:
        lines.pauses[-1] += closing
        _join_voice(piece, lines, opening_ms)
    return total


# ------------------------------------------------------------------ picture
def _chained_still(piece: _Piece, beat: Fields, previous: Path, still: Path) -> None:
    shotmake.last_frame(previous, still)
    piece.add(
        id=f"{beat['id']}.still",
        kind="still",
        role="visual",
        beat_id=beat["id"],
        path=f"beats/{beat['id']}.still.png",
        rights=shotmake.rights(piece.data),
        provider="chained",
        model="last frame of the shot before",
        provenance={"chained_from": previous.name},
        synthetic=True,
        probe=media.summarize(still),
    )


def _new_still(piece: _Piece, i: int, beat: Fields, prompt: str, still: Path) -> None:
    if preproduction.reuse_accepted_still(piece, beat, still, prompt):
        return
    kw = shotmake.shot_kw(piece.resolved, piece.lock, "image", beat)
    made, res = piece.gen(
        "image",
        "image",
        prompt,
        still,
        width=int(piece.prof.get("width", 1080)),
        height=int(piece.prof.get("height", 1920)),
        title=beat.get("on_screen") or beat["text"],
        palette=i,
        style=(piece.data.get("edit") or {}).get("theme", "studio"),
        **kw,
    )
    piece.add(
        id=f"{beat['id']}.still",
        kind="still",
        role="visual",
        beat_id=beat["id"],
        path=f"beats/{beat['id']}.still.png",
        rights=shotmake.rights(piece.data),
        provider=made.name,
        model=res.model,
        provenance=shotmake.made(res, shotmake.kit_refs(kw)),
        prompt=prompt,
        synthetic=True,
        probe=media.summarize(still),
    )


def _film_shot(
    piece: _Piece, beat: Fields, still: Path, prompt: str, span: float, clip: Path
) -> None:
    kw = shotmake.shot_kw(piece.resolved, piece.lock, "video", beat, start=still)
    take = shotmake.take_clip(
        piece.job,
        piece.packet,
        beat,
        still,
        span,
        piece.prof,
        kw,
        piece.gen,
        piece.data,
        prompt,
        clip,
    )
    piece.video_budget -= 1
    broken = shotmake.motion_break(piece.job, beat["id"], take, piece.allow_stills)
    if broken:
        piece.breaks.append(broken)
        print(f"{piece.job.id}: {beat['id']}: {broken['reason']}", file=sys.stderr)
    synced = (
        shotmake.lip_sync(piece.job, beat, clip, span, piece.gen) if beat.get("on_camera") else None
    )
    piece.add(
        id=f"{beat['id']}.video",
        kind="video",
        role="visual",
        beat_id=beat["id"],
        path=f"beats/{beat['id']}.video.mp4",
        duration_sec=media.duration(clip),
        rights=shotmake.rights(piece.data),
        provider=take["provider"],
        model=take["model"],
        provenance={
            **(shotmake.kit_refs(kw) or {}),
            **takes.provider_meta(take),
            **({"end_frame": take["end_frame"]} if take.get("end_frame") else {}),
            **(synced or {}),
        },
        prompt=take.get("prompt"),
        synthetic=True,
        probe=media.summarize(clip),
    )
    shotmake.clip_ambience(piece.job, beat, clip, piece.brief, piece.add, piece.data)


def _moving_shot(piece: _Piece, beat: Fields, still: Path, prompt: str, span: float) -> Path | None:
    """The clip of a shot that asked to move. Failing is refused, unless the job accepts stills."""
    bid = beat["id"]
    if beat.get("visual_kind") != "video" or "video" not in piece.kinds:
        return None
    if piece.video_budget <= 0:
        piece.breaks.append({"beat_id": bid, "reason": "over the video budget"})
        return None
    refusal = preproduction.refuse_shot_still(piece.job, beat, still)
    if refusal:
        piece.breaks.append({"beat_id": bid, "reason": refusal})
        print(f"{piece.job.id}: {bid}: {refusal}", file=sys.stderr)
        return None
    clip = piece.job.work / "beats" / f"{bid}.video.mp4"
    try:
        _film_shot(piece, beat, still, prompt, span, clip)
    except RuntimeError as exc:
        if not piece.allow_stills:
            raise ContractError(
                f"{piece.job.id}: {bid} asked to move and could not: {exc}. "
                "Fix the provider, or set brief.allow_stills to accept a still here."
            ) from exc
        piece.breaks.append({"beat_id": bid, "reason": str(exc)[:300]})
        print(f"{piece.job.id}: {bid}: no video clip, using the still: {exc}", file=sys.stderr)
        return None
    return clip


def _make_pictures(piece: _Piece) -> None:
    if not piece.kinds & {"video", "still"}:
        return
    previous: Path | None = None
    for i, beat in enumerate(piece.packet["beats"]):
        span = piece.span(i)
        if beat.get("graphics"):
            previous = shotmake.graphics_shot(
                piece.job, beat, span, piece.add, piece.gen, piece.data
            )
            continue
        prompt = shotmake.picture_prompt(piece.resolved, piece.packet, beat, piece.data)
        still = piece.job.work / "beats" / f"{beat['id']}.still.png"
        if beat.get("continues") and previous and previous.exists():
            _chained_still(piece, beat, previous, still)
        else:
            _new_still(piece, i, beat, prompt, still)
        still_refusal = preproduction.still_judge_refusal(piece.job, beat, still)
        if still_refusal:
            piece.breaks.append({"beat_id": beat["id"], "reason": still_refusal})
            print(f"{piece.job.id}: {beat['id']}: {still_refusal}", file=sys.stderr)
            previous = None
            continue
        previous = _moving_shot(piece, beat, still, prompt, span)


def _sketch_pictures(piece: _Piece) -> None:
    """The animatic's pictures: each shot's first frame, made once for the full run to reuse.

    No clip is asked for. A shot that carries on from the one before holds that shot's frame, since
    the frame it will really start on does not exist until the clip does. A drawn card comes later.
    """
    held: str | None = None
    for i, beat in enumerate(piece.packet["beats"]):
        row: Fields = {"beat_id": beat["id"]}
        piece.sketch.append(row)
        if not piece.kinds & {"video", "still"} or beat.get("graphics"):
            held = None
            continue
        if beat.get("continues") and held:
            row["still"] = held
            continue
        prompt = shotmake.picture_prompt(piece.resolved, piece.packet, beat, piece.data)
        _new_still(piece, i, beat, prompt, piece.job.work / "beats" / f"{beat['id']}.still.png")
        held = row["still"] = f"beats/{beat['id']}.still.png"


def _run_animatic(job: Job, force: bool) -> Fields:
    """Voice and stills, and the price of the video still to come. Writes no asset manifest."""
    (job.work / "beats").mkdir(exist_ok=True)
    piece = _open_piece(job, force)
    beats = piece.packet["beats"]
    _review_the_plan(piece, hold_to_the_cap=False)
    if piece.resolved:
        consistency.check_script(job, piece.resolved, piece.packet, piece.lock.get("cast", []))
    total = _make_voice(piece)
    _sketch_pictures(piece)
    if piece.has_sound and piece.brief.get("track"):
        soundbed.track_from_job(job, piece.brief["track"], total, piece.add, piece.data)
    return {
        "beats": beats,
        "timeline": piece.timeline,
        "shots": piece.sketch,
        "sound": [a["path"] for a in piece.assets if a.get("role") in ("voice", "music")],
        "total": total,
        "quotes": preproduction.moving_quotes(piece, [piece.span(i) for i in range(len(beats))]),
        "profile": piece.prof,
    }


# ------------------------------------------------------------------ sound
def _make_places(piece: _Piece) -> None:
    if not piece.has_sound:
        return
    have = {a["id"] for a in piece.assets}
    for i, beat in enumerate(piece.packet["beats"]):
        cue = beat.get("ambience")
        if cue and f"{beat['id']}.ambience" not in have:
            shotmake.generated_ambience(
                piece.job, beat["id"], cue, piece.span(i), piece.add, piece.gen, piece.data
            )


def _make_music(piece: _Piece, total: float) -> None:
    """The music bed and the transition, each from the kit when it fixes one."""
    if not piece.has_sound:
        return
    fixed = (piece.resolved.shared.get("music") or {}) if piece.resolved else {}
    job, add, gen, data = piece.job, piece.add, piece.gen, piece.data
    if piece.brief.get("track"):
        soundbed.track_from_job(job, piece.brief["track"], total, add, data)
    else:
        soundbed.bed(job, "music", "music", fixed.get("theme"), total + 1.0, add, gen, data)
    opts = data.get("edit") or {}
    if opts.get("whoosh", opts.get("theme", "studio") != "studio"):
        soundbed.bed(job, "whoosh", "sfx", fixed.get("whoosh"), 0.6, add, gen, data)


def _write_manifest(piece: _Piece, total: float) -> Fields:
    manifest: Fields = {
        "schema_version": "0.1",
        "job_id": piece.data["job_id"],
        "assets": piece.assets,
        "timeline": piece.timeline,
        "duration_sec": total,
    }
    if piece.words or piece.brief.get("words"):
        manifest["words"] = piece.words or list(piece.brief["words"])
    if piece.breaks:
        manifest["promise_breaks"] = piece.breaks
    if piece.resolved:
        manifest["kit_lock_sha256"] = consistency.lock_sha256(piece.job)
    piece.job.write("asset_manifest", manifest)
    return manifest


def run(job: Job, *, force: bool = False, animatic: bool = False) -> Fields:
    """Make the assets. With animatic, only the voice and the stills, and no video is asked for."""
    if animatic:
        return _run_animatic(job, force)
    if job.has("asset_manifest") and not force:
        return job.read("asset_manifest")
    preproduction.require_review(job)
    (job.work / "beats").mkdir(exist_ok=True)
    if force:
        takes.forget(job)
    piece = _open_piece(job, force)
    _review_the_plan(piece)
    if piece.resolved:
        consistency.check_script(job, piece.resolved, piece.packet, piece.lock.get("cast", []))
    total = _make_voice(piece)
    _make_pictures(piece)
    _make_places(piece)
    _make_music(piece, total)
    return _write_manifest(piece, total)
