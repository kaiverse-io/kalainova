"""INGEST. Split the operator's media into shots and score every shot.

All analysis decodes small frames straight from ffmpeg into numpy; nothing leaves the machine.
Per shot we keep a 4 fps time series so the director can pick the best window inside a shot,
not just the best shot.

Scores (0..1 unless noted):
  sharpness   variance of the Laplacian, normalised across the batch
  exposure    1 at mid-grey, falling toward crushed blacks or clipped whites
  colorfulness Hasler-Süsstrunk metric, normalised
  motion      mean absolute frame difference (subject or camera movement)
  shake       high-frequency jitter of global translation (phase correlation); low is steady
  subject_x   horizontal centre of visual interest, for 9:16 reframing
  speech      fraction of the shot with voice-band energy above the noise floor
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np

from .. import media

VIDEO = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".mts"}
IMAGE = {".jpg", ".jpeg", ".png", ".heic", ".webp", ".tif", ".tiff"}
AW, AH, AFPS = 160, 90, 4  # analysis frame size and rate


def scenes(path: Path, threshold: float = 0.32) -> list[float]:
    """Cut points (seconds) where the picture changes."""
    proc = subprocess.run(
        [
            media.FFMPEG,
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
    cuts = []
    for line in proc.stderr.splitlines():
        if "pts_time:" in line and "showinfo" in line:
            try:
                cuts.append(float(line.split("pts_time:")[1].split()[0]))
            except (IndexError, ValueError):
                pass
    return cuts


def frames(
    path: Path, start: float, dur: float, w: int = AW, h: int = AH, fps: float = AFPS
) -> np.ndarray:
    """RGB frames as float32 [n, h, w, 3] in 0..1."""
    proc = subprocess.run(
        [
            media.FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{dur:.3f}",
            "-i",
            str(path),
            "-vf",
            f"fps={fps},scale={w}:{h}:force_original_aspect_ratio=disable",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-",
        ],
        capture_output=True,
    )
    buf = np.frombuffer(proc.stdout, dtype=np.uint8)
    n = buf.size // (w * h * 3)
    return (
        buf[: n * w * h * 3].reshape(n, h, w, 3).astype(np.float32) / 255
        if n
        else np.zeros((0, h, w, 3), np.float32)
    )


def audio_rms(path: Path, start: float, dur: float, sr: int = 8000) -> np.ndarray:
    """Voice-band (300-3400 Hz) RMS per 0.25 s window."""
    proc = subprocess.run(
        [
            media.FFMPEG,
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{dur:.3f}",
            "-i",
            str(path),
            "-vn",
            "-af",
            "highpass=f=300,lowpass=f=3400",
            "-ac",
            "1",
            "-ar",
            str(sr),
            "-f",
            "s16le",
            "-",
        ],
        capture_output=True,
    )
    x = np.frombuffer(proc.stdout, dtype=np.int16).astype(np.float32) / 32768
    win = sr // 4
    if x.size < win:
        return np.zeros(0, np.float32)
    x = x[: x.size // win * win].reshape(-1, win)
    return np.sqrt((x**2).mean(axis=1))


def _gray(f: np.ndarray) -> np.ndarray:
    return f @ np.array([0.299, 0.587, 0.114], np.float32)


def _laplacian_var(g: np.ndarray) -> float:
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def _shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Global translation between two gray frames by phase correlation."""
    fa, fb = np.fft.fft2(a - a.mean()), np.fft.fft2(b - b.mean())
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-9
    c = np.abs(np.fft.ifft2(r))
    dy, dx = np.unravel_index(np.argmax(c), c.shape)
    h, w = a.shape
    return (dx - w if dx > w // 2 else dx), (dy - h if dy > h // 2 else dy)


def _colorfulness(f: np.ndarray) -> float:
    r, g, b = f[..., 0], f[..., 1], f[..., 2]
    rg, yb = r - g, 0.5 * (r + g) - b
    return float(np.hypot(rg.std(), yb.std()) + 0.3 * np.hypot(rg.mean(), yb.mean()))


def _subject_x(fs: np.ndarray) -> float:
    """Centre of gradient energy across columns, biased gently to the middle."""
    g = _gray(fs).mean(axis=0)
    gx = np.abs(np.diff(g, axis=1)).sum(axis=0) + np.abs(np.diff(g, axis=0))[:, :-1].sum(axis=0)
    cols = np.convolve(gx, np.ones(9) / 9, mode="same")
    xs = np.linspace(0, 1, cols.size)
    weight = cols * (1 - 0.35 * np.abs(xs - 0.5) * 2)
    return float((xs * weight).sum() / (weight.sum() + 1e-9))


def score_series(fs: np.ndarray) -> dict:
    """Per-frame series for one shot."""
    if len(fs) == 0:
        return {"sharp": [], "lum": [], "motion": [], "shift": []}
    gray = _gray(fs)
    sharp = [_laplacian_var(g) for g in gray]
    lum = gray.reshape(len(gray), -1).mean(axis=1).tolist()
    motion = [0.0] + [float(np.abs(gray[i] - gray[i - 1]).mean()) for i in range(1, len(gray))]
    shifts = [(0.0, 0.0)] + [_shift(gray[i - 1], gray[i]) for i in range(1, len(gray))]
    return {
        "sharp": sharp,
        "lum": lum,
        "motion": motion,
        "shift": [list(map(float, s)) for s in shifts],
    }


def jitter(shifts: list[list[float]]) -> float:
    """Shake = energy in the second difference of camera path (smooth pans score low)."""
    if len(shifts) < 4:
        return 0.0
    p = np.cumsum(np.array(shifts), axis=0)
    acc = np.diff(p, n=2, axis=0)
    return float(np.sqrt((acc**2).sum(axis=1)).mean())


def _norm(vals: list[float]) -> list[float]:
    a = np.array(vals, np.float64)
    if a.size == 0:
        return []
    lo, hi = np.percentile(a, 5), np.percentile(a, 95)
    return np.clip((a - lo) / (hi - lo + 1e-9), 0, 1).round(3).tolist()


def ingest(job, inputs: list[Path], *, min_shot: float = 1.2, max_shot: float = 12.0) -> dict:
    """Copy inputs into the work dir, split into shots, score, write footage.json."""
    src_dir = job.work / "src"
    thumbs = job.work / "thumbs"
    src_dir.mkdir(exist_ok=True)
    thumbs.mkdir(exist_ok=True)
    shots: list[dict] = []
    sources: list[dict] = []
    for n, path in enumerate(sorted(inputs)):
        ext = path.suffix.lower()
        if ext not in VIDEO | IMAGE:
            continue
        dst = src_dir / f"{n:03d}{ext}"
        if not dst.exists():
            shutil.copy2(path, dst)
        rel = f"src/{dst.name}"
        if ext in IMAGE:
            info = media.summarize(dst)
            sources.append(
                {"id": f"s{n:03d}", "path": rel, "kind": "still", "name": path.name, **info}
            )
            fs = frames(dst, 0, 1, fps=1)
            shots.append(
                {
                    "id": f"s{n:03d}.0",
                    "source": f"s{n:03d}",
                    "kind": "still",
                    "in_sec": 0,
                    "out_sec": 0,
                    "series": score_series(fs[:1]),
                    "colorfulness": _colorfulness(fs[0]) if len(fs) else 0,
                    "subject_x": _subject_x(fs[:1]) if len(fs) else 0.5,
                    "speech": 0.0,
                    "aspect": (info.get("width", 1) / max(info.get("height", 1), 1)),
                }
            )
            continue
        dur = media.duration(dst)
        info = media.summarize(dst)
        has_audio = "sample_rate_hz" in info
        sources.append(
            {
                "id": f"s{n:03d}",
                "path": rel,
                "kind": "video",
                "name": path.name,
                "duration_sec": dur,
                "has_audio": has_audio,
                **info,
            }
        )
        cuts = [0.0] + [c for c in scenes(dst) if 0.3 < c < dur - 0.3] + [dur]
        # merge too-short shots, split too-long ones
        spans: list[tuple[float, float]] = []
        for a, b in zip(cuts, cuts[1:]):
            if spans and b - a < min_shot:
                spans[-1] = (spans[-1][0], b)
                continue
            while b - a > max_shot:
                spans.append((a, a + max_shot))
                a += max_shot
            spans.append((a, b))
        if (
            len(spans) > 1 and spans[0][1] - spans[0][0] < min_shot
        ):  # a short first fragment joins the next shot
            spans[1] = (spans[0][0], spans[1][1])
            spans.pop(0)
        for k, (a, b) in enumerate(spans):
            fs = frames(dst, a, b - a)
            series = score_series(fs)
            rms = audio_rms(dst, a, b - a) if has_audio else np.zeros(0)
            floor = np.percentile(rms, 20) if rms.size else 0
            speech = float((rms > max(floor * 3, 0.01)).mean()) if rms.size else 0.0
            shots.append(
                {
                    "id": f"s{n:03d}.{k}",
                    "source": f"s{n:03d}",
                    "kind": "video",
                    "in_sec": round(a, 3),
                    "out_sec": round(b, 3),
                    "series": series,
                    "colorfulness": float(
                        np.mean([_colorfulness(f) for f in fs[:: max(len(fs) // 6, 1)]])
                    )
                    if len(fs)
                    else 0,
                    "subject_x": _subject_x(fs) if len(fs) else 0.5,
                    "speech": round(speech, 3),
                    "jitter_px": round(jitter(series["shift"]), 3),
                    "aspect": info.get("width", 16) / max(info.get("height", 9), 1),
                }
            )

    # batch-normalised scores
    # stills are full-resolution photos: rank them among stills, not against video frames
    vids = [s for s in shots if s["kind"] == "video"]
    stills = [s for s in shots if s["kind"] == "still"]
    sharp_map, color_map = {}, {}
    for group in (vids, stills):
        sh = _norm(
            [float(np.median(s["series"]["sharp"])) if s["series"]["sharp"] else 0 for s in group]
        )
        co = _norm([s["colorfulness"] for s in group])
        if len(group) == 1:  # a lone item has nothing to be ranked against
            sh, co = [0.7], [0.7]
        for s, a_, b_ in zip(group, sh, co):
            sharp_map[s["id"]], color_map[s["id"]] = a_, b_
    sharp = [sharp_map[s["id"]] for s in shots]
    color = [color_map[s["id"]] for s in shots]
    motion = _norm(
        [float(np.mean(s["series"]["motion"])) if s["series"]["motion"] else 0 for s in shots]
    )
    shake = _norm([jitter(s["series"]["shift"]) for s in shots])
    for s, sh, co, mo, sk in zip(shots, sharp, color, motion, shake):
        lum = float(np.mean(s["series"]["lum"])) if s["series"]["lum"] else 0.5
        exposure = float(np.clip(1 - abs(lum - 0.48) / 0.48, 0, 1))
        s["scores"] = {
            "sharpness": sh,
            "exposure": round(exposure, 3),
            "colorfulness": co,
            "motion": mo,
            "shake": sk if s["kind"] == "video" else 0.0,
            "speech": s.pop("speech"),
        }
        s["subject_x"] = round(s["subject_x"], 3)
        s["colorfulness"] = round(s["colorfulness"], 4)
        s["quality"] = round(
            0.34 * sh
            + 0.22 * s["scores"]["exposure"]
            + 0.18 * co
            + 0.10 * mo
            - 0.26 * s["scores"]["shake"]
            + 0.2,
            3,
        )
        mid = s["in_sec"] + (s["out_sec"] - s["in_sec"]) / 2
        src = next(x for x in sources if x["id"] == s["source"])
        thumb = thumbs / f"{s['id']}.jpg"
        try:
            media.run(
                [
                    "-ss",
                    f"{mid:.3f}",
                    "-i",
                    str(job.work / src["path"]),
                    "-frames:v",
                    "1",
                    "-vf",
                    "scale=320:-2",
                    str(thumb),
                ]
            )
            s["thumb"] = f"thumbs/{thumb.name}"
        except media.MediaError:
            pass
    footage = {"schema_version": "0.1", "job_id": job.id, "sources": sources, "shots": shots}
    (job.folder / "footage.json").write_text(json.dumps(footage, indent=1) + "\n")
    return footage


def best_window(
    shot: dict, length: float, lo: float | None = None, hi: float | None = None
) -> tuple[float, float]:
    """The steadiest, sharpest window of `length` seconds inside a shot, optionally inside [lo, hi]."""
    a0 = shot["in_sec"]
    a, b = (lo if lo is not None else a0), (hi if hi is not None else shot["out_sec"])
    if shot["kind"] == "still" or b - a <= length:
        return a, (b if shot["kind"] == "video" else a + length)
    sr = shot["series"]
    i0 = max(int(round((a - a0) * AFPS)), 0)
    i1 = min(int(round((b - a0) * AFPS)), len(sr["sharp"]))
    sr = {k: v[i0:i1] for k, v in sr.items()}
    n = len(sr["sharp"])
    k = max(int(length * AFPS), 1)
    if n <= k:
        return a, a + length
    sharp = np.array(sr["sharp"])
    sharp = sharp / (sharp.max() + 1e-9)
    shifts = np.array(sr["shift"])
    jit = np.zeros(n)
    if n > 2:
        acc = np.diff(np.cumsum(shifts, axis=0), n=2, axis=0)
        jit[2:] = np.sqrt((acc**2).sum(axis=1))
        jit /= jit.max() + 1e-9
    score = sharp - 0.8 * jit
    sums = np.convolve(score, np.ones(k), mode="valid")
    # avoid the first 0.25 s of a shot: handheld starts are rarely the moment
    sums[: min(1, len(sums) - 1)] -= 0.5
    i = int(np.argmax(sums))
    start = a + i / AFPS
    return round(start, 3), round(min(start + length, b), 3)
