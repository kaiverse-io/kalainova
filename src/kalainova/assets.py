"""SCRIPT -> ASSET. Generates voice, visuals, music and sfx; writes asset_manifest.json.

Asset paths are relative to the job's work dir (out/<job_id>/), which is gitignored.
Each beat gets its own voice clip; the clips are joined into one voice track so
word timings live on a single timeline the editor can cut against.
"""

from __future__ import annotations

import sys
from pathlib import Path

from . import config, consistency, kits, media
from .jobfs import Job
from .providers import base, router

# Air after a line follows how it ends: a full stop takes a breath, a clause runs on.
PAUSE_AFTER = {".": 0.34, "?": 0.38, "!": 0.34, "…": 0.45, ",": 0.14, ":": 0.2, ";": 0.2}
PAUSE_DEFAULT = 0.18


def _pause(text: str) -> float:
    return PAUSE_AFTER.get(text.rstrip()[-1:], PAUSE_DEFAULT)


def _rights(job: dict) -> str:
    return job.get("rights", "owned")


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
        provenance=res.meta.get("provenance"),
        prompt=text if role == "music" else None,
    )


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
    t = float(prof.get("open_sec", 0.0))
    closing = float(prof.get("close_sec", 0.0))
    opening_ms = int(t * 1000)
    voice_parts: list[Path] = []
    voice_makers: list[tuple] = []
    pauses: list[float] = []
    all_beats = packet["beats"]
    for n, beat in enumerate(all_beats):
        bid = beat["id"]
        start = t
        if "audio" in media_kinds or "video" in media_kinds:
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
            t += max(2.0, len(beat["text"].split()) / 2.6)
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
            provenance={"kit_voices": kit_voices} if kit_voices else res.meta.get("provenance"),
            synthetic=True,
            probe=media.summarize(work / "voice.wav"),
        )

    # --- visuals per beat ---------------------------------------------------
    if "video" in media_kinds or "still" in media_kinds:
        video_budget = int(
            brief.get("max_video_beats") if brief.get("max_video_beats") is not None else 3
        )
        for i, beat in enumerate(packet["beats"]):
            bid = beat["id"]
            span = timeline[i]["end_sec"] - timeline[i]["start_sec"]
            prompt = (
                consistency.shot_prompt(resolved, beat, _style(data))
                if resolved
                else f"{beat.get('visual_cue') or beat['text']}. {_style(data)}"
            )
            still_kw = _shot_kw(resolved, lock, "image", beat)
            still = work / "beats" / f"{bid}.still.png"
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
                provenance=_kit_refs(still_kw) or res.meta.get("provenance"),
                prompt=prompt,
                synthetic=True,
                probe=media.summarize(still),
            )
            if beat.get("visual_kind") == "video" and video_budget > 0 and "video" in media_kinds:
                clip = work / "beats" / f"{bid}.video.mp4"
                clip_kw = _shot_kw(resolved, lock, "video", beat, start=still)
                clip_est = {"duration": span, "image": True, "references": bool(clip_kw)}
                try:
                    p, res = _gen(
                        "video",
                        "video",
                        prompt,
                        clip,
                        duration=span,
                        aspect=prof.get("aspect", "9:16"),
                        image=still,
                        est=clip_est,
                        **clip_kw,
                    )
                    video_budget -= 1
                    add(
                        id=f"{bid}.video",
                        kind="video",
                        role="visual",
                        beat_id=bid,
                        path=f"beats/{bid}.video.mp4",
                        duration_sec=media.duration(clip),
                        rights=_rights(data),
                        provider=p.name,
                        model=res.model,
                        provenance=_kit_refs(clip_kw) or res.meta.get("provenance"),
                        prompt=prompt,
                        synthetic=True,
                        probe=media.summarize(clip),
                    )
                except (
                    RuntimeError
                ) as exc:  # still + motion covers this beat, and the operator is told
                    print(
                        f"{job.id}: {bid}: no video clip, using the still: {exc}", file=sys.stderr
                    )

    # --- music bed and transition sfx ---------------------------------------
    if "audio" in media_kinds or "video" in media_kinds:
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
    if words:
        manifest["words"] = words
    if resolved:
        manifest["kit_lock_sha256"] = consistency.lock_sha256(job)
    job.write("asset_manifest", manifest)
    return manifest
