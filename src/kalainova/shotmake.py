"""One shot: where it starts, its takes, its mouth, and the sound of its place.

Every shot that moves is made here, whether by a first run or a retake a person asked for, so both
follow the same promise and the same record.
"""

from __future__ import annotations

import json
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import config, consistency, media, shots, takes, trace
from .bar import judges
from .blobstore import sha256_file
from .editor import singing
from .jobfs import ContractError, Job
from .providers import base, rehearsal, router
from .providers.contract import (
    Card,
    GraphicsRequest,
    ImageRequest,
    LipsyncRequest,
    Pin,
    Reference,
    Request,
    Result,
    SfxRequest,
    SingRequest,
    VideoRequest,
)

Fields = dict[str, Any]
Gen = Callable[..., tuple[base.Provider, Result]]  # (request, **router options)
Add = Callable[..., Any]


@dataclass(frozen=True)
class Held:
    """What holds a shot to its kits: the references, and the model pinned to take them."""

    references: tuple[Reference, ...] = ()
    pin: Pin | None = None

    def __bool__(self) -> bool:
        return bool(self.references)

    def model_at(self, provider: str) -> str | None:
        return self.pin.model if self.pin and self.pin.provider == provider else None


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
    """What a shot's first frame shows. A stream job's kits say it, otherwise the script does. A
    shot that sings starts on a mouth in full view, since the voice has to move it."""
    if resolved:
        said = consistency.shot_prompt(resolved, beat, style(data))
    else:
        said = shots.still_prompt(packet, beat, style(data))
    return f"{said} {shots.MOUTH_CLEAR}" if beat.get("sings") else str(said)


def shot_kw(
    resolved: Any, lock: Fields, capability: str, beat: Fields, start: Path | None = None
) -> Held:
    """The references and pinned model for one shot of a stream job. A beat with no references uses
    the studio's plain model, because a reference endpoint will not run without them."""
    pin = (lock.get("generators") or {}).get(capability)
    if not resolved or not pin:
        return Held()
    support = base.get(pin["provider"]).inputs(capability, pin["model"])
    if not beat.get("cast") and capability == "video":
        return Held()
    # A model that takes the first frame on its own gets the still there, so every reference slot
    # goes to the kit; otherwise the still rides along as the first reference.
    first = None if support.start_with_references else start
    refs = consistency.shot_refs(resolved, beat, support.references, start=first)
    if not refs:
        return Held()
    held = tuple(
        Reference(path=r["path"], label=r["label"], group=r["group"], sha256=r["sha256"])
        for r in refs
    )
    return Held(held, Pin(provider=pin["provider"], model=pin["model"]))


def kit_refs(shot: Held) -> Fields | None:
    shas = [r.sha256 for r in shot.references if r.sha256]
    return {"kit_refs": shas} if shas else None


def reused_origin(job: Job, path: Path, shot: Held) -> Fields:
    """Who made a file this job made earlier and now reuses, from the router's record of the same
    bytes, so the reuse keeps its model and its kit references. The references count only when
    the shot's pinned model is the one that made it."""
    sha = sha256_file(path)
    log = job.folder / router.GENERATIONS
    lines = log.read_text().splitlines() if log.exists() else []
    entries = [json.loads(line) for line in lines if line.strip()]
    entry = next((e for e in reversed(entries) if e.get("sha256") == sha), None)
    if entry is None:
        return {"provider": "animatic", "model": "accepted animatic still"}
    refs = kit_refs(shot) if shot.pin and shot.pin.model == entry["model"] else None
    return {
        "provider": entry["provider"],
        "model": entry["model"],
        "provenance": {**(refs or {}), "sha256": sha, "accepted_in": "animatic"},
    }


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
    p, res = gen(GraphicsRequest(folder=folder, dst=clip))
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


def end_frame_used(job: Job, beat: Fields, held: Held) -> bool:
    """Whether this shot has a last frame and the model that will run it can be given one."""
    if not (beat.get("shot") or {}).get("last_frame"):
        return False
    first = router.first_usable(job, "video")
    return bool(first and first.inputs("video", held.model_at(first.name)).end_frame)


def _end_still(job: Job, beat: Fields, prof: Fields, data: Fields, gen: Gen) -> Path:
    """The picture a shot ends on, made once and reused while it stands."""
    dst = job.work / "beats" / f"{beat['id']}.end.png"
    if dst.exists():
        return dst
    text = str(beat["shot"]["last_frame"]).rstrip(".")
    theme = (data.get("edit") or {}).get("theme", "studio")
    gen(
        ImageRequest(
            prompt=f"{text}. {style(data)}",
            dst=dst,
            width=int(prof.get("width", 1080)),
            height=int(prof.get("height", 1920)),
            card=Card(title=text, palette=0, theme=theme),
        )
    )
    return dst


def take_clip(
    job: Job,
    packet: Fields,
    beat: Fields,
    still: Path,
    span: float,
    prof: Fields,
    clip_kw: Held,
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
    end = _end_still(job, beat, prof, data, gen) if end_frame_used(job, beat, clip_kw) else None
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
    floor = int(prof.get("character_source_min_px") or 0)
    assess = takes.held_to(floor) if floor and beat.get("cast") else takes.assess_clip
    line = job.work / "beats" / f"{beat['id']}.voice.wav"
    sung = bool(beat.get("sings")) and singing.sung_line(job, beat, line) >= singing.NO_VOICE
    if beat.get("sings") and not sung:
        print(f"{job.id}: {beat['id']}: no singing in its span, so it is made as a plain clip")
    assess = judged_sung(assess, line) if sung else assess

    def make(seed: int, dst: Path) -> tuple[Any, Any]:
        if sung:  # the voice moves the face and the body in the same call, so nothing syncs after
            return gen(
                SingRequest(
                    prompt=prompt,
                    still=still,
                    audio=line,
                    dst=dst,
                    aspect=prof.get("aspect", "9:16"),
                    references=clip_kw.references,
                    seed=seed,
                )
            )
        request: Request = VideoRequest(
            prompt=prompt,
            dst=dst,
            duration=span,
            aspect=prof.get("aspect", "9:16"),
            start=still,
            end=end,
            references=clip_kw.references,
            seed=seed,
            sound=wants_sound,
            pin=clip_kw.pin,
        )
        return gen(request)

    if note:
        n = takes.next_take_number(job, beat["id"])
        takes.attempt(
            job,
            beat["id"],
            n,
            suffix=".mp4",
            make=make,
            assess=assess,
            prompt=prompt,
            note=note,
            extra={"retake": True},
        )
    else:
        takes.make_until_good(
            job,
            beat["id"],
            brief,
            suffix=".mp4",
            make=make,
            assess=assess,
            prompt=prompt,
        )
    taken = takes.place(job, beat["id"], clip)
    if (beat.get("shot") or {}).get("last_frame"):
        taken["end_frame"] = "sent as an image" if end else "not used: the model takes none"
    return taken


def lip_sync(job: Job, beat: Fields, clip: Path, span: float, gen: Gen) -> Fields:
    """Match a speaker's mouth to their spoken line. The picture is replaced, and the line stays.

    The vendor cuts to the shorter input, and a line is shorter than its shot by the pause after it.
    So the line is padded with silence to the clip's length first, and the clip as it was before the
    sync is kept beside the synced one. A shot that sings is never synced afterwards: it is sung in
    the call that makes it (take_clip)."""
    line = job.work / "beats" / f"{beat['id']}.voice.wav"
    length = media.duration(clip)
    padded = line.with_suffix(".padded.wav")
    media.run(["-i", str(line), "-af", "apad", "-t", f"{length:.3f}", str(padded)])
    synced = clip.with_suffix(".synced.mp4")
    before = clip.with_name(f"{beat['id']}.video.presync.mp4")
    _, res = gen(LipsyncRequest(video=clip, audio=padded, dst=synced))
    shutil.copyfile(clip, before)
    synced.replace(clip)
    return {"lipsync_model": res.model, "presync_path": f"beats/{before.name}"}


def judged_sung(assess: takes.Assess, line: Path) -> takes.Assess:
    """A sung take is also judged on how its lips follow its line (judges.lipsync), with the line
    itself laid on its picture, so what is scored is the vocal the piece plays over it."""
    if not judges.configured("lipsync") or rehearsal.active() is not None:
        return assess  # a rehearsal's stand-in is a test pattern, with no lips to judge

    def judged(path: Path) -> tuple[Fields, bool]:
        readings, ok = assess(path)
        heard = path.with_suffix(".sync.mp4")
        media.run(["-i", str(path), "-i", str(line), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                   "-shortest", str(heard)])  # fmt: skip
        return {**readings, **judges.of_take("lipsync", heard)}, ok

    return judged


def after_take(
    job: Job, beat: Fields, clip: Path, span: float, gen: Gen, take: Fields
) -> Fields | None:
    """A placed take before the edit: a spoken line's mouth is synced to it; a sung take's picture
    is slipped onto its line by the offset its lip judge measured (singing.slip)."""
    if synced_after(beat):
        return lip_sync(job, beat, clip, span, gen)
    if not beat.get("sings"):
        return None
    slipped = singing.slip(clip, singing.offset_of(take.get("readings") or {}))
    return {"slipped_sec": slipped} if slipped else None


def synced_after(beat: Fields) -> bool:
    """Whether a mouth is synced to its line after the clip is made: a line spoken on camera."""
    return bool(beat.get("on_camera")) and not beat.get("sings")


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
        p, res = gen(SfxRequest(prompt=cue, dst=dst, duration=span))
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


@trace.scoped
def retake(job: Job, bid: str, note: str = "") -> Fields:
    """Another attempt at one shot with a new seed, leaving every other shot alone.

    A note adds to the prompt, so what a person saw wrong can be said once. The new take is used if
    it reads well, unless a person has already chosen one.
    """
    trace.relabel(shot=bid)
    data = job.job
    packet = job.read("script_packet")
    beat = next((b for b in packet["beats"] if b["id"] == bid), None)
    if not beat:
        raise ContractError(f"{job.id}: no beat {bid}")
    takes.check_retake(job, bid, data.get("brief") or {})
    if not note:
        found = takes.finding_for(job, bid)
        note = str((found or {}).get("suggested_prompt_change") or (found or {}).get("note") or "")
    manifest = job.read("asset_manifest")
    span = next(s["end_sec"] - s["start_sec"] for s in manifest["timeline"] if s["beat_id"] == bid)
    locked = consistency.for_job(job)
    resolved, lock = locked if locked else (None, {})
    still = job.work / "beats" / f"{bid}.still.png"
    clip_kw = shot_kw(resolved, lock, "video", beat, start=still)
    prof = config.profile(data.get("profile") or "short-9x16")

    def gen(request: Request, **kw: Any) -> tuple[base.Provider, Result]:
        return router.generate(job, request, **kw)

    prompt = picture_prompt(resolved, packet, beat, data)
    extra = note or f"Another attempt, take {takes.next_take_number(job, bid)}."
    clip = job.work / "beats" / f"{bid}.video.mp4"
    take = take_clip(
        job, packet, beat, still, span, prof, clip_kw, gen, data, prompt, clip, note=extra
    )
    apply_chosen(job, bid, gen)
    return take


MOTION_REASON = "no take moved enough"
SOURCE_REASON = "no take was made at the profile's source size"


def motion_break(job: Job, bid: str, take: Fields, allow_stills: bool) -> Fields | None:
    """A shot whose chosen take did not pass the motion reading broke its promise, unless a person
    accepted stills or chose that take. The failing clip stays on disk for a person to look at.
    A character take made under the profile's source size breaks it too, stills allowed or not."""
    readings = take.get("readings") or {}
    small = readings.get("below_source_floor")
    if take.get("ok") or (allow_stills and not small):
        return None
    entry = takes.load(job)["shots"].get(bid) or {}
    if entry.get("chosen_by") == "human":
        return None
    if small:
        why = f"take {take['n']} is {small}; look at it, and choose it only if it holds up"
        return {"beat_id": bid, "reason": f"{SOURCE_REASON} ({why})"}
    if readings.get("unmeasurable"):
        why = f"take {take['n']} could not be measured: {readings['unmeasurable']}; look at it"
    else:
        why = f"take {take['n']} read {readings.get('shot_motion')}"
    return {"beat_id": bid, "reason": f"{MOTION_REASON} ({why})"}


def apply_chosen(job: Job, bid: str, gen: Gen | None = None) -> Fields:
    """Make the chosen take the one the piece uses, and say so in its record. A take is placed as
    the model made it, so a line spoken on camera is lip-synced again, through the same gate as any
    paid call: a sync no package covers stops here rather than leave the mouth unsynced."""
    clip = job.work / "beats" / f"{bid}.video.mp4"
    take = takes.place(job, bid, clip)
    synced = _resync(job, bid, clip, gen, take)
    manifest = job.read("asset_manifest")
    allowed = bool((job.job.get("brief") or {}).get("allow_stills"))
    breaks = [
        b
        for b in manifest.get("promise_breaks") or []
        if not (b["beat_id"] == bid and str(b["reason"]).startswith((MOTION_REASON, SOURCE_REASON)))
    ]
    broken = motion_break(job, bid, take, allowed)
    breaks += [broken] if broken else []
    if breaks:
        manifest["promise_breaks"] = breaks
    else:
        manifest.pop("promise_breaks", None)
    for asset in manifest["assets"]:
        if asset["id"] == f"{bid}.video":
            kit = {k: v for k, v in (asset.get("provenance") or {}).items() if k == "kit_refs"}
            asset.update(
                provider=take["provider"],
                model=take["model"],
                provenance={**kit, **takes.provider_meta(take), **(synced or {})},
                sha256=sha256_file(clip),
                duration_sec=media.duration(clip),
                probe=media.summarize(clip),
            )
            if take.get("prompt"):
                asset["prompt"] = take["prompt"]
    job.write("asset_manifest", manifest)
    return take


def _resync(job: Job, bid: str, clip: Path, gen: Gen | None, take: Fields) -> Fields | None:
    """after_take, again, on the take just placed: a spoken line synced, a sung one slipped."""
    beats = job.read("script_packet").get("beats", []) if job.has("script_packet") else []
    beat = next((b for b in beats if b["id"] == bid), None)
    if not beat or not (synced_after(beat) or beat.get("sings")):
        return None
    timeline = job.read("asset_manifest").get("timeline") or []
    span = next(s["end_sec"] - s["start_sec"] for s in timeline if s["beat_id"] == bid)

    def routed(request: Request, **kw: Any) -> tuple[base.Provider, Result]:
        return router.generate(job, request, **kw)

    return after_take(job, beat, clip, span, gen or routed, take)
