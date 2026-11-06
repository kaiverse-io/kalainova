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
MASTER_PASSES = 3

# Every stage between the source and the delivered file is lossless 10-bit 4:4:4 BT.709, so one final
# encode is the only place quality is spent. The tags stop players guessing a colour matrix.
COLOR_TAGS = [
    "-colorspace",
    "bt709",
    "-color_primaries",
    "bt709",
    "-color_trc",
    "bt709",
    "-color_range",
    "tv",
]
MASTER_PIX_FMT = "yuv444p10le"
MASTER_ARGS = ["-c:v", "libx264", "-preset", "ultrafast", "-qp", "0", "-pix_fmt", MASTER_PIX_FMT, *COLOR_TAGS]
_SWS = "out_color_matrix=bt709:out_range=tv:flags=lanczos+accurate_rnd+full_chroma_int"
_TAG_FRAMES = "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv"
TO_BT709 = f"scale={_SWS},{_TAG_FRAMES}"
TO_DELIVERY = f"scale={_SWS},format=yuv420p,{_TAG_FRAMES}"
# aq-mode 3 spends bits in dark gradients, where 8-bit bands first. Deblock is eased to keep fine detail.
X264_FINISH = "aq-mode=3:aq-strength=0.9:deblock=-1,-1:psy-rd=1.0,0.15"
HDR_TO_SDR = "zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt709,tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv"


class MediaError(RuntimeError):
    pass


@lru_cache(maxsize=None)
def has_filter(name: str) -> bool:
    """Whether this ffmpeg build has a filter. Builds differ, and the engine must say so or adapt."""
    proc = subprocess.run([FFMPEG, "-hide_banner", "-filters"], capture_output=True, text=True)
    return any(line.split()[1:2] == [name] for line in proc.stdout.splitlines())


def run(
    args: list[str], *, cwd: str | Path | None = None, loglevel: str = "error"
) -> subprocess.CompletedProcess:
    cmd = [FFMPEG, "-hide_banner", "-y", "-loglevel", loglevel, *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    if proc.returncode != 0:
        raise MediaError(
            f"ffmpeg failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-2000:]}"
        )
    return proc


def filter_path(path: str | Path) -> str:
    """A path as one filtergraph value, with the characters the parser treats as syntax escaped."""
    return re.sub(r"([\\:',\[\];])", r"\\\1", str(path))


def from_source_color(path: str | Path) -> list[str]:
    """Filters that bring a source to SDR. Phones shoot HDR, and it looks grey and flat untreated."""
    transfer = stream_info(path, "video").get("color_transfer")
    return [HDR_TO_SDR] if transfer in ("arib-std-b67", "smpte2084") else []


def encode_rgb48(frames, *, size: tuple[int, int], fps: float, vf: str, out: Path, cwd: Path) -> None:
    """Encode rgb48 frames from a generator to the master format."""
    cmd = [
        FFMPEG,
        "-hide_banner",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb48le",
        "-s",
        f"{size[0]}x{size[1]}",
        "-r",
        f"{fps:g}",
        "-i",
        "pipe:0",
        "-vf",
        vf,
        *MASTER_ARGS,
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd)
    try:
        for frame in frames:
            proc.stdin.write(frame)
    except BrokenPipeError:
        pass  # ffmpeg stopped early, and its own message explains why
    _, err = proc.communicate()
    if proc.returncode != 0:
        raise MediaError(f"ffmpeg failed ({proc.returncode}) encoding frames:\n{err.decode()[-2000:]}")


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
    lra = re.search(r"LRA:\s+([\d.]+) LU", summary)
    return {
        "integrated_lufs": float(i.group(1)) if i else None,
        "true_peak_dbtp": float(tp.group(1)) if tp else None,
        "loudness_range_lu": float(lra.group(1)) if lra else None,
    }


def master_loudness(src: Path, dst: Path, target: float, ceiling: float) -> Path:
    """Set the level with one gain and catch peaks with a true-peak limiter at 4x, then check the result.

    A single gain keeps the mix's dynamics. loudnorm's dynamic mode, which it falls back to whenever
    the peaks do not fit, rides the level and audibly pumps music under speech.
    """
    measured = loudness(src)["integrated_lufs"]
    if measured is None:  # digital silence has no loudness to set
        run(["-i", str(src), "-c:a", "pcm_s24le", "-ar", "48000", "-ac", "2", str(dst)])
        return dst
    limit = 10 ** ((ceiling - 0.3) / 20)
    gain = target - measured
    for _ in range(MASTER_PASSES):
        chain = (
            f"volume={gain:.3f}dB,aresample=192000,"
            f"alimiter=limit={limit:.5f}:attack=1:release=60:level=disabled,aresample=48000"
        )
        run(["-i", str(src), "-af", chain, "-c:a", "pcm_s24le", "-ac", "2", str(dst)])
        miss = target - (loudness(dst)["integrated_lufs"] or target)
        if abs(miss) <= 0.1:
            break
        gain += miss
    return dst


def loop_audio(src: Path, dst: Path, seconds: float, crossfade: float = 1.5) -> Path:
    """Extend a bed to length with equal-power crossfades, so the joins are never heard."""
    length = duration(src)
    if length >= seconds:
        run(["-i", str(src), "-t", f"{seconds:.3f}", "-ar", "48000", "-ac", "2", str(dst)])
        return dst
    fade = min(crossfade, length / 3)
    copies = int(np.ceil((seconds - fade) / (length - fade))) + 1
    inputs = [arg for _ in range(copies) for arg in ("-i", str(src))]
    graph, last = "", "0:a"
    for i in range(1, copies):
        graph += f"[{last}][{i}:a]acrossfade=d={fade:.3f}:c1=qsin:c2=qsin[x{i}];"
        last = f"x{i}"
    run(
        [
            *inputs,
            "-filter_complex",
            graph.rstrip(";"),
            "-map",
            f"[{last}]",
            "-t",
            f"{seconds:.3f}",
            "-ar",
            "48000",
            "-ac",
            "2",
            str(dst),
        ]
    )
    return dst


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
