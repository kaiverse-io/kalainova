"""The delivery file against a premium platform's published ingest requirements."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import numpy as np

from .. import media, mediascan
from .picture import BLACK_LEVEL, DUPLICATE_LEVEL, Arr
from .readings import Reading, limits

MASTER_SIZES = {(1920, 1080), (3840, 2160), (4096, 2160)}


def _check(rid: str, value: Any, limit: str, ok: bool) -> dict[str, Any]:
    return asdict(Reading(rid, value, limit, bool(ok), blocks=True))


def _head_bytes(path: Path, count: int = 1 << 20) -> bytes:
    with path.open("rb") as fh:
        return fh.read(count)


def _master_video(path: Path, target_fps: float) -> list[dict[str, Any]]:
    v = media.stream_info(path, "video")
    head = _head_bytes(path)
    tags = {v.get(k) for k in ("color_primaries", "color_transfer", "color_space")}
    num, _, den = str(v.get("r_frame_rate", "0/1")).partition("/")
    fps = float(num) / float(den or 1)
    size = (v.get("width"), v.get("height"))
    return [
        _check(
            "master.codec",
            f"{v.get('codec_name')} {v.get('profile')}",
            "prores HQ",
            v.get("codec_name") == "prores" and "HQ" in str(v.get("profile")),
        ),
        _check("master.pixels", v.get("pix_fmt"), "yuv422p10le", v.get("pix_fmt") == "yuv422p10le"),
        _check("master.size", f"{size[0]}x{size[1]}", "HD or 4K", size in MASTER_SIZES),
        _check(
            "master.color", "/".join(map(str, sorted(tags, key=str))), "bt709", tags == {"bt709"}
        ),
        _check("master.frame_rate", round(fps, 3), f"{target_fps:g}", abs(fps - target_fps) < 0.01),
        _check("master.atoms", "fiel colr", "present", all(a in head for a in (b"fiel", b"colr"))),
    ]


def _scan_held_frames(path: Path) -> tuple[float, float, float]:
    """First level, last level, and held share, one frame at a time: a film has to fit in memory."""
    first = last = 0.0
    previous: Arr | None = None
    held = lit = 0
    for frame in mediascan.iter_gray(path, width=480):
        level = float(frame.mean())
        if previous is None:
            first = level
        else:
            moved = float(np.abs(frame.astype(np.int16) - previous.astype(np.int16)).mean())
            if level > BLACK_LEVEL:
                lit += 1
                held += moved < DUPLICATE_LEVEL
        last, previous = level, frame
    return first, last, held / lit if lit else 0.0


def _master_picture(path: Path) -> list[dict[str, Any]]:
    first, last, held = _scan_held_frames(path)
    limit = float(limits()["duplicate_share_max"])
    return [
        _check(
            "master.black_head_tail",
            f"{first:.1f}/{last:.1f}",
            f"< {BLACK_LEVEL:g}",
            first < BLACK_LEVEL and last < BLACK_LEVEL,
        ),
        _check("master.duplicate_frames", round(held, 4), f"<= {limit:g}", held <= limit),
    ]


def _master_sound(path: Path) -> list[dict[str, Any]]:
    a = media.stream_info(path, "audio")
    if not a:
        return [_check("master.audio", None, "LPCM stereo", False)]
    loud = media.loudness(path)
    lkfs, peak = loud["integrated_lufs"], loud["true_peak_dbtp"]
    max_lkfs = float(limits()["master_integrated_lkfs_max"])
    max_peak = float(limits()["master_true_peak_dbtp_max"])
    return [
        _check(
            "master.audio",
            f"{a.get('codec_name')} {a.get('sample_rate')} {a.get('channels')}ch",
            "pcm_s24le 48000 2ch",
            a.get("codec_name") == "pcm_s24le"
            and a.get("sample_rate") == "48000"
            and a.get("channels") == 2,
        ),
        _check("master.lkfs", lkfs, f"<= {max_lkfs:g}", lkfs is not None and lkfs <= max_lkfs),
        _check("master.true_peak", peak, f"<= {max_peak:g}", peak is not None and peak <= max_peak),
    ]


def measure_master(path: Path, *, target_fps: float) -> list[dict[str, Any]]:
    """The delivery file against a premium platform's published ingest requirements."""
    return [*_master_video(path, target_fps), *_master_picture(path), *_master_sound(path)]
