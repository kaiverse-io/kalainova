"""SCRIPT -> ASSET. Generates voice, visuals, music and sfx; writes asset_manifest.json.

Asset paths are relative to the job's work dir (out/<job_id>/), which is gitignored.
Each beat gets its own voice clip; the clips are joined into one voice track so
word timings live on a single timeline the editor can cut against.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import config, consistency, kits, media, shots, takes
from .blobstore import sha256_file
from .jobfs import ContractError, Job
from .providers import base, router

# Air after a line follows how it ends: a full stop takes a breath, a clause runs on.
PAUSE_AFTER = {".": 0.34, "?": 0.38, "!": 0.34, "…": 0.45, ",": 0.14, ":": 0.2, ";": 0.2}
PAUSE_DEFAULT = 0.18


def _pause(text: str) -> float:
    return PAUSE_AFTER.get(text.rstrip()[-1:], PAUSE_DEFAULT)


def _rights(job: dict) -> str:
    return job["rights"]  # required on every job, and stated by a person


def _made(res, extra: dict | None = None) -> dict | None:
    """What a record of this file needs to say about how it was made."""
    meta = {k: v for k, v in (res.meta or {}).items() if k != "words"}
    found = {**dict(meta.pop("provenance", None) or {}), **meta, **(extra or {})}
    return found or None


def _placeholder_run(data: dict) -> bool:
    """No real model would make the pictures, so nothing here can be approved anyway."""
    usable, _ = router._usable("image", config.preference("image", data))
    return bool(usable) and usable[0].placeholder


def _can_narrate(brief: dict) -> bool:
    return brief.get("narration", True) is not False


def _style(job: dict) -> str:
    brief = job.get("brief") or {}
    return (
        brief.get("visual_style")
        or "cinematic, high contrast, shallow depth of field, rich color, vertical composition"
    )


def _shot_kw(resolved, lock: dict, capability: str, beat: dict, start: Path | None = None) -> dict:
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


def _kit_refs(shot: dict) -> dict | None:
    shas = [r["sha256"] for r in shot.get("references", []) if r["sha256"]]
    return {"kit_refs": shas} if shas else None


def _kit_audio(root: Path, entry: dict, dst: Path, seconds: float) -> None:
    """A fixed sound from the kit, looped or trimmed to length. Never regenerated."""
    src = kits.blob_path(root, entry)
    length = ["-stream_loop", "-1", "-i", str(src), "-t", f"{seconds:.3f}"]
    media.run([*length, "-ar", "48000", "-ac", "2", str(dst)])


def _sound(
    job: Job, asset_id: str, role: str, fixed: dict | None, secs: float, add, gen, data
) -> None:
    """The music bed or the transition: the kit's file when it fixes one, otherwise generated."""
    dst = job.work / f"{asset_id}.wav"
    common = {"id": asset_id, "kind": "audio", "role": role, "path": dst.name, "synthetic": True}
    if fixed:
        _kit_audio(job.folder.parents[1], fixed, dst, secs)
        add(
            **common,
            duration_sec=media.duration(dst),
            rights=_rights(data),
            provider="kit",
            model="kit",
            provenance={"kit_sha256": fixed["sha256"]},
        )
        return
    brief = data.get("brief") or {}
    text = (
        (brief.get("music") or "warm modern instrumental bed, steady pulse, no vocals")
        if role == "music"
        else "soft cinematic whoosh transition"
    )
    p, res = gen(role, role, text, dst, duration=secs, est={"duration": secs})
    add(
        **common,
        duration_sec=media.duration(dst),
        rights=_rights(data),
        provider=p.name,
        model=res.model,
        provenance=_made(res),
        prompt=text if role == "music" else None,
    )


def _last_frame(clip: Path, dst: Path) -> None:
    """The picture a clip ends on, so the next shot can pick up from exactly there."""
    media.frame_at(clip, max(media.duration(clip) - 0.05, 0.0), dst.with_suffix(".tmp.png"))
    dst.with_suffix(".tmp.png").replace(dst)


def _track(job: Job, track: str, total: float, add, data: dict) -> None:
    """A finished piece of music from another job: the picture is cut to it, and it is not remade."""
    src = job.work / track
    dst = job.work / "music.wav"
    media.run(["-i", str(src), "-t", f"{total + 1.0:.3f}", "-ar", "48000", "-ac", "2", str(dst)])
    add(
        id="music",
        kind="audio",
        role="music",
        path=dst.name,
        duration_sec=media.duration(dst),
        rights=_rights(data),
        provider="track",
        model=(data.get("brief") or {}).get("track_model", "a finished track"),
        provenance={"source_sha256": sha256_file(src), "parent_job": data.get("parent_job_id")},
        synthetic=True,
    )


def _graphics_shot(job: Job, beat: dict, span: float, add, gen, data: dict) -> Path:
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
        rights=_rights(data),
        provider=p.name,
        model=res.model,
        synthetic=False,
        probe=media.summarize(clip),
    )
    return clip


def _take_clip(
    job: Job,
    packet: dict,
    beat: dict,
    still: Path,
    span: float,
    prof: dict,
    clip_kw: dict,
    gen,
    data: dict,
    fallback_prompt: str,
    clip: Path,
    *,
    note: str = "",
) -> dict:
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
            _style(data),
            has_start_image=True,
            limit=shots.word_limit(names),
            with_sound=wants_sound,
        )
    )
    if note:
        prompt = f"{prompt} {note}"

    def make(seed: int, dst: Path) -> tuple:
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


def _lip_sync(job: Job, beat: dict, clip: Path, span: float, gen) -> dict:
    """Match the speaker's mouth to their line. The picture is replaced, and the line stays as it was."""
    line = job.work / "beats" / f"{beat['id']}.voice.wav"
    synced = clip.with_suffix(".synced.mp4")
    _, res = gen("lipsync", "lipsync", clip, line, synced, est={"duration": span})
    synced.replace(clip)
    return {"lipsync_model": res.model}


def _clip_ambience(job: Job, beat: dict, clip: Path, brief: dict, add, data: dict) -> None:
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
        rights=_rights(data),
        provider="clip",
        model="the sound of its own clip",
        synthetic=True,
    )


def _generated_ambience(job: Job, bid: str, cue: str, span: float, add, gen, data: dict) -> None:
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
        rights=_rights(data),
        provider=p.name,
        model=res.model,
        provenance=_made(res),
        prompt=cue,
        synthetic=True,
    )


def retake(job: Job, bid: str, note: str = "") -> dict:
    """Another attempt at one shot with a new seed, leaving every other shot alone.

    A note adds to the prompt, so what a person saw wrong can be said once. The chosen take moves to
    the new one only if a person has not already chosen.
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
    clip_kw = _shot_kw(resolved, lock, "video", beat, start=still)
    prof = config.profile(data.get("profile") or "short-9x16")

    def gen(capability: str, fn_name: str, *args, **kw):
        return router.generate(job, capability, fn_name, *args, **kw)

    prompt = (
        consistency.shot_prompt(resolved, beat, _style(data))
        if resolved
        else shots.still_prompt(packet, beat, _style(data))
    )
    extra = note or f"Another attempt, take {takes.next_take_number(job, bid)}."
    clip = job.work / "beats" / f"{bid}.video.mp4"
    take = _take_clip(
        job, packet, beat, still, span, prof, clip_kw, gen, data, prompt, clip, note=extra
    )
    apply_chosen(job, bid)
    return take


def apply_chosen(job: Job, bid: str) -> dict:
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


def run(job: Job, *, force: bool = False) -> dict:
    if job.has("asset_manifest") and not force:
        return job.read("asset_manifest")
    data = job.job
    packet = job.read("script_packet")
    prof = config.profile(data.get("profile") or "short-9x16")
    W, H = int(prof.get("width", 1080)), int(prof.get("height", 1920))
    work = job.work
    (work / "beats").mkdir(exist_ok=True)
    brief = data.get("brief") or {}
    media_kinds = set(data.get("media", []))
    if force:
        takes.forget(job)
    allow_stills = bool(brief.get("allow_stills")) or _placeholder_run(data)
    video_budget = int(
        brief.get("max_video_beats") if brief.get("max_video_beats") is not None else 3
    )
    plan_problems = shots.review(
        packet,
        budget=video_budget,
        allow_stills=allow_stills,
        wants_video="video" in media_kinds,
        style=_style(data),
        limit=shots.word_limit(config.preference("video", data)),
    )
    for problem in plan_problems:
        if problem["status"] == "warn":
            print(f"{job.id}: [{problem['id']}] {problem['detail']}", file=sys.stderr)
    refused = [p["detail"] for p in plan_problems if p["status"] == "fail"]
    if refused:
        raise ContractError(f"{job.id}: the plan cannot be made as written: " + "; ".join(refused))
    locked = consistency.for_job(job)
    resolved, lock = locked if locked else (None, {})
    cast = lock.get("cast", [])
    if resolved:
        consistency.check_script(job, resolved, packet, cast)
    kit_voices: dict[str, str] = {}
    fixed_sound = (resolved.shared.get("music") or {}) if resolved else {}

    def _gen(capability: str, fn_name: str, *args, **kw):
        return router.generate(job, capability, fn_name, *args, fresh=force, **kw)

    assets: list[dict] = []
    words: list[dict] = []
    timeline: list[dict] = []

    def add(**a):
        a = {k: v for k, v in a.items() if v not in (None, "", [])}
        assets.append(a)
        return a

    # --- voice, per beat, then joined ------------------------------------
    # a film opens on picture and music, and holds after its last word; a reel starts on the words
    narrated = _can_narrate(brief)  # a piece cut to a finished track starts when the track does
    t = float(prof.get("open_sec", 0.0)) if narrated else 0.0
    closing = float(prof.get("close_sec", 0.0)) if narrated else 0.0
    opening_ms = int(t * 1000)
    voice_parts: list[Path] = []
    voice_makers: list[tuple] = []
    pauses: list[float] = []
    all_beats = packet["beats"]
    for n, beat in enumerate(all_beats):
        bid = beat["id"]
        start = t
        if ("audio" in media_kinds or "video" in media_kinds) and _can_narrate(brief):
            dst = work / "beats" / f"{bid}.voice.wav"
            voice_kw: dict = {"voice": brief.get("voice")}
            if resolved:
                fixed = consistency.voice_for(resolved, beat, cast)
                kit_voices[bid] = fixed["voice_id"]
                voice_kw = {
                    "voice": fixed["voice_id"],
                    "model": fixed["model"],
                    "only": [fixed["provider"]],
                }
                if fixed.get("settings"):
                    voice_kw["settings"] = fixed["settings"]
            # neighbouring lines let a model keep one read across the cuts
            voice_kw["previous_text"] = all_beats[n - 1]["text"] if n else None
            voice_kw["next_text"] = all_beats[n + 1]["text"] if n + 1 < len(all_beats) else None
            p, res = _gen(
                "voice",
                "voice",
                beat["text"],
                dst,
                est={"chars": len(beat["text"])},
                **voice_kw,
            )
            dur = media.duration(dst)
            for w in res.words:
                words.append(
                    {
                        **w,
                        "start_sec": round(w["start_sec"] + start, 3),
                        "end_sec": round(w["end_sec"] + start, 3),
                    }
                )
            voice_parts.append(dst)
            voice_makers.append((p, res))
            pauses.append(_pause(beat["text"]))
            t += dur + pauses[-1]
        else:
            t += float(beat.get("duration_sec") or max(2.0, len(beat["text"].split()) / 2.6))
        timeline.append(
            {"beat_id": bid, "start_sec": round(start if n else 0.0, 3), "end_sec": round(t, 3)}
        )
    total = round(t + closing, 3)
    if timeline:
        timeline[-1]["end_sec"] = total

    if voice_parts:
        pauses[-1] += closing
        # pad each clip with its pause, then concat via the concat filter (no list files, no shell)
        args: list[str] = []
        for part in voice_parts:
            args += ["-i", str(part)]
        filt = "".join(
            f"[{i}:a]aresample=48000,{f'adelay={opening_ms}:all=1,' if opening_ms and not i else ''}"
            f"apad=pad_dur={pauses[i]}[a{i}];"
            for i in range(len(voice_parts))
        )
        filt += (
            "".join(f"[a{i}]" for i in range(len(voice_parts)))
            + f"concat=n={len(voice_parts)}:v=0:a=1[out]"
        )
        media.run(
            [*args, "-filter_complex", filt, "-map", "[out]", "-ac", "1", str(work / "voice.wav")]
        )
        # one manifest entry covers every beat, so one local beat after a fallback marks the whole track
        p, res = next((m for m in voice_makers if m[0].name == "local"), voice_makers[-1])
        add(
            id="voice",
            kind="audio",
            role="voice",
            path="voice.wav",
            duration_sec=media.duration(work / "voice.wav"),
            rights=_rights(data),
            provider=p.name,
            model=res.model,
            provenance={"kit_voices": kit_voices} if kit_voices else _made(res),
            synthetic=True,
            probe=media.summarize(work / "voice.wav"),
        )

    # --- visuals per beat ---------------------------------------------------
    breaks: list[dict] = []
    if "video" in media_kinds or "still" in media_kinds:
        previous_clip: Path | None = None
        for i, beat in enumerate(packet["beats"]):
            bid = beat["id"]
            span = timeline[i]["end_sec"] - timeline[i]["start_sec"]
            if beat.get("graphics"):
                previous_clip = _graphics_shot(job, beat, span, add, _gen, data)
                continue
            prompt = (
                consistency.shot_prompt(resolved, beat, _style(data))
                if resolved
                else shots.still_prompt(packet, beat, _style(data))
            )
            still_kw = _shot_kw(resolved, lock, "image", beat)
            still = work / "beats" / f"{bid}.still.png"
            if beat.get("continues") and previous_clip and previous_clip.exists():
                _last_frame(previous_clip, still)
                add(
                    id=f"{bid}.still",
                    kind="still",
                    role="visual",
                    beat_id=bid,
                    path=f"beats/{bid}.still.png",
                    rights=_rights(data),
                    provider="chained",
                    model="last frame of the shot before",
                    provenance={"chained_from": previous_clip.name},
                    synthetic=True,
                    probe=media.summarize(still),
                )
            else:
                p, res = _gen(
                    "image",
                    "image",
                    prompt,
                    still,
                    width=W,
                    height=H,
                    title=beat.get("on_screen") or beat["text"],
                    palette=i,
                    style=(data.get("edit") or {}).get("theme", "studio"),
                    **still_kw,
                )
                add(
                    id=f"{bid}.still",
                    kind="still",
                    role="visual",
                    beat_id=bid,
                    path=f"beats/{bid}.still.png",
                    rights=_rights(data),
                    provider=p.name,
                    model=res.model,
                    provenance=_made(res, _kit_refs(still_kw)),
                    prompt=prompt,
                    synthetic=True,
                    probe=media.summarize(still),
                )
            previous_clip = None
            if beat.get("visual_kind") != "video" or "video" not in media_kinds:
                continue
            if video_budget <= 0:
                breaks.append({"beat_id": bid, "reason": "over the video budget"})
                continue
            clip = work / "beats" / f"{bid}.video.mp4"
            clip_kw = _shot_kw(resolved, lock, "video", beat, start=still)
            try:
                take = _take_clip(
                    job, packet, beat, still, span, prof, clip_kw, _gen, data, prompt, clip
                )
                video_budget -= 1
                synced = _lip_sync(job, beat, clip, span, _gen) if beat.get("on_camera") else None
                add(
                    id=f"{bid}.video",
                    kind="video",
                    role="visual",
                    beat_id=bid,
                    path=f"beats/{bid}.video.mp4",
                    duration_sec=media.duration(clip),
                    rights=_rights(data),
                    provider=take["provider"],
                    model=take["model"],
                    provenance={
                        **(_kit_refs(clip_kw) or {}),
                        **takes.provider_meta(take),
                        **(synced or {}),
                    },
                    prompt=take.get("prompt"),
                    synthetic=True,
                    probe=media.summarize(clip),
                )
                previous_clip = clip
                _clip_ambience(job, beat, clip, brief, add, data)
            except RuntimeError as exc:
                if not allow_stills:
                    raise ContractError(
                        f"{job.id}: {bid} asked to move and could not: {exc}. "
                        "Fix the provider, or set brief.allow_stills to accept a still here."
                    ) from exc
                breaks.append({"beat_id": bid, "reason": str(exc)[:300]})
                print(f"{job.id}: {bid}: no video clip, using the still: {exc}", file=sys.stderr)

    # --- the sound of each place --------------------------------------------
    if "audio" in media_kinds or "video" in media_kinds:
        have = {a["id"] for a in assets}
        for i, beat in enumerate(packet["beats"]):
            cue = beat.get("ambience")
            if cue and f"{beat['id']}.ambience" not in have:
                span = timeline[i]["end_sec"] - timeline[i]["start_sec"]
                _generated_ambience(job, beat["id"], cue, span, add, _gen, data)

    # --- music bed and transition sfx ---------------------------------------
    if "audio" in media_kinds or "video" in media_kinds:
        if brief.get("track"):
            _track(job, brief["track"], total, add, data)
        else:
            _sound(job, "music", "music", fixed_sound.get("theme"), total + 1.0, add, _gen, data)
        edit_opts = data.get("edit") or {}
        if edit_opts.get("whoosh", edit_opts.get("theme", "studio") != "studio"):
            _sound(job, "whoosh", "sfx", fixed_sound.get("whoosh"), 0.6, add, _gen, data)

    manifest = {
        "schema_version": "0.1",
        "job_id": data["job_id"],
        "assets": assets,
        "timeline": timeline,
        "duration_sec": total,
    }
    if words or brief.get("words"):
        manifest["words"] = words or list(brief["words"])
    if breaks:
        manifest["promise_breaks"] = breaks
    if resolved:
        manifest["kit_lock_sha256"] = consistency.lock_sha256(job)
    job.write("asset_manifest", manifest)
    return manifest
