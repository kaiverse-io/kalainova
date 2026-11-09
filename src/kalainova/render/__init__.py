"""EDIT -> RENDER. Compiles edit_manifest.json into render_plan.json (fixed ops), then executes it.

The executor is the only code that turns a plan into ffmpeg arguments. Ops come
from a closed set and every path is resolved inside the job work dir, so a
model-written plan cannot run a shell command or touch files outside the job.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import mediascan
from ..jobfs import ContractError, Job
from . import cache as step_cache
from . import export, picture, sound, spec
from .sound import MUSIC_UNDER_VOICE_DB

TITLE_HOLD_SEC = 3.0
DISSOLVE_SEC = 0.4
Step = dict[str, Any]
OPERATIONS: dict[str, Callable[[Path, dict[str, Any]], None]] = {
    "still": picture.op_still,
    "cut": picture.op_cut,
    "scale": picture.op_scale,
    "concat": picture.op_concat,
    "overlay_text": picture.op_overlay_text,
    "burn_captions": picture.op_burn_captions,
    "caption_files": picture.op_caption_files,
    "mix_audio": sound.op_mix_audio,
    "loudnorm": sound.op_loudnorm,
    "export_audio": sound.op_export_audio,
    "export": export.op_export,
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ------------------------------------------------------------------ compile
def _audio_steps(em: dict[str, Any], assets: dict[str, Any], *, original: bool) -> list[Step]:
    """The mix and its master, shared by a piece with a picture and a piece without one."""
    prof = em["profile"]
    a = em.get("audio") or {}
    mix: dict[str, Any] = {"out": "mix.wav", "duration_sec": em["duration_sec"]}
    if a.get("voice_asset_id"):
        mix["voice"] = assets[a["voice_asset_id"]]["path"]
        mix["voice_chain"] = True
    elif original:
        mix["voice"] = "orig.wav"  # the footage's own sound leads; music ducks under it
        mix["voice_chain"] = bool(em.get("speech"))
    if a.get("music_asset_id"):
        mix["music"] = assets[a["music_asset_id"]]["path"]
        mix["music_gain_db"] = a.get("music_gain_db", MUSIC_UNDER_VOICE_DB)
        mix["duck"] = a.get("duck", True)
    mix["sfx"] = [
        {
            "path": assets[x["asset_id"]]["path"],
            "start_sec": x["start_sec"],
            "gain_db": x.get("gain_db", -12),
        }
        for x in a.get("sfx", [])
    ]
    mix["ambience"] = [
        {
            "path": assets[x["asset_id"]]["path"],
            "start_sec": x["start_sec"],
            "end_sec": x["end_sec"],
            "gain_db": x.get("gain_db", -24),
        }
        for x in a.get("ambience", [])
    ]
    master = {
        "input": "mix.wav",
        "out": "mix.norm.wav",
        "target_lufs": prof.get("target_lufs", -14),
        "true_peak_dbtp_max": prof.get("true_peak_dbtp_max", -1),
    }
    return [{"op": "mix_audio", "args": mix}, {"op": "loudnorm", "args": master}]


def _sound_only_steps(em: dict[str, Any], assets: dict[str, Any], synthetic: bool) -> list[Step]:
    steps = _audio_steps(em, assets, original=False)
    cues = em.get("closed_captions") or em.get("captions")
    if cues:  # a transcript at a nominal rate, so a listener who cannot hear still gets the words
        steps.append({"op": "caption_files", "args": {"cues": cues, "fps": 24.0}})
    delivered = {
        "audio": "mix.norm.wav",
        "master": "final.wav",
        "delivery": "final.m4a",
        "synthetic": synthetic,
    }
    return [*steps, {"op": "export_audio", "args": delivered}]


def _span(em: dict[str, Any], i: int) -> float:
    """Segment length snapped to whole frames from cumulative starts, so picture never drifts."""
    fps = em["profile"]["fps"]
    cuts = em["cuts"]
    start = round(cuts[i].get("start_sec", 0) * fps)
    end = round((cuts[i + 1].get("start_sec") if i + 1 < len(cuts) else em["duration_sec"]) * fps)
    return float(max(end - start, 1) / fps)


def _copied(args: dict[str, Any], cut: dict[str, Any], keys: tuple[str, ...]) -> None:
    for key in keys:
        if cut.get(key) is not None:
            args[key] = cut[key]


@dataclass
class _Segments:
    """The picture's parts, in order, with what the join needs to know about them."""

    work: Path
    steps: list[Step] = field(default_factory=list)
    outs: list[str] = field(default_factory=list)
    lengths: list[float] = field(default_factory=list)
    sounds: list[str] = field(default_factory=list)
    boxes: dict[str, tuple[float, float, float, float]] = field(default_factory=dict)

    def add_still(
        self, src: dict[str, Any], cut: dict[str, Any], out: str, seg: float, prof: dict[str, Any]
    ) -> None:
        args: dict[str, Any] = {
            "source": src["path"],
            "out": out,
            "width": prof["width"],
            "height": prof["height"],
            "fps": prof["fps"],
            "duration_sec": seg,
            "motion": cut.get("motion", "none"),
        }
        _copied(args, cut, ("crop_x", "grade", "gamma"))
        self.steps.append({"op": "still", "args": args})

    def add_clip(
        self,
        i: int,
        src: dict[str, Any],
        cut: dict[str, Any],
        out: str,
        seg: float,
        tail: float,
        prof: dict[str, Any],
        original: bool,
    ) -> None:
        raw = f"seg/{i:02d}.raw.mp4"
        speed = float(cut.get("speed") or 1.0)
        # take the dissolve overlap from the source when it exists; tpad covers the rest
        wanted = cut["out_sec"] + tail * speed
        args: dict[str, Any] = {
            "source": src["path"],
            "kind": src["kind"],
            "in_sec": cut["in_sec"],
            "out_sec": round(min(wanted, src.get("duration_sec", wanted)), 3),
            "fps": prof["fps"],
            "out": raw,
            "pad_to_sec": seg if (cut.get("hold_last_frame") or src["kind"] == "video") else None,
        }
        if speed != 1.0:
            args["speed"] = speed
        if original:
            args["audio_out"] = f"seg/{i:02d}.wav"
            args["audio_from_source"] = bool(cut.get("keep_audio")) and speed == 1.0
            args["pad_to_sec"] = seg
            self.sounds.append(args["audio_out"])
        self.steps.append({"op": "cut", "args": args})
        self.steps.append({"op": "scale", "args": self._scale_args(raw, src, cut, out, seg, prof)})

    def _scale_args(
        self,
        raw: str,
        src: dict[str, Any],
        cut: dict[str, Any],
        out: str,
        seg: float,
        prof: dict[str, Any],
    ) -> dict[str, Any]:
        args: dict[str, Any] = {
            "input": raw,
            "out": out,
            "width": prof["width"],
            "height": prof["height"],
            "fps": prof["fps"],
            "duration_sec": seg,
        }
        _copied(args, cut, ("crop_x", "zoom", "grade", "gamma"))
        if src["kind"] == "video":
            box = self.boxes.setdefault(src["path"], mediascan.picture_box(self.work / src["path"]))
            if box != mediascan.FULL_FRAME:
                args["picture_box"] = list(box)
        return args


def _segments(job: Job, em: dict[str, Any], assets: dict[str, Any], overlap: float) -> _Segments:
    parts = _Segments(job.work)
    cuts = em.get("cuts", [])
    original = bool(em.get("original_audio"))
    for i, cut in enumerate(cuts):
        src = assets[cut["source"]]
        out = f"seg/{i:02d}.mp4"
        tail = overlap if i < len(cuts) - 1 else 0.0
        seg = round(_span(em, i) + tail, 3)  # overlap so the dissolve eats no beat time
        parts.lengths.append(seg)
        if src["kind"] == "still":
            parts.add_still(src, cut, out, seg, em["profile"])
        else:
            parts.add_clip(i, src, cut, out, seg, tail, em["profile"], original)
        parts.outs.append(out)
    return parts


def _titles(em: dict[str, Any], studio: bool) -> list[dict[str, Any]]:
    titles = []
    for i, cut in enumerate(em.get("cuts", [])):
        if not cut.get("title"):
            continue
        at = cut.get("start_sec", 0)
        span = _span(em, i)
        hold = min(TITLE_HOLD_SEC, span) - 0.15 if studio else min(2.2, span)
        titles.append(
            {
                "text": cut["title"],
                "start_sec": at + (0.15 if studio else 0.1),
                "end_sec": at + max(hold, 0.6),
            }
        )
    return titles


def _caption_steps(em: dict[str, Any], picture: str) -> tuple[list[Step], str]:
    """Caption files, and burned captions if the piece carries them. Returns the picture to use."""
    prof = em["profile"]
    steps: list[Step] = []
    cues = em.get("closed_captions") or em.get("captions")
    if cues:
        steps.append({"op": "caption_files", "args": {"cues": cues, "fps": prof["fps"]}})
    if not em.get("captions"):
        return steps, picture
    style = em.get("caption_style", "kinetic")
    steps.append(
        {
            "op": "burn_captions",
            "args": {
                "input": picture,
                "out": "picture.cap.mp4",
                "width": prof["width"],
                "height": prof["height"],
                "style": style if style != "none" else "plain",
                "captions": em["captions"],
            },
        }
    )
    return steps, "picture.cap.mp4"


def _picture_steps(job: Job, em: dict[str, Any], assets: dict[str, Any]) -> list[Step]:
    prof = em["profile"]
    studio = em.get("theme", "studio") == "studio"
    dissolve = em.get("transition") == "dissolve"
    overlap = DISSOLVE_SEC if dissolve else 0.0
    parts = _segments(job, em, assets, overlap)
    join = {
        "inputs": parts.outs,
        "out": "picture.mp4",
        "fps": prof["fps"],
        "transition": "dissolve" if dissolve else "cut",
        "xfade_sec": overlap,
        "durations": parts.lengths,
        "audio_inputs": parts.sounds,
        "audio_out": "orig.wav" if parts.sounds else None,
    }
    steps = [*parts.steps, {"op": "concat", "args": join}]
    titles, overlays = _titles(em, studio), em.get("overlays", [])
    if not titles and not overlays:
        # Nothing to burn in: a pass would only write a second lossless copy of the whole picture.
        return steps
    overlay = {
        "input": "picture.mp4",
        "out": "picture.ov.mp4",
        "width": prof["width"],
        "height": prof["height"],
        "overlays": overlays,
        "titles": titles,
        "theme": "studio" if studio else "bold",
        "duration_sec": em["duration_sec"],
    }
    return [*steps, {"op": "overlay_text", "args": overlay}]


def _final_step(em: dict[str, Any], am: dict[str, Any], video: str, audio: str | None) -> Step:
    prof = em["profile"]
    return {
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
            "fps": prof["fps"],
            "master": "final.master.mov" if prof.get("delivery") == "mezzanine" else None,
            "synthetic": any(x.get("synthetic") for x in am["assets"]),
        },
    }


def _piece_steps(job: Job, em: dict[str, Any], am: dict[str, Any]) -> list[Step]:
    assets = {a["id"]: a for a in am["assets"]}
    if not em.get("cuts"):
        return _sound_only_steps(em, assets, any(x.get("synthetic") for x in am["assets"]))
    original = bool(em.get("original_audio"))
    picture = _picture_steps(job, em, assets)
    captions, video = _caption_steps(em, picture[-1]["args"]["out"])
    steps = [*picture, *captions]
    audio = None
    if em.get("audio") or original:
        steps += _audio_steps(em, assets, original=original)
        audio = "mix.norm.wav"
    return [*steps, _final_step(em, am, video, audio)]


def compile_plan(job: Job) -> dict[str, Any]:
    em = job.read("edit_manifest")
    plan = {
        "schema_version": "0.1",
        "job_id": em["job_id"],
        "edit_manifest_sha256": _sha(job.path("edit_manifest")),
        "steps": _piece_steps(job, em, job.read("asset_manifest")),
    }
    job.write("render_plan", plan)
    return plan


# ------------------------------------------------------------------ execute
def stamp(job: Job, video: Path) -> None:
    """Tie the rendered file to the asset record it was made from."""
    if job.has("asset_manifest"):
        record = {
            "artifact_sha256": _sha(video),
            "asset_manifest_sha256": _sha(job.path("asset_manifest")),
        }
        master = video.with_name("final.master.mov")
        if master.exists():
            record["master_sha256"] = _sha(master)
        job.write_stamp(record)


def _run_steps(job: Job, plan: dict[str, Any], *, cache: bool) -> None:
    work = job.work
    done = step_cache.load(work) if cache else {}
    for n, step in enumerate(plan["steps"]):
        op, given = step["op"], step.get("args", {})
        if op not in spec.OPS:
            raise ContractError(f"step {n}: op {op!r} not allowed")
        args = spec.coerce(op, given if isinstance(given, dict) else {}, n)
        key = step_cache.key(work, op, args)
        if cache and step_cache.unchanged(work, done, n, key, args):
            continue
        OPERATIONS[op](work, args)
        step_cache.remember(done, n, key)
        step_cache.save(work, done)


def execute(job: Job, plan: dict[str, Any] | None = None, *, cache: bool = True) -> Path:
    """Run the plan. A step whose inputs and settings have not changed keeps its old output."""
    plan = plan or job.read("render_plan")
    if plan.get("edit_manifest_sha256") and job.has("edit_manifest"):
        if _sha(job.path("edit_manifest")) != plan["edit_manifest_sha256"]:
            raise ContractError(
                f"{job.id}: render_plan is stale; edit_manifest changed since compile"
            )
    work = job.work
    (work / "seg").mkdir(exist_ok=True)
    _run_steps(job, plan, cache=cache)
    out = work / "final.mp4" if "video" in job.job.get("media", []) else job.artifact()
    digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    (work / "render.done.json").write_text(json.dumps({"plan_sha256": digest}) + "\n")
    if out.exists():
        stamp(job, out)
    return out
