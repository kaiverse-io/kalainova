"""Synthetic footage with known properties, for testing the editing arm without real media.

landscape(): a procedural layered-mountain scene with sun and haze (deterministic by seed).
clip(): turns a scene into a short video with a pan, optional handheld shake, blur, or under-exposure.
talk(): an audio-bearing clip with speech-like bursts separated by silences (for dead-air removal).
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from kalainova import media


def landscape(seed: int, w: int = 1280, h: int = 720) -> Image.Image:
    rng = np.random.default_rng(seed)
    y = np.linspace(0, 1, h)[:, None]
    top = np.array(rng.choice([[40, 90, 170], [250, 140, 80], [90, 60, 140], [70, 140, 200]]), np.float32)
    bottom = np.array([250, 215, 170], np.float32)
    sky = top + (bottom - top) * y ** 0.7
    img = np.broadcast_to(sky[:, None, :], (h, w, 3)).copy()
    sx, sy = rng.uniform(0.2, 0.8) * w, rng.uniform(0.25, 0.45) * h
    yy, xx = np.mgrid[0:h, 0:w]
    sun = np.exp(-(((xx - sx) ** 2 + (yy - sy) ** 2) / (2 * (0.05 * w) ** 2)))
    img += sun[..., None] * np.array([255, 240, 200]) * 0.9
    for layer in range(4):
        base = 0.45 + layer * 0.12
        xs = np.arange(w)
        ridge = base * h + sum(rng.uniform(10, 60) * np.sin(xs / rng.uniform(40, 220) + rng.uniform(0, 6)) for _ in range(4))
        shade = np.array([30, 45, 70]) * (1 - layer * 0.18) + layer * 18
        haze = 0.55 - layer * 0.15
        mask = yy > ridge[None, :]
        tex = rng.normal(0, 6, (h, w))[..., None]
        img = np.where(mask[..., None], shade * (1 - haze) + img * haze + tex, img)
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


def clip(dst: Path, seed: int, *, dur: float = 4.0, shake: float = 0.0, blur: float = 0.0, dark: float = 1.0,
         fps: int = 24, size=(640, 360)) -> Path:
    scene = landscape(seed, int(size[0] * 1.4), int(size[1] * 1.4))
    if blur:
        scene = scene.filter(ImageFilter.GaussianBlur(blur))
    still = dst.with_suffix(".scene.png")
    scene.save(still)
    n = int(dur * fps)
    W, H = size
    sw, sh = scene.size
    rng = np.random.default_rng(seed + 99)
    jx = np.cumsum(rng.normal(0, shake, n)) if shake else np.zeros(n)
    jy = np.cumsum(rng.normal(0, shake, n)) if shake else np.zeros(n)
    frames_dir = dst.with_suffix("")
    frames_dir.mkdir(exist_ok=True)
    arr = np.asarray(scene, np.float32)
    for i in range(n):
        t = i / max(n - 1, 1)
        x = int((sw - W) * (0.15 + 0.7 * t) + jx[i]) % max(sw - W, 1)
        y = int((sh - H) * 0.5 + jy[i]) % max(sh - H, 1)
        f = arr[y:y + H, x:x + W] * dark
        Image.fromarray(np.clip(f, 0, 255).astype(np.uint8)).save(frames_dir / f"{i:04d}.png")
    media.run(["-framerate", str(fps), "-i", str(frames_dir / "%04d.png"), "-f", "lavfi", "-i",
               f"anoisesrc=d={dur}:c=pink:a=0.02", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", "-c:a", "aac", str(dst)])
    for f in frames_dir.iterdir():
        f.unlink()
    frames_dir.rmdir()
    still.unlink()
    return dst


def talk(dst: Path, segments: list[tuple[float, bool]], size=(640, 360)) -> Path:
    """segments: (seconds, speaking?). Speech is a modulated voice-band tone; silence is a low room tone."""
    expr_parts, t = [], 0.0
    for dur, speaking in segments:
        if speaking:
            expr_parts.append(f"between(t,{t:.2f},{t + dur:.2f})*0.3*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*4*t))")
        t += dur
    expr = "+".join(expr_parts) + "+0.002*sin(2*PI*50*t)"
    media.run(["-f", "lavfi", "-i", f"testsrc2=s={size[0]}x{size[1]}:r=24:d={t:.2f}",
               "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={t:.2f}",
               "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(dst)])
    return dst


def travel_set(folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    specs = [
        ("01_good_wide.mp4", 1, {}),
        ("02_shaky.mp4", 2, {"shake": 6.0}),
        ("03_blurry.mp4", 3, {"blur": 6.0}),
        ("04_dark.mp4", 4, {"dark": 0.25}),
        ("05_good_sunset.mp4", 5, {}),
        ("06_good_ridge.mp4", 6, {"dur": 6.0}),
    ]
    out = [clip(folder / name, seed, **kw) for name, seed, kw in specs]
    photo = folder / "07_photo.jpg"
    landscape(7, 1600, 1066).save(photo, quality=92)
    out.append(photo)
    return out
