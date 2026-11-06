"""Zero-cost local providers. They need no network and no keys.

They exist so the whole pipeline runs anywhere (CI, offline, a fresh box) and so
remote outages degrade quality instead of stopping the line. They are not the
quality bar: the studio config prefers remote providers whenever keys exist.
"""

from __future__ import annotations

import hashlib
import math
import random
import re
import tempfile
from pathlib import Path

from .. import media
from .base import Provider, Result, register

FONT_DIRS = [Path(__file__).resolve().parents[3] / "fonts"]


def find_font(*names: str) -> str | None:
    for d in FONT_DIRS:
        for n in names:
            p = d / n
            if p.exists():
                return str(p)
    return None


def estimate_words(text: str, total: float, offset: float = 0.0) -> list[dict]:
    """Spread words over a clip by character weight. Marked low confidence."""
    words = re.findall(r"\S+", text)
    if not words or total <= 0:
        return []
    lead, tail = min(0.08, total * 0.05), min(0.12, total * 0.05)
    span = max(total - lead - tail, 0.01)
    weights = [
        len(re.sub(r"\W", "", w)) + 2 + (3 if re.search(r"[.,!?;:]$", w) else 0) for w in words
    ]
    scale = span / sum(weights)
    t = offset + lead
    out = []
    for w, wt in zip(words, weights):
        d = wt * scale
        out.append(
            {
                "start_sec": round(t, 3),
                "end_sec": round(t + d * 0.92, 3),
                "text": w,
                "confidence": 0.5,
            }
        )
        t += d
    return out


@register
class LocalProvider(Provider):
    name = "local"
    capabilities = ("voice", "image", "music", "sfx")
    env_key = None
    synthetic = True
    free = True
    placeholder = True

    def reference_support(self, capability: str, model: str) -> dict:
        """Takes and ignores references, so the line can be tested. approve refuses its output."""
        return {"max_images": 99, "max_characters": 99} if capability == "image" else {}

    # flite voices bundled with ffmpeg's libflite
    VOICES = ("slt", "awb", "rms", "kal16", "kal")

    def voice(self, text: str, dst: Path, *, voice: str | None = None, **kw) -> Result:
        if not media.has_filter("flite"):  # many ffmpeg builds ship without it
            return self._murmur(text, dst)
        v = voice if voice in self.VOICES else "slt"
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
            fh.write(text)
            txt = fh.name
        raw = dst.with_suffix(".raw.wav")
        media.run(["-f", "lavfi", "-i", f"flite=textfile={txt}:voice={v}", str(raw)])
        # flite is 8/16k mono and a little slow; lift pace slightly, resample, gentle EQ.
        media.run(
            [
                "-i",
                str(raw),
                "-af",
                "atempo=1.08,highpass=f=80,acompressor=threshold=-18dB:ratio=3:attack=5:release=80,aresample=48000",
                "-ac",
                "1",
                str(dst),
            ]
        )
        raw.unlink(missing_ok=True)
        dur = media.duration(dst)
        return Result(
            path=dst,
            model=f"flite-{v}",
            words=estimate_words(text, dur),
            meta={"duration_sec": dur},
        )

    def _murmur(self, text: str, dst: Path) -> Result:
        """Syllable-paced tone at speech length, for an ffmpeg with no flite. Timing stays testable."""
        dur = max(len(re.findall(r"\S+", text)) / 2.6, 0.5)
        media.run(
            [
                "-f",
                "lavfi",
                "-i",
                f"aevalsrc='0.25*sin(2*PI*180*t)*(0.55+0.45*sin(2*PI*4.5*t))':s=48000:d={dur:.3f}",
                "-ac",
                "1",
                str(dst),
            ]
        )
        return Result(
            path=dst, model="flite-absent", words=estimate_words(text, dur), meta={"duration_sec": dur}
        )

    def image(
        self,
        prompt: str,
        dst: Path,
        *,
        width: int,
        height: int,
        title: str = "",
        palette: int | None = None,
        **kw,
    ) -> Result:
        if kw.get("style", "studio") == "studio":
            return self._studio_field(prompt, dst, width=width, height=height, palette=palette)
        return self._typecard(prompt, dst, width=width, height=height, title=title, palette=palette)

    # Studio palettes: (base, light A, light B). Deep near-black base, two luminous fields.
    STUDIO = {
        "blue": ((4, 6, 14), (40, 110, 255), (120, 200, 255)),
        "sunset": ((10, 4, 4), (255, 90, 40), (255, 170, 80)),
        "spectrum": ((6, 6, 10), (120, 90, 255), (60, 210, 200)),
        "dusk": ((6, 4, 14), (120, 70, 220), (240, 110, 170)),
        "green": ((3, 10, 7), (40, 200, 140), (180, 240, 120)),
        "silver": ((8, 8, 10), (150, 160, 180), (230, 232, 240)),
        "red": ((12, 3, 4), (230, 40, 60), (255, 120, 90)),
    }
    CUES = [
        ("sunset", "sunset sunrise orange warm red-orange dawn fire golden"),
        ("red", "red crimson danger alert"),
        ("dusk", "dusk night purple violet calm evening dream"),
        ("blue", "blue sky noon ocean water cool air atmosphere"),
        ("green", "green nature growth plant forest money"),
        ("spectrum", "prism light white color rainbow spectrum split"),
        ("silver", "metal steel silver data tech minimal"),
    ]

    def _palette_for(self, prompt: str, palette: int | None) -> str:
        low = prompt.lower()
        hits = [(low.find(w), name) for name, words in self.CUES for w in words.split() if w in low]
        if hits:
            return min(hits)[1]
        names = list(self.STUDIO)
        return names[
            (palette or int(hashlib.sha1(prompt.encode()).hexdigest()[:6], 16)) % len(names)
        ]

    def _studio_field(
        self, prompt: str, dst: Path, *, width: int, height: int, palette: int | None
    ) -> Result:
        """Keynote-style background: near-black, two soft luminous fields, gentle vignette, dithered."""
        import numpy as np
        from PIL import Image

        name = self._palette_for(prompt, palette)
        base, ca, cb = (np.array(c, dtype=np.float32) / 255 for c in self.STUDIO[name])
        rnd = random.Random(int(hashlib.sha1(prompt.encode()).hexdigest()[:8], 16))
        w, h = width // 2, height // 2  # render at half size; the smooth field upsamples cleanly
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        x /= w
        y /= h
        img = np.broadcast_to(base, (h, w, 3)).copy()

        def field(cx, cy, rx, ry, color, strength):
            d = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
            return np.exp(-d)[..., None] * color * strength

        # 1. a low, wide pool of light; 2. a smaller offset glow; 3. one flowing ribbon. Black does the rest.
        img += field(rnd.uniform(0.35, 0.65), rnd.uniform(1.02, 1.1), 0.9, 0.24, ca, 0.85)
        img += field(rnd.uniform(0.2, 0.8), rnd.uniform(0.86, 0.92), 0.35, 0.10, cb, 0.35)
        phase, amp, yc = rnd.uniform(0, 6.28), rnd.uniform(0.03, 0.06), rnd.uniform(0.80, 0.86)
        curve = yc + amp * np.sin(x * rnd.uniform(3.0, 5.0) + phase) + 0.10 * (x - 0.5) ** 2
        dist = np.abs(y - curve)
        ribbon = (
            np.exp(-((dist / 0.006) ** 2)) * 0.9 + np.exp(-((dist / 0.03) ** 2)) * 0.35
        )  # bright core + soft bloom
        fade = np.exp(-(((x - 0.5) / 0.55) ** 4))  # ribbon dissolves toward the edges
        img += (ribbon * fade)[..., None] * (0.55 * ca + 0.45 * cb + 0.25)
        vign = 1 - 0.6 * (((x - 0.5) / 0.8) ** 2 + ((y - 0.55) / 0.85) ** 2)
        img *= np.clip(vign, 0.25, 1)[..., None]
        # roll off highlights by luminance only, so hues stay saturated
        lum = img.max(axis=2, keepdims=True)
        img *= np.where(
            lum > 0.85, (0.85 + 0.15 * np.tanh((lum - 0.85) / 0.15)) / np.maximum(lum, 1e-6), 1.0
        )
        img += np.random.default_rng(1).uniform(
            -1.5 / 255, 1.5 / 255, img.shape
        )  # dither against banding
        out = Image.fromarray((np.clip(img, 0, 1) * 255).astype(np.uint8)).resize(
            (width, height), Image.LANCZOS
        )
        out.save(dst)
        return Result(path=dst, model="local-studio-field", meta={"palette": name})

    def _typecard(
        self,
        prompt: str,
        dst: Path,
        *,
        width: int,
        height: int,
        title: str = "",
        palette: int | None = None,
    ) -> Result:
        """Bold style: a designed typographic card with a baked headline."""
        from PIL import Image, ImageDraw, ImageFilter, ImageFont

        seed = int(hashlib.sha1(prompt.encode()).hexdigest()[:8], 16)
        rnd = random.Random(seed)
        palettes = [
            ((12, 14, 38), (88, 40, 170), (255, 196, 61)),
            ((6, 30, 41), (0, 128, 128), (255, 107, 107)),
            ((24, 8, 18), (180, 40, 80), (255, 230, 140)),
            ((10, 22, 14), (40, 120, 70), (230, 255, 150)),
            ((18, 18, 18), (70, 70, 90), (120, 220, 255)),
        ]
        a, b, accent = palettes[(palette if palette is not None else seed) % len(palettes)]
        img = Image.new("RGB", (width, height))
        px = img.load()
        ang = rnd.uniform(0, math.pi)
        ca, sa = math.cos(ang), math.sin(ang)
        diag = abs(width * ca) + abs(height * sa)
        for y in range(0, height, 2):
            for x in range(0, width, 2):
                t = ((x - width / 2) * ca + (y - height / 2) * sa) / diag + 0.5
                t = min(max(t, 0), 1)
                c = tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))
                px[x, y] = c
                if x + 1 < width:
                    px[x + 1, y] = c
                if y + 1 < height:
                    px[x, y + 1] = c
                    if x + 1 < width:
                        px[x + 1, y + 1] = c
        draw = ImageDraw.Draw(img, "RGBA")
        for _ in range(7):
            r = rnd.randint(width // 8, width // 2)
            cx, cy = rnd.randint(-r // 2, width), rnd.randint(-r // 2, height)
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*accent, rnd.randint(14, 36)))
        for _ in range(4):
            y0 = rnd.randint(0, height)
            draw.rectangle([0, y0, width, y0 + rnd.randint(2, 6)], fill=(*accent, 50))
        img = img.filter(ImageFilter.GaussianBlur(radius=2))
        draw = ImageDraw.Draw(img, "RGBA")
        headline = (title or prompt).strip()
        font_path = find_font("InterDisplay-SemiBold.ttf")
        size = int(width * 0.11)
        lines: list[str] = []
        while size > 24:
            font = ImageFont.truetype(font_path, size) if font_path else ImageFont.load_default()
            lines, cur = [], ""
            for word in headline.upper().split():
                trial = f"{cur} {word}".strip()
                if draw.textlength(trial, font=font) <= width * 0.82:
                    cur = trial
                else:
                    if cur:
                        lines.append(cur)
                    cur = word
            if cur:
                lines.append(cur)
            if len(lines) <= 4:
                break
            size = int(size * 0.88)
        line_h = int(size * 1.12)
        y = int(height * 0.30) - line_h * len(lines) // 2
        for i, line in enumerate(lines):
            w = draw.textlength(line, font=font)
            x = (width - w) / 2
            fill = accent if i == 0 else (255, 255, 255)
            draw.text((x + 6, y + 6), line, font=font, fill=(0, 0, 0, 120))
            draw.text((x, y), line, font=font, fill=fill)
            y += line_h
        noise = Image.effect_noise((width, height), 18).convert("L")
        img = Image.composite(
            img, Image.new("RGB", (width, height), (0, 0, 0)), noise.point(lambda v: 255 - v // 10)
        )
        img.save(dst, quality=92)
        return Result(path=dst, model="local-typecard", meta={"seed": seed})

    def music(self, prompt: str, dst: Path, *, duration: float, **kw) -> Result:
        """Ambient pad: a slow chord progression with tremolo and a soft pulse."""
        prog = [
            (220.0, 261.63, 329.63),
            (196.0, 246.94, 293.66),
            (174.61, 220.0, 261.63),
            (196.0, 246.94, 329.63),
        ]
        bar = 4.0
        terms = []
        for i, chord in enumerate(prog):
            gate = f"(gte(mod(t,{bar * len(prog)}),{i * bar})*lt(mod(t,{bar * len(prog)}),{(i + 1) * bar}))"
            voices = "+".join(f"sin(2*PI*{f}*t)+0.3*sin(2*PI*{f * 2}*t)" for f in chord)
            terms.append(f"{gate}*({voices})")
        expr = f"0.05*({'+'.join(terms)})*(0.75+0.25*sin(2*PI*0.25*t))+0.04*sin(2*PI*55*t)*exp(-6*mod(t,0.5))"
        media.run(
            [
                "-f",
                "lavfi",
                "-i",
                f"aevalsrc='{expr}':s=48000:d={duration:.2f}",
                "-af",
                f"lowpass=f=2400,afade=t=in:d=1.5,afade=t=out:st={max(duration - 2, 0):.2f}:d=2,aecho=0.6:0.5:120:0.25",
                "-ac",
                "2",
                str(dst),
            ]
        )
        return Result(path=dst, model="local-pad", meta={"duration_sec": duration})

    def sfx(self, prompt: str, dst: Path, *, duration: float = 0.6, **kw) -> Result:
        """A whoosh: filtered noise with a fast swell."""
        media.run(
            [
                "-f",
                "lavfi",
                "-i",
                f"anoisesrc=d={duration}:c=pink:a=0.6",
                "-af",
                f"bandpass=f=1800:w=1200,afade=t=in:d={duration * 0.6:.2f},afade=t=out:st={duration * 0.6:.2f}:d={duration * 0.4:.2f}",
                "-ar",
                "48000",
                "-ac",
                "2",
                str(dst),
            ]
        )
        return Result(path=dst, model="local-whoosh", meta={"duration_sec": duration})
