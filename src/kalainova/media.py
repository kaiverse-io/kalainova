"""ffmpeg / ffprobe helpers. Commands are argument lists, never shell strings."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"


class MediaError(RuntimeError):
    pass


@lru_cache(maxsize=None)
def has_filter(name: str) -> bool:
    """Whether this ffmpeg build has a filter. Builds differ, and the engine must say so or adapt."""
    proc = subprocess.run([FFMPEG, "-hide_banner", "-filters"], capture_output=True, text=True)
    return any(line.split()[1:2] == [name] for line in proc.stdout.splitlines())


def run(
    args: list[str], *, quiet: bool = True, cwd: str | Path | None = None
) -> subprocess.CompletedProcess:
    cmd = [FFMPEG, "-hide_banner", "-y", "-loglevel", "error" if quiet else "info", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if proc.returncode != 0:
        raise MediaError(
            f"ffmpeg failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-2000:]}"
        )
    return proc


def probe(path: str | Path) -> dict:
    proc = subprocess.run(
        [
            FFPROBE,
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise MediaError(f"ffprobe failed on {path}: {proc.stderr}")
    return json.loads(proc.stdout)


def duration(path: str | Path) -> float:
    return float(probe(path)["format"]["duration"])


def summarize(path: str | Path) -> dict:
    """Shape for asset_manifest.assets[].probe"""
    info = probe(path)
    out: dict = {}
    for s in info.get("streams", []):
        if s.get("codec_type") == "video" and "width" not in out:
            out["width"] = int(s["width"])
            out["height"] = int(s["height"])
            num, _, den = s.get("avg_frame_rate", "0/1").partition("/")
            try:
                fps = float(num) / float(den or 1)
            except ZeroDivisionError:
                fps = 0.0
            if fps:
                out["fps"] = round(fps, 3)
        if s.get("codec_type") == "audio" and "sample_rate_hz" not in out:
            out["sample_rate_hz"] = int(s["sample_rate"])
            out["channels"] = int(s["channels"])
    return out


def loudness(path: str | Path) -> dict:
    """Integrated loudness (LUFS) and true peak (dBTP) via ebur128."""
    proc = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-filter_complex",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    text = proc.stderr
    summary = text[text.rfind("Summary:") :] if "Summary:" in text else text
    i = re.search(r"I:\s+(-?[\d.]+) LUFS", summary)
    tp = re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary)
    return {
        "integrated_lufs": float(i.group(1)) if i else None,
        "true_peak_dbtp": float(tp.group(1)) if tp else None,
    }


def loudnorm_two_pass(
    src: Path, dst: Path, target: float = -14.0, tp: float = -1.0, lra: float = 11.0
) -> dict:
    first = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostats",
            "-i",
            str(src),
            "-af",
            f"loudnorm=I={target}:TP={tp}:LRA={lra}:print_format=json",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    blob = first.stderr[first.stderr.rfind("{") : first.stderr.rfind("}") + 1]
    m = json.loads(blob)
    af = (
        f"loudnorm=I={target}:TP={tp}:LRA={lra}:measured_I={m['input_i']}:measured_TP={m['input_tp']}"
        f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}"
        ":linear=true:print_format=summary"
    )
    run(["-i", str(src), "-af", af, "-ar", "48000", "-ac", "2", str(dst)])
    return m


def blackdetect(path: str | Path, min_dur: float = 0.5) -> list[tuple[float, float]]:
    proc = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vf",
            f"blackdetect=d={min_dur}:pix_th=0.05",
            "-an",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    spans = []
    for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+)", proc.stderr):
        spans.append((float(m.group(1)), float(m.group(2))))
    return spans


def silencedetect(
    path: str | Path, noise_db: float = -45, min_dur: float = 1.5
) -> list[tuple[float, float]]:
    proc = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-af",
            f"silencedetect=n={noise_db}dB:d={min_dur}",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    return list(zip(starts, ends))


def frame_at(path: str | Path, t: float, dst: Path) -> Path:
    run(["-ss", f"{t:.3f}", "-i", str(path), "-frames:v", "1", str(dst)])
    return dst


def stream_info(path: str | Path, kind: str) -> dict:
    """The first stream of a kind, as ffprobe reports it."""
    return next((s for s in probe(path).get("streams", []) if s.get("codec_type") == kind), {})


def scene_changes(path: str | Path, threshold: float = 0.32) -> list[float]:
    """Seconds where the picture changes."""
    proc = subprocess.run(
        [
            FFMPEG,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-an",
            "-vf",
            f"scale=320:-2,select='gt(scene,{threshold})',showinfo",
            "-f",
            "null",
            "-",
        ],
        capture_output=True,
        text=True,
    )
    return [float(m) for m in re.findall(r"pts_time:([\d.]+)", proc.stderr)]


def _decode(args: list[str]) -> bytes:
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", *args]
    return subprocess.run(cmd, capture_output=True).stdout


def decode_gray(
    path: str | Path,
    *,
    width: int,
    fps: float | None = None,
    start: float = 0.0,
    duration: float | None = None,
) -> "np.ndarray":
    """Frames as uint8 luma [n, h, w]. Height follows the file's shape."""
    info = summarize(path)
    height = max(round(width * info["height"] / info["width"]) // 2 * 2, 2)
    seek = ["-ss", f"{start:.3f}"] if start else []
    span = ["-t", f"{duration:.3f}"] if duration else []
    rate = f"fps={fps:g}," if fps else ""
    blob = _decode(
        [
            *seek,
            *span,
            "-i",
            str(path),
            "-an",
            "-vf",
            f"{rate}scale={width}:{height}:flags=bicubic,format=gray",
            "-f",
            "rawvideo",
            "-",
        ]
    )
    frames = np.frombuffer(blob, np.uint8)
    n = frames.size // (width * height)
    return frames[: n * width * height].reshape(n, height, width)


def gray_frame(path: str | Path, t: float, *, width: int | None = None) -> "np.ndarray":
    """One frame as uint8 luma, full size unless a width is given."""
    info = summarize(path)
    w = width or info["width"]
    return decode_gray(path, width=w, start=t, duration=0.08)[0]


def decode_stereo(path: str | Path, sr: int = 48000) -> tuple["np.ndarray", "np.ndarray", int]:
    """Left, right, and sample rate, as float32 in -1..1."""
    blob = _decode(["-i", str(path), "-vn", "-ac", "2", "-ar", str(sr), "-f", "f32le", "-"])
    x = np.frombuffer(blob, np.float32)
    x = x[: x.size // 2 * 2].reshape(-1, 2)
    return x[:, 0], x[:, 1], sr
