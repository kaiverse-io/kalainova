"""EDIT -> RENDER. Compiles edit_manifest.json into render_plan.json (fixed ops), then executes it.

The executor is the only code that turns a plan into ffmpeg arguments. Ops come
from a closed set and every path is resolved inside the job work dir, so a
model-written plan cannot run a shell command or touch files outside the job.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import captions as ass
from . import media
from .jobfs import ContractError, Job

OPS = ("cut", "scale", "concat", "overlay_text", "mix_audio", "loudnorm", "burn_captions", "export")
MOTIONS = ("none", "push_in", "push_out", "pan_left", "pan_right", "drift_up")
PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow")
GRADES = ("natural", "warm", "cool", "teal_orange", "film", "bw", "vivid")
# Grade looks: gentle, filmic, never crushed. Each is a fixed filter string; no value from a plan enters it.
GRADE_FILTERS = {
    "natural": "eq=contrast=1.04:saturation=1.06",
    "warm": "colorbalance=rs=0.04:gs=0.01:bs=-0.05:rm=0.03:bm=-0.03:rh=0.02:bh=-0.03,eq=contrast=1.05:saturation=1.08",
    "cool": "colorbalance=rs=-0.03:bs=0.05:rm=-0.02:bm=0.03,eq=contrast=1.05:saturation=0.98",
    "teal_orange": "colorbalance=rs=-0.06:gs=0.0:bs=0.08:rh=0.07:gh=0.02:bh=-0.06,eq=contrast=1.08:saturation=1.1",
    "film": "curves=m='0/0.035 0.25/0.22 0.5/0.5 0.75/0.78 1/0.96',eq=saturation=0.92,noise=alls=5:allf=t",
    "bw": "hue=s=0,eq=contrast=1.12,curves=m='0/0.02 0.5/0.5 1/0.97'",
    "vivid": "eq=contrast=1.08:saturation=1.22,unsharp=5:5:0.4",
}

# Closed arg spec per op. Every value is coerced to its type before it reaches ffmpeg, so a
# model-written plan cannot smuggle filtergraph text through a number. Text (titles, captions)
# only ever goes into .ass files, never into a filtergraph.
SPEC = {
    "cut": {"source": "path", "kind": ("still", "video"), "in_sec": "num", "out_sec": "num", "fps": "num",
            "out": "path", "pad_to_sec": "num?", "speed": "num?", "audio_out": "path?", "audio_from_source": "bool?"},
    "scale": {"input": "path", "out": "path", "width": "int", "height": "int", "fps": "num",
              "motion": MOTIONS, "duration_sec": "num", "intensity": "num?", "crop_x": "num?", "zoom": "num?",
              "grade": GRADES + (None,), "gamma": "num?"},
    "concat": {"inputs": "paths", "out": "path", "fps": "num", "transition": ("cut", "dissolve", None),
               "xfade_sec": "num?", "durations": "list", "audio_inputs": "list", "audio_out": "path?"},
    "overlay_text": {"input": "path", "out": "path", "width": "int", "height": "int", "overlays": "list",
                     "titles": "list", "duration_sec": "num", "theme": ("studio", "bold", None)},
    "burn_captions": {"input": "path", "out": "path", "width": "int", "height": "int",
                      "style": ("studio", "kinetic", "plain"), "captions": "list"},
    "mix_audio": {"out": "path", "duration_sec": "num", "voice": "path?", "music": "path?",
                  "music_gain_db": "num?", "duck": "bool?", "sfx": "list"},
    "loudnorm": {"input": "path", "out": "path", "target_lufs": "num", "true_peak_dbtp_max": "num"},
    "export": {"video": "path", "audio": "path?", "out": "path", "crf": "int", "preset": PRESETS,
               "thumbnail": "path?", "audio_only": "path?", "fade_out_sec": "num?", "duration_sec": "num?",
               "synthetic": "bool?"},
}


def _coerce(op: str, args: dict, n: int) -> dict:
    import math
    spec = SPEC[op]
    extra = set(args) - set(spec)
    if extra:
        raise ContractError(f"step {n} ({op}): unknown args {sorted(extra)}")
    out = {}
    for key, kind in spec.items():
        optional = isinstance(kind, str) and kind.endswith("?")
        kind = kind.rstrip("?") if isinstance(kind, str) else kind
        if key not in args or args[key] is None:
            if optional or kind in ("list",) or (isinstance(kind, tuple) and None in kind):
                out[key] = [] if kind == "list" else None
                continue
            raise ContractError(f"step {n} ({op}): missing {key}")
        v = args[key]
        try:
            if isinstance(kind, tuple):
                if v not in kind:
                    raise ValueError(f"{v!r} not in {kind}")
            elif kind == "num":
                if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
                    raise ValueError(f"{v!r} is not a number")
                v = float(v)
            elif kind == "int":
                if isinstance(v, bool) or not isinstance(v, int) or not 0 < v <= 8192:
                    raise ValueError(f"{v!r} is not an int in range")
            elif kind == "bool":
                if not isinstance(v, bool):
                    raise ValueError(f"{v!r} is not a bool")
            elif kind == "path":
                if not isinstance(v, str) or not v or v.startswith("-"):
                    raise ValueError(f"{v!r} is not a relative path")
            elif kind == "paths":
                if not isinstance(v, list) or not all(isinstance(x, str) and x and not x.startswith("-") for x in v):
                    raise ValueError("inputs must be a list of relative paths")
            elif kind == "list":
                if not isinstance(v, list):
                    raise ValueError("expected a list")
        except ValueError as exc:
            raise ContractError(f"step {n} ({op}): {key}: {exc}") from exc
        out[key] = v
    for s in out.get("sfx") or []:
        if not (isinstance(s, dict) and isinstance(s.get("path"), str) and not s["path"].startswith("-")
                and all(isinstance(s.get(k, 0), (int, float)) and not isinstance(s.get(k, 0), bool) for k in ("start_sec", "gain_db"))):
            raise ContractError(f"step {n} (mix_audio): malformed sfx entry")
    for p in out.get("audio_inputs") or []:
        if not isinstance(p, str) or not p or p.startswith("-"):
            raise ContractError(f"step {n} (concat): malformed audio input")
    for key in ("crop_x",):
        if out.get(key) is not None and not 0 <= out[key] <= 1:
            raise ContractError(f"step {n}: {key} out of range")
    if out.get("speed") is not None and not 0.25 <= out["speed"] <= 4:
        raise ContractError(f"step {n}: speed out of range")
    if out.get("zoom") is not None and not 1 <= out["zoom"] <= 1.5:
        raise ContractError(f"step {n}: zoom out of range")
    if out.get("gamma") is not None and not 0.5 <= out["gamma"] <= 2:
        raise ContractError(f"step {n}: gamma out of range")
    return out


# ------------------------------------------------------------------ compile
def compile_plan(job: Job) -> dict:
    em = job.read("edit_manifest")
    am = job.read("asset_manifest")
    assets = {a["id"]: a for a in am["assets"]}
    prof = em["profile"]
    W, H, FPS = prof["width"], prof["height"], prof["fps"]
    steps: list[dict] = []
    segs: list[str] = []
    studio = em.get("theme", "studio") == "studio"
    dissolve = em.get("transition") == "dissolve"
    XF = 0.4 if dissolve else 0.0
    n_cuts = len(em.get("cuts", []))
    seg_durs: list[float] = []
    seg_audio: list[str] = []
    orig = bool(em.get("original_audio"))

    for i, cut in enumerate(em.get("cuts", [])):
        src = assets[cut["source"]]
        dur = round(cut["out_sec"] - cut["in_sec"], 3)
        raw = f"seg/{i:02d}.raw.mp4"
        out = f"seg/{i:02d}.mp4"
        seg = round(_span(em, i) + (XF if i < n_cuts - 1 else 0), 3)  # overlap so the dissolve eats no beat time
        seg_durs.append(seg)
        speed = float(cut.get("speed") or 1.0)
        tail = XF if i < n_cuts - 1 else 0
        if src["kind"] == "still":
            out_sec = cut["out_sec"] + tail
        else:  # take the dissolve overlap from the source when it exists; tpad covers the rest
            out_sec = min(cut["out_sec"] + tail * speed, src.get("duration_sec", cut["out_sec"] + tail * speed))
        cut_args = {"source": src["path"], "kind": src["kind"], "in_sec": cut["in_sec"], "out_sec": round(out_sec, 3),
                    "fps": FPS, "out": raw, "pad_to_sec": seg if (cut.get("hold_last_frame") or src["kind"] == "video") else None}
        if speed != 1.0:
            cut_args["speed"] = speed
        if orig:
            cut_args["audio_out"] = f"seg/{i:02d}.wav"
            cut_args["audio_from_source"] = bool(cut.get("keep_audio")) and speed == 1.0
            cut_args["pad_to_sec"] = seg
            seg_audio.append(cut_args["audio_out"])
        steps.append({"op": "cut", "args": cut_args})
        scale_args = {"input": raw, "out": out, "width": W, "height": H, "fps": FPS,
                      "motion": cut.get("motion", "none"), "duration_sec": seg, "intensity": 0.45 if studio else 1.0}
        for key in ("crop_x", "zoom", "grade", "gamma"):
            if cut.get(key) is not None:
                scale_args[key] = cut[key]
        steps.append({"op": "scale", "args": scale_args})
        segs.append(out)

    steps.append({"op": "concat", "args": {"inputs": segs, "out": "picture.mp4", "fps": FPS,
                                           "transition": "dissolve" if dissolve else "cut", "xfade_sec": XF,
                                           "durations": seg_durs, "audio_inputs": seg_audio,
                                           "audio_out": "orig.wav" if seg_audio else None}})

    titles = []
    for i, cut in enumerate(em.get("cuts", [])):
        if cut.get("title"):
            s = cut.get("start_sec", 0)
            span = _span(em, i)
            hold = span - 0.15 if studio else min(2.2, span)  # studio headlines live for the whole beat
            item = {"text": cut["title"], "start_sec": s + (0.15 if studio else 0.1), "end_sec": s + max(hold, 0.6)}
            if assets[cut["source"]].get("provider") == "operator":
                item["scrim"] = True
            titles.append(item)
    steps.append({"op": "overlay_text", "args": {"input": "picture.mp4", "out": "picture.ov.mp4", "width": W, "height": H,
                                                 "overlays": em.get("overlays", []), "titles": titles,
                                                 "theme": "studio" if studio else "bold",
                                                 "duration_sec": em["duration_sec"]}})
    video = "picture.ov.mp4"
    if em.get("captions"):
        steps.append({"op": "burn_captions", "args": {"input": video, "out": "picture.cap.mp4", "width": W, "height": H,
                                                      "style": em.get("caption_style", "kinetic") if em.get("caption_style") != "none" else "plain",
                                                      "captions": em["captions"]}})
        video = "picture.cap.mp4"

    audio = None
    a = em.get("audio") or {}
    if a or orig:
        mix = {"out": "mix.wav", "duration_sec": em["duration_sec"]}
        if a.get("voice_asset_id"):
            mix["voice"] = assets[a["voice_asset_id"]]["path"]
        elif orig:
            mix["voice"] = "orig.wav"  # the footage's own sound leads; music ducks under it
        if a.get("music_asset_id"):
            mix["music"] = assets[a["music_asset_id"]]["path"]
            mix["music_gain_db"] = a.get("music_gain_db", -19)
            mix["duck"] = a.get("duck", True)
        mix["sfx"] = [{"path": assets[x["asset_id"]]["path"], "start_sec": x["start_sec"], "gain_db": x.get("gain_db", -12)}
                      for x in a.get("sfx", [])]
        steps.append({"op": "mix_audio", "args": mix})
        steps.append({"op": "loudnorm", "args": {"input": "mix.wav", "out": "mix.norm.wav",
                                                 "target_lufs": prof.get("target_lufs", -14),
                                                 "true_peak_dbtp_max": prof.get("true_peak_dbtp_max", -1)}})
        audio = "mix.norm.wav"

    steps.append({"op": "export", "args": {"video": video, "audio": audio, "out": "final.mp4", "crf": 18,
                                           "preset": "veryfast", "thumbnail": "thumb.jpg", "audio_only": "final.m4a" if audio else None,
                                           "fade_out_sec": em.get("fade_out_sec"), "duration_sec": em["duration_sec"],
                                           "synthetic": any(x.get("synthetic") for x in am["assets"])}})

    plan = {
        "schema_version": "0.1",
        "job_id": em["job_id"],
        "edit_manifest_sha256": hashlib.sha256(job.path("edit_manifest").read_bytes()).hexdigest(),
        "steps": steps,
    }
    job.write("render_plan", plan)
    return plan


def _span(em: dict, i: int) -> float:
    """Segment length snapped to whole frames from cumulative starts, so picture never drifts from audio."""
    fps = em["profile"]["fps"]
    cuts = em["cuts"]
    start = round(cuts[i].get("start_sec", 0) * fps)
    end = round((cuts[i + 1].get("start_sec") if i + 1 < len(cuts) else em["duration_sec"]) * fps)
    return max(end - start, 1) / fps


# ------------------------------------------------------------------ execute
def _safe(work: Path, rel: str) -> Path:
    p = (work / rel).resolve()
    if work.resolve() not in p.parents and p != work.resolve():
        raise ContractError(f"path escapes job work dir: {rel}")
    return p


def _motion_filter(motion: str, w: int, h: int, fps: float, dur: float, k: float = 1.0) -> str:
    frames = max(int(dur * fps), 1)
    # upscale first so zoompan has pixels to move through without shimmer
    pre = f"scale={w * 2}:{h * 2}:force_original_aspect_ratio=increase,crop={w * 2}:{h * 2}"
    zi, zp, zd = 0.12 * k, 1 + 0.10 * k, 1 + 0.08 * k
    # ease in-out (smoothstep) on the progress term: motion starts and lands softly
    e = "(3*pow(on/{n},2)-2*pow(on/{n},3))"
    z = {
        "push_in": (f"1.0+{zi:.4f}*{e}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        "push_out": (f"{1 + zi:.4f}-{zi:.4f}*{e}", "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        "pan_left": (f"{zp:.4f}", f"(iw-iw/zoom)*(1-{e})", "ih/2-(ih/zoom/2)"),
        "pan_right": (f"{zp:.4f}", f"(iw-iw/zoom)*{e}", "ih/2-(ih/zoom/2)"),
        "drift_up": (f"{zd:.4f}", "iw/2-(iw/zoom/2)", f"(ih-ih/zoom)*(1-{e})"),
    }.get(motion)
    if not z:
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},fps={fps}"
    zz, xx, yy = (s.format(n=frames) for s in z)
    return f"{pre},zoompan=z='{zz}':x='{xx}':y='{yy}':d={frames}:s={w}x{h}:fps={fps},setsar=1"


def stamp(job: Job, video: Path) -> None:
    """Tie the rendered file to the asset record it was made from."""
    if job.has("asset_manifest"):
        job.write_stamp({"video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                         "asset_manifest_sha256": hashlib.sha256(job.path("asset_manifest").read_bytes()).hexdigest()})


def execute(job: Job, plan: dict | None = None) -> Path:
    plan = plan or job.read("render_plan")
    if plan.get("edit_manifest_sha256") and job.has("edit_manifest"):
        current = hashlib.sha256(job.path("edit_manifest").read_bytes()).hexdigest()
        if current != plan["edit_manifest_sha256"]:
            raise ContractError(f"{job.id}: render_plan is stale; edit_manifest changed since compile")
    work = job.work
    (work / "seg").mkdir(exist_ok=True)
    for n, step in enumerate(plan["steps"]):
        op, a = step["op"], step.get("args", {})
        if op not in OPS:
            raise ContractError(f"step {n}: op {op!r} not allowed")
        globals()[f"_op_{op}"](work, _coerce(op, a if isinstance(a, dict) else {}, n))
    out = work / "final.mp4"
    (work / "render.done.json").write_text(json.dumps({"plan_sha256": hashlib.sha256(
        json.dumps(plan, sort_keys=True).encode()).hexdigest()}) + "\n")
    if out.exists():
        stamp(job, out)
    return out


def _op_cut(work: Path, a: dict) -> None:
    src, out = _safe(work, a["source"]), _safe(work, a["out"])
    dur = a["out_sec"] - a["in_sec"]
    if a["kind"] == "still":
        media.run(["-loop", "1", "-framerate", str(a["fps"]), "-t", f"{dur:.3f}", "-i", str(src),
                   "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",  # camera photos often have odd dimensions
                   "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p", str(out)])
        return
    speed = a.get("speed") or 1.0
    vf = [f"setpts=PTS/{speed:.4f}" if speed != 1.0 else "setpts=PTS-STARTPTS", f"fps={a['fps']:g}",
          "scale=trunc(iw/2)*2:trunc(ih/2)*2"]
    shown = dur / speed
    if a.get("pad_to_sec") and a["pad_to_sec"] > shown:
        vf.append(f"tpad=stop_mode=clone:stop_duration={a['pad_to_sec'] - shown:.3f}")
    media.run(["-ss", f"{a['in_sec']:.3f}", "-t", f"{dur:.3f}", "-i", str(src), "-an", "-vf", ",".join(vf),
               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p", str(out)])
    if a.get("audio_out"):
        total = a.get("pad_to_sec") or shown
        aout = _safe(work, a["audio_out"])
        if a.get("audio_from_source"):
            fo = max(dur - 0.03, 0)
            media.run(["-ss", f"{a['in_sec']:.3f}", "-t", f"{dur:.3f}", "-i", str(src), "-vn",
                       "-af", f"afade=t=in:d=0.02,afade=t=out:st={fo:.3f}:d=0.03,aresample=48000,apad=whole_dur={total:.3f},"
                              f"atrim=0:{total:.3f}", "-ac", "2", "-ar", "48000", str(aout)])
        else:
            media.run(["-f", "lavfi", "-i", f"anullsrc=r=48000:cl=stereo", "-t", f"{total:.3f}", str(aout)])


def _op_scale(work: Path, a: dict) -> None:
    src, out = _safe(work, a["input"]), _safe(work, a["out"])
    W, H = a["width"], a["height"]
    if a.get("motion", "none") == "none":
        z = a.get("zoom") or 1.0
        cx = 0.5 if a.get("crop_x") is None else a["crop_x"]
        # fill the frame, punch in if asked, then crop around the subject (clamped inside the frame)
        vf = (f"scale={int(W * z)}:{int(H * z)}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={W}:{H}:x='(iw-{W})*{min(max(cx, 0.0), 1.0):.4f}':y='(ih-{H})/2',fps={a['fps']:g},setsar=1")
    else:
        vf = _motion_filter(a["motion"], W, H, a["fps"], a["duration_sec"], a.get("intensity") or 1.0)
    looks = []
    if a.get("gamma") and abs(a["gamma"] - 1) > 0.02:
        looks.append(f"eq=gamma={a['gamma']:.3f}")
    if a.get("grade"):
        looks.append(GRADE_FILTERS[a["grade"]])
    if looks:
        vf += "," + ",".join(looks)
    media.run(["-i", str(src), "-vf", vf + f",trim=duration={a['duration_sec']:.3f},format=yuv420p",
               "-an", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", str(out)])


def _op_concat(work: Path, a: dict) -> None:
    ins = [_safe(work, p) for p in a["inputs"]]
    args: list[str] = []
    for p in ins:
        args += ["-i", str(p)]
    filt = "".join(f"[{i}:v]settb=AVTB,fps={a['fps']:g},format=yuv420p[v{i}];" for i in range(len(ins)))
    durs = [float(d) for d in a.get("durations") or []]
    xf = a.get("xfade_sec") or 0.0
    if a.get("transition") == "dissolve" and xf > 0 and len(ins) > 1 and len(durs) == len(ins):
        prev, total = "v0", durs[0]
        for i in range(1, len(ins)):
            label = "out" if i == len(ins) - 1 else f"x{i}"
            filt += f"[{prev}][v{i}]xfade=transition=fade:duration={xf:.3f}:offset={total - xf:.3f}[{label}];"
            prev, total = label, total + durs[i] - xf
        filt = filt.rstrip(";")
    else:
        filt += "".join(f"[v{i}]" for i in range(len(ins))) + f"concat=n={len(ins)}:v=1:a=0[out]"
    media.run([*args, "-filter_complex", filt, "-map", "[out]", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14",
               str(_safe(work, a["out"]))])
    auds = [_safe(work, p) for p in a.get("audio_inputs") or []]
    if auds and a.get("audio_out"):
        aargs: list[str] = []
        for p in auds:
            aargs += ["-i", str(p)]
        if a.get("transition") == "dissolve" and xf > 0 and len(auds) > 1:
            af, prev = "", "0:a"
            for i in range(1, len(auds)):
                label = "aout" if i == len(auds) - 1 else f"ax{i}"
                af += f"[{prev}][{i}:a]acrossfade=d={xf:.3f}:c1=tri:c2=tri[{label}];"
                prev = label
            af = af.rstrip(";")
        else:
            af = "".join(f"[{i}:a]" for i in range(len(auds))) + f"concat=n={len(auds)}:v=0:a=1[aout]"
        media.run([*aargs, "-filter_complex", af, "-map", "[aout]", "-ar", "48000", "-ac", "2", str(_safe(work, a["audio_out"]))])


def _op_overlay_text(work: Path, a: dict) -> None:
    src, out = _safe(work, a["input"]), _safe(work, a["out"])
    W, H, D = a["width"], a["height"], a["duration_sec"]
    ass_path = work / "overlay.ass"
    studio = a.get("theme") == "studio"
    ass_path.write_text(ass.studio_titles(a.get("titles", []), W, H) if studio
                        else ass.overlay_events(a.get("overlays", []), a.get("titles", []), W, H))
    bar = any(o["kind"] == "progress_bar" for o in a.get("overlays", []))
    fonts = ass.STUDIO_FONTS if studio else "/usr/share/fonts/truetype/google-fonts"
    if bar:
        bh = max(8, H // 240)
        filt = (f"[0:v]subtitles=overlay.ass:fontsdir={fonts}[t];"
                f"color=c=0xFFD700:s={W}x{bh}:r=30:d={D:.3f}[bar];"
                f"[t][bar]overlay=x='-W+W*t/{D:.3f}':y=H-h-{H // 9}:shortest=1[out]")
        media.run(["-i", src.name, "-filter_complex", filt, "-map", "[out]", "-c:v", "libx264", "-preset", "ultrafast",
                   "-crf", "14", out.name], cwd=work)
    else:
        media.run(["-i", src.name, "-vf", f"subtitles=overlay.ass:fontsdir={fonts}", "-c:v", "libx264",
                   "-preset", "ultrafast", "-crf", "14", out.name], cwd=work)


def _op_burn_captions(work: Path, a: dict) -> None:
    src, out = _safe(work, a["input"]), _safe(work, a["out"])
    studio = a.get("style") == "studio"
    (work / "captions.ass").write_text(ass.studio_captions(a["captions"], a["width"], a["height"]) if studio
                                       else ass.kinetic(a["captions"], a["width"], a["height"]))
    fonts = ass.STUDIO_FONTS if studio else "/usr/share/fonts/truetype/google-fonts"
    media.run(["-i", src.name, "-vf", f"subtitles=captions.ass:fontsdir={fonts}",
               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "14", out.name], cwd=work)
    (work / "captions.srt").write_text(_srt(a["captions"]))


def _srt(caps: list[dict]) -> str:
    def t(s: float) -> str:
        ms = int(round(s * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{i}\n{t(c['start_sec'])} --> {t(c['end_sec'])}\n{c['text']}\n" for i, c in enumerate(caps, 1))


def _op_mix_audio(work: Path, a: dict) -> None:
    D = a["duration_sec"]
    ins, chains, labels = [], [], []
    idx = 0
    voice_label = None
    if a.get("voice"):
        ins += ["-i", str(_safe(work, a["voice"]))]
        chains.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={D:.3f}[voice]")
        voice_label, idx = "voice", idx + 1
    if a.get("music"):
        ins += ["-i", str(_safe(work, a["music"]))]
        g = a.get("music_gain_db", -19)
        chains.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,aloop=loop=-1:size=2147483647,"
                      f"volume={g:.2f}dB,atrim=0:{D:.3f}[mus]")
        idx += 1
        if voice_label and a.get("duck"):
            chains.append("[voice]asplit=2[voice][vkey]")
            chains.append("[mus][vkey]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=350:makeup=1[musd]")
            labels.append("[musd]")
        else:
            labels.append("[mus]")
    for k, s in enumerate(a.get("sfx", [])):
        ins += ["-i", str(_safe(work, s["path"]))]
        ms = max(int(float(s["start_sec"]) * 1000), 0)
        chains.append(f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,volume={float(s.get('gain_db', -12)):.2f}dB,"
                      f"adelay={ms}|{ms}[sfx{k}]")
        labels.append(f"[sfx{k}]")
        idx += 1
    if voice_label:
        labels.insert(0, "[voice]")
    if not labels:
        return
    filt = ";".join(chains) + ";" + "".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=first,atrim=0:{D:.3f}[out]"
    media.run([*ins, "-filter_complex", filt, "-map", "[out]", "-ar", "48000", str(_safe(work, a["out"]))])


def _op_loudnorm(work: Path, a: dict) -> None:
    media.loudnorm_two_pass(_safe(work, a["input"]), _safe(work, a["out"]), a["target_lufs"], a["true_peak_dbtp_max"])


def _op_export(work: Path, a: dict) -> None:
    out = _safe(work, a["out"])
    args = ["-i", str(_safe(work, a["video"]))]
    f, D = a.get("fade_out_sec") or 0, a.get("duration_sec") or 0
    if a.get("audio"):
        args += ["-i", str(_safe(work, a["audio"])), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
        if f and D > f:
            args += ["-af", f"afade=t=out:st={D - f:.3f}:d={f:.3f}"]
    if f and D > f:  # output options go after every input
        args += ["-vf", f"fade=t=out:st={D - f:.3f}:d={f:.3f}"]
    note = "Made with Kalainova; contains AI-generated media" if a.get("synthetic", True) else "Edited with Kalainova"
    args += ["-c:v", "libx264", "-preset", a.get("preset", "veryfast"), "-crf", str(a.get("crf", 20)), "-profile:v", "high",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-metadata", f"comment={note}", str(out)]
    media.run(args)
    if a.get("thumbnail"):
        media.frame_at(out, 0.9, _safe(work, a["thumbnail"]))
    if a.get("audio_only") and a.get("audio"):
        media.run(["-i", str(_safe(work, a["audio"])), "-c:a", "aac", "-b:a", "192k", str(_safe(work, a["audio_only"]))])
