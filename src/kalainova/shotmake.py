"""One shot: where it starts, its takes, its mouth, and the sound of its place.

Every shot that moves is made here, whether by a first run or a retake a person asked for, so both
follow the same promise and the same record.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import config, consistency, media, shots, takes
from .blobstore import sha256_file
from .jobfs import ContractError, Job
from .providers import base, router

Fields = dict[str, Any]
Gen = Callable[..., tuple[Any, Any]]
Add = Callable[..., Any]


def rights(job: Fields) -> str:
    return str(job["rights"])  # required on every job, and stated by a person


def made(res: Any, extra: Fields | None = None) -> Fields | None:
    """What a record of this file needs to say about how it was made."""
    meta = {k: v for k, v in (res.meta or {}).items() if k != "words"}
    found = {**dict(meta.pop("provenance", None) or {}), **meta, **(extra or {})}
    return found or None


def style(job: Fields) -> str:
    brief = job.get("brief") or {}
    return (
        brief.get("visual_style")
        or "cinematic, high contrast, shallow depth of field, rich color, vertical composition"
    )


def picture_prompt(resolved: Any, packet: Fields, beat: Fields, data: Fields) -> str:
    """What a shot's first frame shows. A stream job's kits say it, otherwise the script does."""
    if resolved:
        return str(consistency.shot_prompt(resolved, beat, style(data)))
    return str(shots.still_prompt(packet, beat, style(data)))


def shot_kw(
    resolved: Any, lock: Fields, capability: str, beat: Fields, start: Path | None = None
) -> Fields:
    """The references and pinned model for one shot of a stream job. A beat with no references uses
    the studio's plain model, because a reference endpoint will not run without them."""
    pin = (lock.get("generators") or {}).get(capability)
    if not resolved or not pin:
        return {}
    capacity = base.get(pin["provider"]).reference_support(capability, pin["model"])["max_images"]
    if not beat.get("cast") and capability == "video":
        return {}
    refs = consistency.shot_refs(resolved, beat, capacity, start=start)
    return {"references": refs, "model": pin["model"]} if refs else {}


def kit_refs(shot: Fields) -> Fields | None:
    shas = [r["sha256"] for r in shot.get("references", []) if r["sha256"]]
    return {"kit_refs": shas} if shas else None


def last_frame(clip: Path, dst: Path) -> None:
    """The picture a clip ends on, so the next shot can pick up from exactly there."""
    media.frame_at(clip, max(media.duration(clip) - 0.05, 0.0), dst.with_suffix(".tmp.png"))
    dst.with_suffix(".tmp.png").replace(dst)


def graphics_shot(job: Job, beat: Fields, span: float, add: Add, gen: Gen, data: Fields) -> Path:
    """A composition rendered as this shot. Exact, so no model invents a number or a word."""
    folder = (job.folder / beat["graphics"]).resolve()
    if job.folder.resolve() not in folder.parents or not folder.is_dir():
        raise ContractError(f"{job.id}: {beat['id']}: no composition folder at {beat['graphics']}")
    clip = job.work / "beats" / f"{beat['id']}.video.mp4"
    p, res = gen("graphics", "graphics", folder, clip)
    add(
        id=f"{beat['id']}.video",
        kind="video",
        role="visual",
        beat_id=beat["id"],
        path=f"beats/{beat['id']}.video.mp4",
        duration_sec=media.duration(clip),
        rights=rights(data),
        provider=p.name,
        model=res.model,
        synthetic=False,
        probe=media.summarize(clip),
    )
    return clip


def take_clip(
    job: Job,
    packet: Fields,
    beat: Fields,
    still: Path,
    span: float,
    prof: Fields,
    clip_kw: Fields,
    gen: Gen,
    data: Fields,
    fallback_prompt: str,
    clip: Path,
    *,
    note: str = "",
) -> Fields:
    """Attempts at one moving shot, until one reads well or the limit is reached."""
    brief = data.get("brief") or {}
    wants_sound = bool(brief.get("clip_audio"))
    names = config.preference("video", data)
    prompt = (
        fallback_prompt
        if clip_kw and not beat.get("shot")
        else shots.motion_prompt(
            packet,
            beat,
            style(data),
            has_start_image=True,
            limit=shots.word_limit(names),
            with_sound=wants_sound,
        )
    )
    if note:
        prompt = f"{prompt} {note}"

    def make(seed: int, dst: Path) -> tuple[Any, Any]:
        return gen(
            "video",
            "video",
            prompt,
            dst,
            duration=span,
            aspect=prof.get("aspect", "9:16"),
            image=still,
            seed=seed,
            audio=wants_sound,
            est={"duration": span, "image": True, "references": bool(clip_kw)},
            **clip_kw,
        )

    if note:
        n = takes.next_take_number(job, beat["id"])
        takes.attempt(
            job,
            beat["id"],
            n,
            suffix=".mp4",
            make=make,
            assess=takes.assess_clip,
            prompt=prompt,
            note=note,
        )
    else:
        takes.make_until_good(
            job,
            beat["id"],
            brief,
            suffix=".mp4",
            make=make,
            assess=takes.assess_clip,
            prompt=prompt,
        )
    return takes.place(job, beat["id"], clip)


def lip_sync(job: Job, beat: Fields, clip: Path, span: float, gen: Gen) -> Fields:
    """Match the speaker's mouth to their line. The picture is replaced, and the line stays."""
    line = job.work / "beats" / f"{beat['id']}.voice.wav"
    synced = clip.with_suffix(".synced.mp4")
    _, res = gen("lipsync", "lipsync", clip, line, synced, est={"duration": span})
    synced.replace(clip)
    return {"lipsync_model": res.model}


def clip_ambience(
    job: Job, beat: Fields, clip: Path, brief: Fields, add: Add, data: Fields
) -> None:
    """Take the sound a clip was generated with, when the job asked a model to make it."""
    if not brief.get("clip_audio") or "sample_rate_hz" not in media.summarize(clip):
        return
    dst = job.work / "beats" / f"{beat['id']}.ambience.wav"
    media.run(["-i", str(clip), "-vn", "-ar", "48000", "-ac", "2", str(dst)])
    add(
        id=f"{beat['id']}.ambience",
        kind="audio",
        role="sfx",
        beat_id=beat["id"],
        path=f"beats/{beat['id']}.ambience.wav",
        duration_sec=media.duration(dst),
        rights=rights(data),
        provider="clip",
        model="the sound of its own clip",
        synthetic=True,
    )


def generated_ambience(
    job: Job, bid: str, cue: str, span: float, add: Add, gen: Gen, data: Fields
) -> None:
    """The sound of a place. Worth having, and no reason to stop a piece if nothing can make it."""
    dst = job.work / "beats" / f"{bid}.ambience.wav"
    try:
        p, res = gen("sfx", "sfx", cue, dst, duration=span, est={"duration": span})
    except RuntimeError as exc:
        print(f"{job.id}: {bid}: no ambience: {exc}", file=sys.stderr)
        return
    add(
        id=f"{bid}.ambience",
        kind="audio",
        role="sfx",
        beat_id=bid,
        path=f"beats/{bid}.ambience.wav",
        duration_sec=media.duration(dst),
        rights=rights(data),
        provider=p.name,
        model=res.model,
        provenance=made(res),
        prompt=cue,
        synthetic=True,
    )


def retake(job: Job, bid: str, note: str = "") -> Fields:
    """Another attempt at one shot with a new seed, leaving every other shot alone.

    A note adds to the prompt, so what a person saw wrong can be said once. The new take is used if
    it reads well, unless a person has already chosen one.
    """
    data = job.job
    packet = job.read("script_packet")
    beat = next((b for b in packet["beats"] if b["id"] == bid), None)
    if not beat:
        raise ContractError(f"{job.id}: no beat {bid}")
    manifest = job.read("asset_manifest")
    span = next(s["end_sec"] - s["start_sec"] for s in manifest["timeline"] if s["beat_id"] == bid)
    locked = consistency.for_job(job)
    resolved, lock = locked if locked else (None, {})
    still = job.work / "beats" / f"{bid}.still.png"
    clip_kw = shot_kw(resolved, lock, "video", beat, start=still)
    prof = config.profile(data.get("profile") or "short-9x16")

    def gen(capability: str, fn_name: str, *args: Any, **kw: Any) -> tuple[Any, Any]:
        return router.generate(job, capability, fn_name, *args, **kw)

    prompt = picture_prompt(resolved, packet, beat, data)
    extra = note or f"Another attempt, take {takes.next_take_number(job, bid)}."
    clip = job.work / "beats" / f"{bid}.video.mp4"
    take = take_clip(
        job, packet, beat, still, span, prof, clip_kw, gen, data, prompt, clip, note=extra
    )
    apply_chosen(job, bid)
    return take


def apply_chosen(job: Job, bid: str) -> Fields:
    """Make the chosen take the one the piece uses, and say so in its record."""
    clip = job.work / "beats" / f"{bid}.video.mp4"
    take = takes.place(job, bid, clip)
    manifest = job.read("asset_manifest")
    for asset in manifest["assets"]:
        if asset["id"] == f"{bid}.video":
            kit = {k: v for k, v in (asset.get("provenance") or {}).items() if k == "kit_refs"}
            asset.update(
                provider=take["provider"],
                model=take["model"],
                provenance={**kit, **takes.provider_meta(take)},
                sha256=sha256_file(clip),
                duration_sec=media.duration(clip),
                probe=media.summarize(clip),
            )
            if take.get("prompt"):
                asset["prompt"] = take["prompt"]
    job.write("asset_manifest", manifest)
    return take
