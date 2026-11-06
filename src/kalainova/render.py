"""EDIT -> RENDER. Compiles edit_manifest.json into render_plan.json (fixed ops), then executes it.

The executor is the only code that turns a plan into ffmpeg arguments. Ops come
from a closed set and every path is resolved inside the job work dir, so a
model-written plan cannot run a shell command or touch files outside the job.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import numpy as np

from . import captions as ass
from . import look, media, motion
from .jobfs import ContractError, Job

OPS = (
    "still",
    "cut",
    "scale",
    "concat",
    "overlay_text",
    "mix_audio",
    "loudnorm",
    "burn_captions",
    "caption_files",
    "export",
)
MOTIONS = ("none", "push_in", "push_out", "pan_left", "pan_right", "drift_up")
PRESETS = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow")
GRADES = tuple(look.LOOKS)

# The sound of a finished voice: rumble out, sibilance tamed, mud eased, presence and air lifted, level
# held. Fixed strings, so no value from a plan enters them.
VOICE_CHAIN = (
    "highpass=f=75,deesser=i=0.4:m=0.5:f=0.5,equalizer=f=220:t=q:w=1.2:g=-1.5,"
    "equalizer=f=3000:t=q:w=1.5:g=1.5,equalizer=f=9500:t=h:w=2000:g=1,"
    "acompressor=threshold=-22dB:ratio=2.5:attack=6:release=120:makeup=3dB,"
    "alimiter=limit=0.9:attack=2:release=50:level=disabled"
)
MUSIC_POCKET = "equalizer=f=2800:t=q:w=1.4:g=-3"  # a space in the music for the words to sit in
DUCK = "sidechaincompress=threshold=0.02:ratio=6:attack=25:release=450:makeup=1"
# A real room is never silent. A faint bed keeps speech gaps from dropping to digital zero.
ROOM_TONE = "anoisesrc=d={duration:.3f}:c=pink:r=48000:a=0.0007:seed=7,lowpass=f=7000,aformat=channel_layouts=stereo[room]"
MUSIC_FADE_SEC = 2.5
SAMPLE_WIDTH, SAMPLE_FPS = 270, 2.0
TITLE_HOLD_SEC = 3.0

# Closed arg spec per op. Every value is coerced to its type before it reaches ffmpeg, so a
# model-written plan cannot smuggle filtergraph text through a number. Text (titles, captions)
# only ever goes into .ass files, never into a filtergraph.
SPEC = {
    "still": {
        "source": "path",
        "out": "path",
        "width": "int",
        "height": "int",
        "fps": "num",
        "duration_sec": "num",
        "motion": MOTIONS,
        "crop_x": "num?",
        "grade": GRADES + (None,),
        "gamma": "num?",
    },
    "cut": {
        "source": "path",
        "kind": ("video",),
        "in_sec": "num",
        "out_sec": "num",
        "fps": "num",
        "out": "path",
        "pad_to_sec": "num?",
        "speed": "num?",
        "audio_out": "path?",
        "audio_from_source": "bool?",
    },
    "scale": {
        "input": "path",
        "out": "path",
        "width": "int",
        "height": "int",
        "fps": "num",
        "duration_sec": "num",
        "crop_x": "num?",
        "zoom": "num?",
        "grade": GRADES + (None,),
        "gamma": "num?",
    },
    "concat": {
        "inputs": "paths",
        "out": "path",
        "fps": "num",
        "transition": ("cut", "dissolve", None),
        "xfade_sec": "num?",
        "durations": "list",
        "audio_inputs": "list",
        "audio_out": "path?",
    },
    "overlay_text": {
        "input": "path",
        "out": "path",
        "width": "int",
        "height": "int",
        "overlays": "list",
        "titles": "list",
        "duration_sec": "num",
        "theme": ("studio", "bold", None),
    },
    "burn_captions": {
        "input": "path",
        "out": "path",
        "width": "int",
        "height": "int",
        "style": ("studio", "kinetic", "plain"),
        "captions": "list",
    },
    "caption_files": {"cues": "list", "fps": "num"},
    "mix_audio": {
        "out": "path",
        "duration_sec": "num",
        "voice": "path?",
        "voice_chain": "bool?",
        "music": "path?",
        "music_gain_db": "num?",
        "duck": "bool?",
        "sfx": "list",
    },
    "loudnorm": {"input": "path", "out": "path", "target_lufs": "num", "true_peak_dbtp_max": "num"},
    "export": {
        "video": "path",
        "audio": "path?",
        "out": "path",
        "crf": "int",
        "preset": PRESETS,
        "thumbnail": "path?",
        "audio_only": "path?",
        "fade_in_sec": "num?",
        "fade_out_sec": "num?",
        "duration_sec": "num?",
        "fps": "num?",
        "master": "path?",
        "synthetic": "bool?",
    },
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
                if not isinstance(v, list) or not all(
                    isinstance(x, str) and x and not x.startswith("-") for x in v
                ):
                    raise ValueError("inputs must be a list of relative paths")
            elif kind == "list":
                if not isinstance(v, list):
                    raise ValueError("expected a list")
        except ValueError as exc:
            raise ContractError(f"step {n} ({op}): {key}: {exc}") from exc
        out[key] = v
    for s in out.get("sfx") or []:
        if not (
            isinstance(s, dict)
            and isinstance(s.get("path"), str)
            and not s["path"].startswith("-")
            and all(
                isinstance(s.get(k, 0), (int, float)) and not isinstance(s.get(k, 0), bool)
                for k in ("start_sec", "gain_db")
            )
        ):
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
        seg = round(
            _span(em, i) + (XF if i < n_cuts - 1 else 0), 3
        )  # overlap so the dissolve eats no beat time
        seg_durs.append(seg)
        speed = float(cut.get("speed") or 1.0)
        tail = XF if i < n_cuts - 1 else 0
        if src["kind"] == "still":
            out_sec = cut["out_sec"] + tail
        else:  # take the dissolve overlap from the source when it exists; tpad covers the rest
            out_sec = min(
                cut["out_sec"] + tail * speed,
                src.get("duration_sec", cut["out_sec"] + tail * speed),
            )
        if src["kind"] == "still":
            still_args = {
                "source": src["path"],
                "out": out,
                "width": W,
                "height": H,
                "fps": FPS,
                "duration_sec": seg,
                "motion": cut.get("motion", "none"),
            }
            for key in ("crop_x", "grade", "gamma"):
                if cut.get(key) is not None:
                    still_args[key] = cut[key]
            steps.append({"op": "still", "args": still_args})
            segs.append(out)
            continue
        cut_args = {
            "source": src["path"],
            "kind": src["kind"],
            "in_sec": cut["in_sec"],
            "out_sec": round(out_sec, 3),
            "fps": FPS,
            "out": raw,
            "pad_to_sec": seg if (cut.get("hold_last_frame") or src["kind"] == "video") else None,
        }
        if speed != 1.0:
            cut_args["speed"] = speed
        if orig:
            cut_args["audio_out"] = f"seg/{i:02d}.wav"
            cut_args["audio_from_source"] = bool(cut.get("keep_audio")) and speed == 1.0
            cut_args["pad_to_sec"] = seg
            seg_audio.append(cut_args["audio_out"])
        steps.append({"op": "cut", "args": cut_args})
        scale_args = {
            "input": raw,
            "out": out,
            "width": W,
            "height": H,
            "fps": FPS,
            "duration_sec": seg,
        }
        for key in ("crop_x", "zoom", "grade", "gamma"):
            if cut.get(key) is not None:
                scale_args[key] = cut[key]
        steps.append({"op": "scale", "args": scale_args})
        segs.append(out)

    steps.append(
        {
            "op": "concat",
            "args": {
                "inputs": segs,
                "out": "picture.mp4",
                "fps": FPS,
                "transition": "dissolve" if dissolve else "cut",
                "xfade_sec": XF,
                "durations": seg_durs,
                "audio_inputs": seg_audio,
                "audio_out": "orig.wav" if seg_audio else None,
            },
        }
    )

    titles = []
    for i, cut in enumerate(em.get("cuts", [])):
        if cut.get("title"):
            s = cut.get("start_sec", 0)
            span = _span(em, i)
            hold = min(TITLE_HOLD_SEC, span) - 0.15 if studio else min(2.2, span)
            item = {
                "text": cut["title"],
                "start_sec": s + (0.15 if studio else 0.1),
                "end_sec": s + max(hold, 0.6),
            }
            titles.append(item)
    steps.append(
        {
            "op": "overlay_text",
            "args": {
                "input": "picture.mp4",
                "out": "picture.ov.mp4",
                "width": W,
                "height": H,
                "overlays": em.get("overlays", []),
                "titles": titles,
                "theme": "studio" if studio else "bold",
                "duration_sec": em["duration_sec"],
            },
        }
    )
    video = "picture.ov.mp4"
    cues = em.get("closed_captions") or em.get("captions")
    if cues:
        steps.append({"op": "caption_files", "args": {"cues": cues, "fps": FPS}})
    if em.get("captions"):
        steps.append(
            {
                "op": "burn_captions",
                "args": {
                    "input": video,
                    "out": "picture.cap.mp4",
                    "width": W,
                    "height": H,
                    "style": em.get("caption_style", "kinetic")
                    if em.get("caption_style") != "none"
                    else "plain",
                    "captions": em["captions"],
                },
            }
        )
        video = "picture.cap.mp4"

    audio = None
    a = em.get("audio") or {}
    if a or orig:
        mix = {"out": "mix.wav", "duration_sec": em["duration_sec"]}
        if a.get("voice_asset_id"):
            mix["voice"] = assets[a["voice_asset_id"]]["path"]
            mix["voice_chain"] = True
        elif orig:
            mix["voice"] = "orig.wav"  # the footage's own sound leads; music ducks under it
        if a.get("music_asset_id"):
            mix["music"] = assets[a["music_asset_id"]]["path"]
            mix["music_gain_db"] = a.get("music_gain_db", -19)
            mix["duck"] = a.get("duck", True)
        mix["sfx"] = [
            {
                "path": assets[x["asset_id"]]["path"],
                "start_sec": x["start_sec"],
                "gain_db": x.get("gain_db", -12),
            }
            for x in a.get("sfx", [])
        ]
        steps.append({"op": "mix_audio", "args": mix})
        steps.append(
            {
                "op": "loudnorm",
                "args": {
                    "input": "mix.wav",
                    "out": "mix.norm.wav",
                    "target_lufs": prof.get("target_lufs", -14),
                    "true_peak_dbtp_max": prof.get("true_peak_dbtp_max", -1),
                },
            }
        )
        audio = "mix.norm.wav"

    steps.append(
        {
            "op": "export",
            "args": {
                "video": video,
                "audio": audio,
                "out": "final.mp4",
                "crf": 16,
                "preset": "slow",
                "thumbnail": "thumb.jpg",
                "audio_only": "final.m4a" if audio else None,
                "fade_in_sec": em.get("fade_in_sec"),
                "fade_out_sec": em.get("fade_out_sec"),
                "duration_sec": em["duration_sec"],
                "fps": FPS,
                "master": "final.master.mov" if prof.get("delivery") == "mezzanine" else None,
                "synthetic": any(x.get("synthetic") for x in am["assets"]),
            },
        }
    )

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


def stamp(job: Job, video: Path) -> None:
    """Tie the rendered file to the asset record it was made from."""
    if job.has("asset_manifest"):
        job.write_stamp(
            {
                "artifact_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                "asset_manifest_sha256": hashlib.sha256(
                    job.path("asset_manifest").read_bytes()
                ).hexdigest(),
            }
        )


def execute(job: Job, plan: dict | None = None) -> Path:
    plan = plan or job.read("render_plan")
    if plan.get("edit_manifest_sha256") and job.has("edit_manifest"):
        current = hashlib.sha256(job.path("edit_manifest").read_bytes()).hexdigest()
        if current != plan["edit_manifest_sha256"]:
            raise ContractError(
                f"{job.id}: render_plan is stale; edit_manifest changed since compile"
            )
    work = job.work
    (work / "seg").mkdir(exist_ok=True)
    for n, step in enumerate(plan["steps"]):
        op, a = step["op"], step.get("args", {})
        if op not in OPS:
            raise ContractError(f"step {n}: op {op!r} not allowed")
        globals()[f"_op_{op}"](work, _coerce(op, a if isinstance(a, dict) else {}, n))
    out = work / "final.mp4"
    (work / "render.done.json").write_text(
        json.dumps(
            {"plan_sha256": hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()}
        )
        + "\n"
    )
    if out.exists():
        stamp(job, out)
    return out


def refuse_fallback_fonts(log: str) -> None:
    """libass names a system path when it could not find the font asked for. That is not our type."""
    for wanted, used in re.findall(r"fontselect: \(([^,]+),[^)]*\) -> ([^,]+),", log):
        if "/" in used:
            raise ContractError(
                f"font {wanted!r} is not in {ass.FONTS}; libass fell back to {used}"
            )


def _look_filter(work: Path, a: dict) -> list[str]:
    """The grade as one LUT, for stills and footage alike. Its name holds no text from a plan."""
    gamma = a.get("gamma") or 1.0
    if not a.get("grade") and abs(gamma - 1) <= 0.02:
        return []
    name = a.get("grade") or "natural"
    (work / "looks").mkdir(exist_ok=True)
    cube = work / "looks" / f"{name}-{gamma:.3f}.cube"
    if not cube.exists():
        cube.write_text(look.cube_text(name, gamma))
    return [f"lut3d=file=looks/{cube.name}"]


def _to_master(look_chain: list[str]) -> str:
    return ",".join([*look_chain, media.TO_BT709, f"format={media.MASTER_PIX_FMT}"])


def _op_still(work: Path, a: dict) -> None:
    frames = motion.frames_16bit(
        _safe(work, a["source"]),
        a["motion"],
        width=a["width"],
        height=a["height"],
        fps=a["fps"],
        duration=a["duration_sec"],
        crop_x=0.5 if a.get("crop_x") is None else a["crop_x"],
    )
    media.encode_rgb48(
        frames,
        size=(a["width"], a["height"]),
        fps=a["fps"],
        vf=_to_master(_look_filter(work, a)),
        out=_safe(work, a["out"]),
        cwd=work,
    )


def _op_cut(work: Path, a: dict) -> None:
    src, out = _safe(work, a["source"]), _safe(work, a["out"])
    dur = a["out_sec"] - a["in_sec"]
    speed = a.get("speed") or 1.0
    vf = [
        *media.from_source_color(src),
        f"setpts=PTS/{speed:.4f}" if speed != 1.0 else "setpts=PTS-STARTPTS",
        f"fps={a['fps']:g}",
        "scale=trunc(iw/2)*2:trunc(ih/2)*2",
    ]
    shown = dur / speed
    if a.get("pad_to_sec") and a["pad_to_sec"] > shown:
        vf.append(f"tpad=stop_mode=clone:stop_duration={a['pad_to_sec'] - shown:.3f}")
    media.run(
        [
            "-ss",
            f"{a['in_sec']:.3f}",
            "-t",
            f"{dur:.3f}",
            "-i",
            str(src),
            "-an",
            "-vf",
            ",".join([*vf, media.TO_BT709, f"format={media.MASTER_PIX_FMT}"]),
            *media.MASTER_ARGS,
            str(out),
        ]
    )
    if a.get("audio_out"):
        total = a.get("pad_to_sec") or shown
        aout = _safe(work, a["audio_out"])
        if a.get("audio_from_source"):
            fo = max(dur - 0.03, 0)
            media.run(
                [
                    "-ss",
                    f"{a['in_sec']:.3f}",
                    "-t",
                    f"{dur:.3f}",
                    "-i",
                    str(src),
                    "-vn",
                    "-af",
                    f"afade=t=in:d=0.02,afade=t=out:st={fo:.3f}:d=0.03,aresample=48000,apad=whole_dur={total:.3f},"
                    f"atrim=0:{total:.3f}",
                    "-ac",
                    "2",
                    "-ar",
                    "48000",
                    str(aout),
                ]
            )
        else:
            media.run(
                ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", f"{total:.3f}", str(aout)]
            )


def _op_scale(work: Path, a: dict) -> None:
    src, out = _safe(work, a["input"]), _safe(work, a["out"])
    W, H = a["width"], a["height"]
    z = a.get("zoom") or 1.0
    cx = 0.5 if a.get("crop_x") is None else a["crop_x"]
    # fill the frame, punch in if asked, then crop around the subject (clamped inside the frame)
    fit = (
        f"scale={int(W * z)}:{int(H * z)}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={W}:{H}:x='(iw-{W})*{min(max(cx, 0.0), 1.0):.4f}':y='(ih-{H})/2',fps={a['fps']:g},setsar=1"
    )
    trim = f"trim=duration={a['duration_sec']:.3f}"
    media.run(
        [
            "-i",
            str(src),
            "-vf",
            f"{fit},{trim},{_to_master(_look_filter(work, a))}",
            "-an",
            *media.MASTER_ARGS,
            str(out),
        ],
        cwd=work,
    )


def _op_concat(work: Path, a: dict) -> None:
    ins = [_safe(work, p) for p in a["inputs"]]
    args: list[str] = []
    for p in ins:
        args += ["-i", str(p)]
    filt = "".join(
        f"[{i}:v]settb=AVTB,fps={a['fps']:g},format={media.MASTER_PIX_FMT}[v{i}];"
        for i in range(len(ins))
    )
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
    media.run(
        [
            *args,
            "-filter_complex",
            filt,
            "-map",
            "[out]",
            *media.MASTER_ARGS,
            str(_safe(work, a["out"])),
        ]
    )
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
            af = (
                "".join(f"[{i}:a]" for i in range(len(auds)))
                + f"concat=n={len(auds)}:v=0:a=1[aout]"
            )
        media.run(
            [
                *aargs,
                "-filter_complex",
                af,
                "-map",
                "[aout]",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(_safe(work, a["audio_out"])),
            ]
        )


def _op_overlay_text(work: Path, a: dict) -> None:
    src, out = _safe(work, a["input"]), _safe(work, a["out"])
    W, H, D = a["width"], a["height"], a["duration_sec"]
    ass_path = work / "overlay.ass"
    studio = a.get("theme") == "studio"
    ass_path.write_text(
        ass.studio_titles(_placed_titles(src, a.get("titles", []), W, H), W, H)
        if studio
        else ass.overlay_events(a.get("overlays", []), a.get("titles", []), W, H)
    )
    burn = f"subtitles=overlay.ass:fontsdir={media.filter_path(ass.FONTS)}"
    bar = any(o["kind"] == "progress_bar" for o in a.get("overlays", []))
    if bar:
        bh = max(8, H // 240)
        filt = (
            f"[0:v]{burn}[t];"
            f"color=c=0xFFD700:s={W}x{bh}:r=30:d={D:.3f}[bar];"
            f"[t][bar]overlay=x='-W+W*t/{D:.3f}':y=H-h-{H // 9}:shortest=1[out]"
        )
        _burn(work, src, out, ["-filter_complex", filt, "-map", "[out]"])
    else:
        _burn(work, src, out, ["-vf", burn])


def _picture_samples(src: Path) -> tuple[np.ndarray, float]:
    """A small copy of the picture at a few frames a second, for placing type against it."""
    return media.decode_gray(src, width=SAMPLE_WIDTH, fps=SAMPLE_FPS), SAMPLE_FPS


def _frame_at(samples: np.ndarray, rate: float, t: float) -> np.ndarray:
    return samples[min(int(t * rate), len(samples) - 1)]


def _band_level(gray: np.ndarray, center: float, half: float) -> float:
    """The bright end of a horizontal band, 0..1, which is what type has to read against."""
    h = gray.shape[0]
    rows = gray[max(int((center - half) * h), 0) : int((center + half) * h) + 1]
    return float(np.percentile(rows, 90)) / 255 if rows.size else 0.0


def _placed_titles(src: Path, titles: list[dict], w: int, h: int) -> list[dict]:
    """Put each title where the picture is calm, and darken behind it only if it needs that."""
    if not titles:
        return []
    samples, rate = _picture_samples(src)
    placed = []
    for title in titles:
        frame = _frame_at(samples, rate, (title["start_sec"] + title["end_sec"]) / 2)
        y = ass.calmest_band(frame, ass.title_centers(w, h))
        alpha = ass.scrim_alpha(_band_level(frame, y, 0.1))
        placed.append({**title, "y_frac": y, "scrim_alpha": alpha})
    return placed


def _caption_levels(src: Path, captions: list[dict], w: int, h: int) -> list[float]:
    samples, rate = _picture_samples(src)
    line = ass.safe_area(w, h)["bottom"]
    return [
        max(
            _band_level(_frame_at(samples, rate, t), 1 - line - 0.04, 0.05)
            for t in (card["start_sec"], (card["start_sec"] + card["end_sec"]) / 2)
        )
        for card in captions
    ]


def _burn(work: Path, src: Path, out: Path, graph: list[str]) -> None:
    proc = media.run(
        ["-i", src.name, *graph, *media.MASTER_ARGS, out.name], cwd=work, loglevel="verbose"
    )
    refuse_fallback_fonts(proc.stderr)


def _op_burn_captions(work: Path, a: dict) -> None:
    src, out = _safe(work, a["input"]), _safe(work, a["out"])
    caps, W, H = a["captions"], a["width"], a["height"]
    if a.get("style") == "studio":
        text, report = ass.studio_captions(caps, W, H, _caption_levels(src, caps, W, H))
        (work / "type_report.json").write_text(json.dumps(report) + "\n")
    else:
        text = ass.kinetic(caps, W, H)
    (work / "captions.ass").write_text(text)
    burn = f"subtitles=captions.ass:fontsdir={media.filter_path(ass.FONTS)}"
    _burn(work, src, out, ["-vf", burn])


def _op_caption_files(work: Path, a: dict) -> None:
    for name, text in ass.sidecars(a["cues"], a["fps"]).items():
        (work / name).write_text(text)


def _music_chain(index: int, a: dict, duration: float, under_voice: bool) -> str:
    fade = min(MUSIC_FADE_SEC, duration * 0.25)
    pocket = f"{MUSIC_POCKET}," if under_voice else ""
    gain = a.get("music_gain_db", -19)
    return (
        f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,{pocket}volume={gain:.2f}dB,"
        f"afade=t=in:d=0.2,afade=t=out:st={duration - fade:.3f}:d={fade:.3f}"
    )


def _op_mix_audio(work: Path, a: dict) -> None:
    D = a["duration_sec"]
    ins: list[str] = []
    chains: list[str] = []
    labels: list[str] = []
    maps: list[str] = []
    idx = 0
    has_voice = bool(a.get("voice"))
    if has_voice:
        ins += ["-i", str(_safe(work, a["voice"]))]
        polish = f"{VOICE_CHAIN}," if a.get("voice_chain") else ""
        chains.append(
            f"[0:a]aresample=48000,aformat=channel_layouts=stereo,{polish}"
            f"apad=whole_dur={D:.3f},atrim=0:{D:.3f},asplit=3[voice][vkey][vstem]"
        )
        chains.append(ROOM_TONE.format(duration=D))
        labels += ["[voice]", "[room]"]
        maps += ["-map", "[vstem]", str(work / "voice.stem.wav")]
        idx = 1
    if a.get("music"):
        bed = media.loop_audio(_safe(work, a["music"]), work / "music.bed.wav", D)
        ins += ["-i", str(bed)]
        music = _music_chain(idx, a, D, has_voice)
        idx += 1
        if has_voice and a.get("duck"):
            chains.append(f"{music}[mus]")
            chains.append(f"[mus][vkey]{DUCK},asplit=2[musd][mstem]")
        else:
            chains.append(f"{music},asplit=2[musd][mstem]")
        labels.append("[musd]")
        maps += ["-map", "[mstem]", str(work / "music.stem.wav")]
    if has_voice and not a.get("music"):
        chains.append("[vkey]anullsink")
    for k, s in enumerate(a.get("sfx", [])):
        ins += ["-i", str(_safe(work, s["path"]))]
        ms = max(int(float(s["start_sec"]) * 1000), 0)
        chains.append(
            f"[{idx}:a]aresample=48000,aformat=channel_layouts=stereo,volume={float(s.get('gain_db', -12)):.2f}dB,"
            f"adelay={ms}|{ms}[sfx{k}]"
        )
        labels.append(f"[sfx{k}]")
        idx += 1
    if not labels:
        return
    filt = (
        ";".join(chains)
        + ";"
        + "".join(labels)
        + f"amix=inputs={len(labels)}:normalize=0:duration=longest,atrim=0:{D:.3f}[out]"
    )
    media.run(
        [
            *ins,
            "-filter_complex",
            filt,
            "-map",
            "[out]",
            "-ar",
            "48000",
            str(_safe(work, a["out"])),
            *maps,
        ]
    )


def _op_loudnorm(work: Path, a: dict) -> None:
    media.master_loudness(
        _safe(work, a["input"]), _safe(work, a["out"]), a["target_lufs"], a["true_peak_dbtp_max"]
    )


def _fades(a: dict) -> tuple[list[str], list[str]]:
    """Video and audio fades. The picture is fully black before its last frame, so a master can end on one."""
    vf, af = [], []
    D, fps = a.get("duration_sec") or 0, a.get("fps") or 30
    fin, fout = a.get("fade_in_sec") or 0, a.get("fade_out_sec") or 0
    if fin:
        vf.append(f"fade=t=in:st=0:d={fin:.3f}")
        af.append(f"afade=t=in:d={fin:.3f}")
    if fout and D > fout:
        vf.append(f"fade=t=out:st={D - fout:.3f}:d={fout - 1.5 / fps:.3f}")
        af.append(f"afade=t=out:st={D - fout:.3f}:d={fout:.3f}")
    return vf, af


def _write_master(work: Path, a: dict, vf: list[str], af: list[str], note: str) -> None:
    """A ProRes 422 HQ master with LPCM stereo: the file a premium platform ingests."""
    args = ["-i", str(_safe(work, a["video"]))]
    if a.get("audio"):
        args += ["-i", str(_safe(work, a["audio"])), "-map", "0:v", "-map", "1:a"]
        args += ["-c:a", "pcm_s24le", "-ar", "48000", "-ac", "2", "-channel_layout", "stereo"]
        if af:
            args += ["-af", ",".join(af)]
    media.run(
        [
            *args,
            "-vf",
            ",".join([*vf, media.TO_PRORES]),
            *media.PRORES_ARGS,
            "-metadata",
            f"comment={note}",
            str(_safe(work, a["master"])),
        ]
    )


def _op_export(work: Path, a: dict) -> None:
    out = _safe(work, a["out"])
    vf, af = _fades(a)
    note = (
        "Made with Kalainova; contains AI-generated media"
        if a.get("synthetic", True)
        else "Edited with Kalainova"
    )
    args = ["-i", str(_safe(work, a["video"]))]
    if a.get("audio"):
        args += [
            "-i",
            str(_safe(work, a["audio"])),
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-ar",
            "48000",
            "-shortest",
        ]
        if af:
            args += ["-af", ",".join(af)]
    args += [
        "-vf",
        ",".join([*vf, media.TO_DELIVERY]),
        "-c:v",
        "libx264",
        "-preset",
        a.get("preset", "veryfast"),
        "-crf",
        str(a.get("crf", 20)),
        "-profile:v",
        "high",
        "-pix_fmt",
        "yuv420p",
        "-x264-params",
        media.X264_FINISH,
        *media.COLOR_TAGS,
        "-movflags",
        "+faststart",
        "-metadata",
        f"comment={note}",
        str(out),
    ]
    media.run(args)
    if a.get("master"):
        _write_master(work, a, vf, af, note)
    if a.get("thumbnail"):
        media.run(
            [
                "-ss",
                "0.9",
                "-i",
                str(out),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                str(_safe(work, a["thumbnail"])),
            ]
        )
    if a.get("audio_only") and a.get("audio"):
        media.run(
            [
                "-i",
                str(_safe(work, a["audio"])),
                "-c:a",
                "aac",
                "-b:a",
                "256k",
                str(_safe(work, a["audio_only"])),
            ]
        )
