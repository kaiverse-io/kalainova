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

# Closed arg spec per op. Every value is coerced to its type before it reaches ffmpeg, so a
# model-written plan cannot smuggle filtergraph text through a number. Text (titles, captions)
# only ever goes into .ass files, never into a filtergraph.
SPEC = {
    "cut": {"source": "path", "kind": ("still", "video"), "in_sec": "num", "out_sec": "num", "fps": "num",
            "out": "path", "pad_to_sec": "num?"},
    "scale": {"input": "path", "out": "path", "width": "int", "height": "int", "fps": "num",
              "motion": MOTIONS, "duration_sec": "num", "intensity": "num?"},
    "concat": {"inputs": "paths", "out": "path", "fps": "num", "transition": ("cut", "dissolve", None),
               "xfade_sec": "num?", "durations": "list"},
    "overlay_text": {"input": "path", "out": "path", "width": "int", "height": "int", "overlays": "list",
                     "titles": "list", "duration_sec": "num", "theme": ("studio", "bold", None)},
    "burn_captions": {"input": "path", "out": "path", "width": "int", "height": "int",
                      "style": ("studio", "kinetic", "plain"), "captions": "list"},
    "mix_audio": {"out": "path", "duration_sec": "num", "voice": "path?", "music": "path?",
                  "music_gain_db": "num?", "duck": "bool?", "sfx": "list"},
    "loudnorm": {"input": "path", "out": "path", "target_lufs": "num", "true_peak_dbtp_max": "num"},
    "export": {"video": "path", "audio": "path?", "out": "path", "crf": "int", "preset": PRESETS,
               "thumbnail": "path?", "audio_only": "path?"},
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
            if optional or kind in ("list",):
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
        if not (isinstance(s, dict) and isinstance(s.get("path"), str)
                and all(isinstance(s.get(k, 0), (int, float)) and not isinstance(s.get(k, 0), bool) for k in ("start_sec", "gain_db"))):
            raise ContractError(f"step {n} (mix_audio): malformed sfx entry")
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

    for i, cut in enumerate(em.get("cuts", [])):
        src = assets[cut["source"]]
        dur = round(cut["out_sec"] - cut["in_sec"], 3)
        raw = f"seg/{i:02d}.raw.mp4"
        out = f"seg/{i:02d}.mp4"
        seg = round(_span(em, i) + (XF if i < n_cuts - 1 else 0), 3)  # overlap so the dissolve eats no beat time
        seg_durs.append(seg)
        out_sec = cut["out_sec"] + (XF if i < n_cuts - 1 and src["kind"] == "still" else 0)
        steps.append({"op": "cut", "args": {"source": src["path"], "kind": src["kind"], "in_sec": cut["in_sec"],
                                            "out_sec": out_sec, "fps": FPS, "out": raw,
                                            "pad_to_sec": seg if (cut.get("hold_last_frame") or src["kind"] == "video") else None}})
        steps.append({"op": "scale", "args": {"input": raw, "out": out, "width": W, "height": H, "fps": FPS,
                                              "motion": cut.get("motion", "none"), "duration_sec": seg,
                                              "intensity": 0.45 if studio else 1.0}})
        segs.append(out)

    steps.append({"op": "concat", "args": {"inputs": segs, "out": "picture.mp4", "fps": FPS,
                                           "transition": "dissolve" if dissolve else "cut", "xfade_sec": XF,
                                           "durations": seg_durs}})

    titles = []
    for i, cut in enumerate(em.get("cuts", [])):
        if cut.get("title"):
            s = cut.get("start_sec", 0)
            span = _span(em, i)
            hold = span - 0.15 if studio else min(2.2, span)  # studio headlines live for the whole beat
            titles.append({"text": cut["title"], "start_sec": s + (0.15 if studio else 0.1), "end_sec": s + max(hold, 0.6)})
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
    if a:
        mix = {"out": "mix.wav", "duration_sec": em["duration_sec"]}
        if a.get("voice_asset_id"):
            mix["voice"] = assets[a["voice_asset_id"]]["path"]
        if a.get("music_asset_id"):
            mix["music"] = assets[a["music_asset_id"]]["path"]
            mix["music_gain_db"] = a.get("music_gain_db", -19)
            mix["duck"] = a.get("duck", True)
        mix["sfx"] = [{"path": assets[s["asset_id"]]["path"], "start_sec": s["start_sec"], "gain_db": s.get("gain_db", -12)}
                      for s in a.get("sfx", [])]
        steps.append({"op": "mix_audio", "args": mix})
        steps.append({"op": "loudnorm", "args": {"input": "mix.wav", "out": "mix.norm.wav",
                                                 "target_lufs": prof.get("target_lufs", -14),
                                                 "true_peak_dbtp_max": prof.get("true_peak_dbtp_max", -1)}})
        audio = "mix.norm.wav"

    steps.append({"op": "export", "args": {"video": video, "audio": audio, "out": "final.mp4", "crf": 20,
                                           "preset": "veryfast", "thumbnail": "thumb.jpg", "audio_only": "final.m4a" if audio else None}})

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
    return out


def _op_cut(work: Path, a: dict) -> None:
    src, out = _safe(work, a["source"]), _safe(work, a["out"])
    dur = a["out_sec"] - a["in_sec"]
    if a["kind"] == "still":
        media.run(["-loop", "1", "-framerate", str(a["fps"]), "-t", f"{dur:.3f}", "-i", str(src),
                   "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p", str(out)])
        return
    vf = [f"fps={a['fps']}"]
    if a.get("pad_to_sec") and a["pad_to_sec"] > dur:
        vf.append(f"tpad=stop_mode=clone:stop_duration={a['pad_to_sec'] - dur:.3f}")
    media.run(["-ss", f"{a['in_sec']:.3f}", "-t", f"{dur:.3f}", "-i", str(src), "-an", "-vf", ",".join(vf),
               "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p", str(out)])


def _op_scale(work: Path, a: dict) -> None:
    src, out = _safe(work, a["input"]), _safe(work, a["out"])
    vf = _motion_filter(a.get("motion", "none"), a["width"], a["height"], a["fps"], a["duration_sec"], a.get("intensity") or 1.0)
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
    if a.get("audio"):
        args += ["-i", str(_safe(work, a["audio"])), "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "192k", "-shortest"]
    args += ["-c:v", "libx264", "-preset", a.get("preset", "veryfast"), "-crf", str(a.get("crf", 20)), "-profile:v", "high",
             "-pix_fmt", "yuv420p", "-movflags", "+faststart",
             "-metadata", "comment=AI-generated with Kalainova; synthetic media", str(out)]
    media.run(args)
    if a.get("thumbnail"):
        media.frame_at(out, 0.9, _safe(work, a["thumbnail"]))
    if a.get("audio_only") and a.get("audio"):
        media.run(["-i", str(_safe(work, a["audio"])), "-c:a", "aac", "-b:a", "192k", str(_safe(work, a["audio_only"]))])
