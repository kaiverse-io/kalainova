"""The delivered files: the web file, the master a platform ingests, and a thumbnail."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import media
from . import cover
from .spec import safe_path


def _fades(a: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Video and audio fades. The picture goes black before its last frame, so a master ends so."""
    vf: list[str] = []
    af: list[str] = []
    total, fps = a.get("duration_sec") or 0, a.get("fps") or 30
    fin, fout = a.get("fade_in_sec") or 0, a.get("fade_out_sec") or 0
    if fin:
        vf.append(f"fade=t=in:st=0:d={fin:.3f}")
        af.append(f"afade=t=in:d={fin:.3f}")
    if fout and total > fout:
        vf.append(f"fade=t=out:st={total - fout:.3f}:d={fout - 1.5 / fps:.3f}")
        af.append(f"afade=t=out:st={total - fout:.3f}:d={fout:.3f}")
    return vf, af


def _write_master(work: Path, a: dict[str, Any], vf: list[str], af: list[str], note: str) -> None:
    """A ProRes 422 HQ master with LPCM stereo: the file a premium platform ingests."""
    args = ["-i", str(safe_path(work, a["video"]))]
    if a.get("audio"):
        args += ["-i", str(safe_path(work, a["audio"])), "-map", "0:v", "-map", "1:a"]
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
            str(safe_path(work, a["master"])),
        ]
    )


def _sound_args(work: Path, a: dict[str, Any], af: list[str]) -> list[str]:
    if not a.get("audio"):
        return []
    args = [
        "-i",
        str(safe_path(work, a["audio"])),
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
    return [*args, "-af", ",".join(af)] if af else args


def _write_web_file(work: Path, a: dict[str, Any], vf: list[str], af: list[str], note: str) -> Path:
    out = safe_path(work, a["out"])
    media.run(
        [
            "-i",
            str(safe_path(work, a["video"])),
            *_sound_args(work, a, af),
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
    )
    return out


def _write_thumbnail(work: Path, out: Path, a: dict[str, Any]) -> None:
    """The cover: the sharpest clean frame, or the time or file the brief names."""
    given = a.get("cover_file")
    cover.write(
        out,
        safe_path(work, a["thumbnail"]),
        safe_path(work, a["thumbnail_square"]) if a.get("thumbnail_square") else None,
        duration=a.get("duration_sec") or 0.0,
        edge_sec=max(a.get("fade_in_sec") or 0.0, a.get("fade_out_sec") or 0.0),
        at=a.get("cover_at_sec"),
        file=safe_path(work, given) if given else None,
    )


def _write_audio_only(work: Path, a: dict[str, Any]) -> None:
    source = str(safe_path(work, a["audio"]))
    media.run(["-i", source, "-c:a", "aac", "-b:a", "256k", str(safe_path(work, a["audio_only"]))])


def op_export(work: Path, a: dict[str, Any]) -> None:
    vf, af = _fades(a)
    synthetic = a.get("synthetic", True)
    note = (
        "Made with Kalainova; contains AI-generated media" if synthetic else "Edited with Kalainova"
    )
    out = _write_web_file(work, a, vf, af, note)
    if a.get("master"):
        _write_master(work, a, vf, af, note)
    if a.get("thumbnail"):
        _write_thumbnail(work, out, a)
    if a.get("audio_only") and a.get("audio"):
        _write_audio_only(work, a)
