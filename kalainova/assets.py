"""SCRIPT -> ASSET. Generates voice, visuals, music and sfx; writes asset_manifest.json.

Asset paths are relative to the job's work dir (out/<job_id>/), which is gitignored.
Each beat gets its own voice clip; the clips are joined into one voice track so
word timings live on a single timeline the editor can cut against.
"""

from __future__ import annotations

from pathlib import Path

import sys

from . import config, media
from .jobfs import Job
from .providers import router

GAP = 0.12  # seconds of air between beats


def _rights(job: dict) -> str:
    return job.get("rights", "owned")


def _style(job: dict) -> str:
    brief = job.get("brief") or {}
    return brief.get("visual_style") or "cinematic, high contrast, shallow depth of field, rich color, vertical composition"


def run(job: Job, *, force: bool = False) -> dict:
    if job.has("asset_manifest") and not force:
        return job.read("asset_manifest")
    data = job.job
    packet = job.read("script_packet")
    prof = config.profile((data.get("profile") or "short-9x16"))
    W, H = int(prof.get("width", 1080)), int(prof.get("height", 1920))
    work = job.work
    (work / "beats").mkdir(exist_ok=True)
    brief = data.get("brief") or {}
    media_kinds = set(data.get("media", []))

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
    t = 0.0
    voice_parts: list[Path] = []
    voice_makers: list[tuple] = []
    for beat in packet["beats"]:
        bid = beat["id"]
        start = t
        if "audio" in media_kinds or "video" in media_kinds:
            dst = work / "beats" / f"{bid}.voice.wav"
            p, res = _gen("voice", "voice", beat["text"], dst, voice=brief.get("voice"), est={"chars": len(beat["text"])})
            dur = media.duration(dst)
            for w in res.words:
                words.append({**w, "start_sec": round(w["start_sec"] + start, 3), "end_sec": round(w["end_sec"] + start, 3)})
            voice_parts.append(dst)
            voice_makers.append((p, res))
            t += dur + GAP
        else:
            t += max(2.0, len(beat["text"].split()) / 2.6)
        timeline.append({"beat_id": bid, "start_sec": round(start, 3), "end_sec": round(t, 3)})
    total = round(t, 3)

    if voice_parts:
        # pad each clip with GAP of silence, then concat via the concat filter (no list files, no shell)
        args: list[str] = []
        for part in voice_parts:
            args += ["-i", str(part)]
        filt = "".join(f"[{i}:a]aresample=48000,apad=pad_dur={GAP}[a{i}];" for i in range(len(voice_parts)))
        filt += "".join(f"[a{i}]" for i in range(len(voice_parts))) + f"concat=n={len(voice_parts)}:v=0:a=1[out]"
        media.run([*args, "-filter_complex", filt, "-map", "[out]", "-ac", "1", str(work / "voice.wav")])
        # one manifest entry covers every beat, so one local beat after a fallback marks the whole track
        p, res = next((m for m in voice_makers if m[0].name == "local"), voice_makers[-1])
        add(id="voice", kind="audio", role="voice", path="voice.wav", duration_sec=media.duration(work / "voice.wav"),
            rights=_rights(data), provider=p.name, model=res.model, provenance=res.meta.get("provenance"), synthetic=True, probe=media.summarize(work / "voice.wav"))

    # --- visuals per beat ---------------------------------------------------
    if "video" in media_kinds or "still" in media_kinds:
        video_budget = int((brief.get("max_video_beats") if brief.get("max_video_beats") is not None else 3))
        for i, beat in enumerate(packet["beats"]):
            bid = beat["id"]
            span = timeline[i]["end_sec"] - timeline[i]["start_sec"]
            prompt = f"{beat.get('visual_cue') or beat['text']}. {_style(data)}"
            still = work / "beats" / f"{bid}.still.png"
            p, res = _gen("image", "image", prompt, still, width=W, height=H,
                          title=beat.get("on_screen") or beat["text"], palette=i,
                          style=(data.get("edit") or {}).get("theme", "studio"))
            add(id=f"{bid}.still", kind="still", role="visual", beat_id=bid, path=f"beats/{bid}.still.png",
                rights=_rights(data), provider=p.name, model=res.model, provenance=res.meta.get("provenance"), prompt=prompt, synthetic=True,
                probe=media.summarize(still))
            if beat.get("visual_kind") == "video" and video_budget > 0 and "video" in media_kinds:
                clip = work / "beats" / f"{bid}.video.mp4"
                try:
                    p, res = _gen("video", "video", prompt, clip, duration=span, aspect=prof.get("aspect", "9:16"), image=still,
                                  est={"duration": span, "image": True})
                    video_budget -= 1
                    add(id=f"{bid}.video", kind="video", role="visual", beat_id=bid, path=f"beats/{bid}.video.mp4",
                        duration_sec=media.duration(clip), rights=_rights(data), provider=p.name, model=res.model, provenance=res.meta.get("provenance"),
                        prompt=prompt, synthetic=True, probe=media.summarize(clip))
                except RuntimeError as exc:  # still + motion covers this beat, and the operator is told
                    print(f"{job.id}: {bid}: no video clip, using the still: {exc}", file=sys.stderr)

    # --- music bed and transition sfx ---------------------------------------
    if "audio" in media_kinds or "video" in media_kinds:
        mood = brief.get("music") or "warm modern instrumental bed, steady pulse, no vocals"
        bed = work / "music.wav"
        p, res = _gen("music", "music", mood, bed, duration=total + 1.0, est={"duration": total + 1.0})
        add(id="music", kind="audio", role="music", path="music.wav", duration_sec=media.duration(bed),
            rights=_rights(data), provider=p.name, model=res.model, provenance=res.meta.get("provenance"), prompt=mood, synthetic=True)
        whoosh = work / "whoosh.wav"
        p, res = _gen("sfx", "sfx", "soft cinematic whoosh transition", whoosh, duration=0.6, est={"duration": 0.6})
        add(id="whoosh", kind="audio", role="sfx", path="whoosh.wav", duration_sec=media.duration(whoosh),
            rights=_rights(data), provider=p.name, model=res.model, provenance=res.meta.get("provenance"), synthetic=True)

    manifest = {
        "schema_version": "0.1",
        "job_id": data["job_id"],
        "assets": assets,
        "timeline": timeline,
        "duration_sec": total,
    }
    if words:
        manifest["words"] = words
    job.write("asset_manifest", manifest)
    return manifest
