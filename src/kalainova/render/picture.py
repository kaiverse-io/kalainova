"""The picture path: stills and clips to lossless segments, joined, then titled and captioned.

Every stage is lossless 10-bit 4:4:4 BT.709, so one final encode is the only place quality is spent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt

from .. import captions as ass
from .. import look, media, motion
from ..jobfs import ContractError
from . import drawn
from .spec import safe_path

Arr = npt.NDArray[Any]

# Video usually arrives in 8 bits, which leaves contours in skies. This smooths them at high depth.
DEBAND_VIDEO = "format=yuv444p16le,deband=1thr=0.012:2thr=0.012:3thr=0.012:range=20:blur=1"
SHARPEN_ENLARGED = "cas=strength=0.3"
SAMPLE_WIDTH, SAMPLE_FPS = 270, 2.0


def refuse_fallback_fonts(log: str) -> None:
    """libass names a system path when it cannot find the font asked for. That is not our type."""
    for wanted, used in re.findall(r"fontselect: \(([^,]+),[^)]*\) -> ([^,]+),", log):
        if "/" in used:
            raise ContractError(
                f"font {wanted!r} is not in {ass.FONTS}; libass fell back to {used}"
            )


def _look_filter(work: Path, a: dict[str, Any]) -> list[str]:
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


def op_still(work: Path, a: dict[str, Any]) -> None:
    frames = motion.frames_16bit(
        safe_path(work, a["source"]),
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
        out=safe_path(work, a["out"]),
        cwd=work,
    )


def op_cut(work: Path, a: dict[str, Any]) -> None:
    src, out = safe_path(work, a["source"]), safe_path(work, a["out"])
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
        aout = safe_path(work, a["audio_out"])
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


def _finish_after_scale(source: tuple[int, int], width: int, height: int) -> str:
    """An enlarged source comes back soft, so it gets a light sharpen. Full size is left alone."""
    enlarged = max(width / source[0], height / source[1]) > 1.0
    return f"{SHARPEN_ENLARGED}," if enlarged else ""


def op_scale(work: Path, a: dict[str, Any]) -> None:
    src, out = safe_path(work, a["input"]), safe_path(work, a["out"])
    width, height = a["width"], a["height"]
    z = a.get("zoom") or 1.0
    info = media.summarize(src)
    sharpen = _finish_after_scale((info["width"], info["height"]), width, height)
    cx = 0.5 if a.get("crop_x") is None else a["crop_x"]
    box = a.get("picture_box")
    bars = f"crop=iw*{box[2]:.5f}:ih*{box[3]:.5f}:iw*{box[0]:.5f}:ih*{box[1]:.5f}," if box else ""
    # fill the frame, punch in if asked, then crop around the subject (clamped inside the frame)
    fit = (
        f"{bars}{DEBAND_VIDEO},"
        f"scale={int(width * z)}:{int(height * z)}:"
        "force_original_aspect_ratio=increase:flags=lanczos,"
        f"{sharpen}crop={width}:{height}:x='(iw-{width})*{min(max(cx, 0.0), 1.0):.4f}':"
        f"y='(ih-{height})/2',fps={a['fps']:g},setsar=1"
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


def _dissolve_graph(durations: list[float], overlap: float) -> str:
    """Each picture into the next. Offsets are from the start of the join, so overlaps add up."""
    graph, previous, total = "", "v0", durations[0]
    for i in range(1, len(durations)):
        label = "out" if i == len(durations) - 1 else f"x{i}"
        graph += (
            f"[{previous}][v{i}]xfade=transition=fade:duration={overlap:.3f}:"
            f"offset={total - overlap:.3f}[{label}];"
        )
        previous, total = label, total + durations[i] - overlap
    return graph.rstrip(";")


def _sound_dissolve_graph(count: int, overlap: float) -> str:
    graph, previous = "", "0:a"
    for i in range(1, count):
        label = "aout" if i == count - 1 else f"ax{i}"
        graph += f"[{previous}][{i}:a]acrossfade=d={overlap:.3f}:c1=tri:c2=tri[{label}];"
        previous = label
    return graph.rstrip(";")


def _inputs(paths: list[Path]) -> list[str]:
    return [arg for path in paths for arg in ("-i", str(path))]


def _join_picture(work: Path, a: dict[str, Any], overlap: float) -> None:
    pictures = [safe_path(work, p) for p in a["inputs"]]
    count = len(pictures)
    prepare = "".join(
        f"[{i}:v]settb=AVTB,fps={a['fps']:g},format={media.MASTER_PIX_FMT}[v{i}];"
        for i in range(count)
    )
    durations = [float(d) for d in a.get("durations") or []]
    if overlap > 0 and count > 1 and len(durations) == count:
        join = _dissolve_graph(durations, overlap)
    else:
        join = "".join(f"[v{i}]" for i in range(count)) + f"concat=n={count}:v=1:a=0[out]"
    media.run(
        [
            *_inputs(pictures),
            "-filter_complex",
            prepare + join,
            "-map",
            "[out]",
            *media.MASTER_ARGS,
            str(safe_path(work, a["out"])),
        ]
    )


def _join_sound(work: Path, a: dict[str, Any], overlap: float) -> None:
    sounds = [safe_path(work, p) for p in a.get("audio_inputs") or []]
    if not sounds or not a.get("audio_out"):
        return
    count = len(sounds)
    if overlap > 0 and count > 1:
        graph = _sound_dissolve_graph(count, overlap)
    else:
        graph = "".join(f"[{i}:a]" for i in range(count)) + f"concat=n={count}:v=0:a=1[aout]"
    media.run(
        [
            *_inputs(sounds),
            "-filter_complex",
            graph,
            "-map",
            "[aout]",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(safe_path(work, a["audio_out"])),
        ]
    )


def op_concat(work: Path, a: dict[str, Any]) -> None:
    overlap = (a.get("xfade_sec") or 0.0) if a.get("transition") == "dissolve" else 0.0
    _join_picture(work, a, overlap)
    _join_sound(work, a, overlap)


def op_overlay_text(work: Path, a: dict[str, Any]) -> None:
    src, out = safe_path(work, a["input"]), safe_path(work, a["out"])
    width, height, seconds = a["width"], a["height"], a["duration_sec"]
    ass_path = work / "overlay.ass"
    studio = a.get("theme") == "studio"
    ass_path.write_text(
        ass.studio_titles(_placed_titles(src, a.get("titles", []), width, height), width, height)
        if studio
        else ass.overlay_events(a.get("overlays", []), a.get("titles", []), width, height)
    )
    burn = f"subtitles=overlay.ass:fontsdir={media.filter_path(ass.FONTS)}"
    bar = any(o["kind"] == "progress_bar" for o in a.get("overlays", []))
    if bar:
        bh = max(8, height // 240)
        filt = (
            f"[0:v]{burn}[t];"
            f"color=c=0xFFD700:s={width}x{bh}:r=30:d={seconds:.3f}[bar];"
            f"[t][bar]overlay=x='-W+W*t/{seconds:.3f}':y=H-h-{height // 9}:shortest=1[out]"
        )
        _burn(work, src, out, ["-filter_complex", filt, "-map", "[out]"])
    else:
        _burn(work, src, out, ["-vf", burn])


def _picture_samples(src: Path) -> tuple[Arr, float]:
    """A small copy of the picture at a few frames a second, for placing type against it."""
    return media.decode_gray(src, width=SAMPLE_WIDTH, fps=SAMPLE_FPS), SAMPLE_FPS


def _frame_at(samples: Arr, rate: float, t: float) -> Arr:
    frame: Arr = samples[min(int(t * rate), len(samples) - 1)]
    return frame


def _band_level(gray: Arr, center: float, half: float) -> float:
    """The bright end of a horizontal band, 0..1, which is what type has to read against."""
    h = gray.shape[0]
    rows = gray[max(int((center - half) * h), 0) : int((center + half) * h) + 1]
    return float(np.percentile(rows, 90)) / 255 if rows.size else 0.0


def _placed_titles(src: Path, titles: list[dict[str, Any]], w: int, h: int) -> list[dict[str, Any]]:
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


def _caption_levels(src: Path, captions: list[dict[str, Any]], w: int, h: int) -> list[float]:
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


def op_burn_captions(work: Path, a: dict[str, Any]) -> None:
    src, out = safe_path(work, a["input"]), safe_path(work, a["out"])
    caps, width, height = a["captions"], a["width"], a["height"]
    if a.get("style") == "drawn":
        drawn.burn_drawn_captions(work, src, out, a)
        return
    if a.get("style") == "studio":
        text, report = ass.studio_captions(
            caps, width, height, _caption_levels(src, caps, width, height)
        )
        (work / "type_report.json").write_text(json.dumps(report) + "\n")
    else:
        text = ass.kinetic(caps, width, height)
    (work / "captions.ass").write_text(text)
    burn = f"subtitles=captions.ass:fontsdir={media.filter_path(ass.FONTS)}"
    _burn(work, src, out, ["-vf", burn])


def op_caption_files(work: Path, a: dict[str, Any]) -> None:
    for name, text in ass.sidecars(a["cues"], a["fps"]).items():
        (work / name).write_text(text)
