"""ASS subtitle builders for libass: kinetic word captions, hook card, beat titles.

This is the ffmpeg-native caption renderer. A brief that asks for `captions: kinetic` is drawn by
the graphics provider instead (render/drawn.py), behind the same burn_captions op.
"""

from __future__ import annotations

from functools import lru_cache
from html import escape
from pathlib import Path

import numpy as np
from PIL import ImageFont

FONT = "Inter SemiBold"
FONTS = (
    Path(__file__).resolve().parents[2] / "fonts"
)  # vendored, so every machine sets the same type


def ts(sec: float) -> str:
    sec = max(sec, 0)
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def esc(text: str) -> str:
    # libass has no backslash escape: swap it for a look-alike so "\\N" and friends stay literal text
    return text.replace("\\", "\u29f5").replace("{", "(").replace("}", ")").replace("\n", " ")


def header(w: int, h: int) -> str:
    # libass sizes by line height (ascent+descent). These give ~70px caption caps on a 1080-wide frame.
    k = 1.56
    fs = int(w * 0.105 * k)
    hook = int(w * 0.12 * k)
    title = int(w * 0.06 * k)
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{FONT},{fs},&H00FFFFFF,&H0000D7FF,&H00101010,&H96000000,-1,0,0,0,100,100,0,0,1,{max(4, fs // 12)},3,5,60,60,0,1
Style: Hook,{FONT},{hook},&H00FFFFFF,&H0000D7FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{max(5, hook // 11)},4,5,70,70,0,1
Style: Title,{FONT},{title},&H0000D7FF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,2,0,1,{max(3, title // 12)},2,8,60,60,{int(h * 0.12)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


ACCENT = "&H0000D7FF&"  # BGR: golden yellow
WHITE = "&H00FFFFFF&"


def kinetic(captions: list[dict], w: int, h: int, y_frac: float = 0.64) -> str:
    """One event per spoken word: the card stays, the active word lights up and pops."""
    x, y = w // 2, int(h * y_frac)
    lines = [header(w, h)]
    for card in captions:
        words = card.get("words") or [
            {"text": card["text"], "start_sec": card["start_sec"], "end_sec": card["end_sec"]}
        ]
        emph = {e.lower() for e in card.get("emphasis", [])}
        for i, active in enumerate(words):
            start = active["start_sec"] if i else card["start_sec"]
            end = words[i + 1]["start_sec"] if i + 1 < len(words) else card["end_sec"]
            if end <= start:
                continue
            parts = []
            for j, wd in enumerate(words):
                t = esc(wd["text"].upper())
                if j == i:
                    parts.append(
                        f"{{\\c{ACCENT}\\t(0,90,\\fscx112\\fscy112)\\t(90,180,\\fscx100\\fscy100)}}{t}{{\\c{WHITE}}}"
                    )
                elif wd["text"].lower() in emph:
                    parts.append(f"{{\\c{ACCENT}}}{t}{{\\c{WHITE}}}")
                else:
                    parts.append(t)
            pop = "\\fscx86\\fscy86\\t(0,110,\\fscx100\\fscy100)" if i == 0 else ""
            lines.append(
                f"Dialogue: 2,{ts(start)},{ts(end)},Caption,,0,0,0,,{{\\pos({x},{y}){pop}\\blur0.6}}{' '.join(parts)}"
            )
    return "\n".join(lines) + "\n"


def overlay_events(overlays: list[dict], titles: list[dict], w: int, h: int) -> str:
    """Hook card (full-screen scrim + slam-in text) and per-beat titles."""
    lines = [header(w, h)]
    for ov in overlays:
        if ov["kind"] != "hook_card":
            continue
        s, e = ov["start_sec"], ov["end_sec"]
        dur_ms = int((e - s) * 1000)
        scrim = f"m 0 0 l {w} 0 l {w} {h} l 0 {h}"
        lines.append(
            f"Dialogue: 0,{ts(s)},{ts(e)},Hook,,0,0,0,,{{\\pos(0,0)\\an7\\bord0\\shad0\\1c&H200514&\\1a&H30&"
            f"\\fad(0,220)\\p1}}{scrim}{{\\p0}}"
        )
        lines.append(
            f"Dialogue: 1,{ts(s)},{ts(e)},Hook,,0,0,0,,{{\\pos({w // 2},{int(h * 0.42)})\\fscx40\\fscy40"
            f"\\t(0,140,\\fscx108\\fscy108)\\t(140,240,\\fscx100\\fscy100)\\t({max(dur_ms - 240, 240)},{dur_ms},\\fscx70\\fscy70)"
            f"\\fad(0,220)}}{esc(ov['text'].upper())}"
        )
    for t in titles:
        lines.append(
            f"Dialogue: 1,{ts(t['start_sec'])},{ts(t['end_sec'])},Title,,0,0,0,,"
            f"{{\\fad(160,160)\\move({w // 2},{int(h * 0.10)},{w // 2},{int(h * 0.12)},0,260)}}{esc(t['text'].upper())}"
        )
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- studio theme
# Keynote restraint: Inter Display, sentence case, no outlines, a soft shadow, and eased fades with a
# short rise. Sizes follow the frame's shape, wrapping follows real font metrics, and everything stays
# inside the area each screen keeps clear of its own interface and overscan.
HEAD_FACE, CAP_FACE = "InterDisplay-SemiBold.ttf", "InterDisplay-Medium.ttf"
LIBASS_EM = (
    1.21  # libass sizes by ascent + descent, so one em of Inter is this much smaller than "size"
)
READABLE_CONTRAST = 4.5
SCRIM_TARGET_LEVEL = 0.45  # white on this grey level reaches readable contrast
INACTIVE_ALPHA = (
    "&H33&"  # the rest of a line stays readable, and only the spoken word is full white
)


def _shape(w: int, h: int) -> str:
    return "vertical" if h > w * 1.1 else ("wide" if w > h * 1.1 else "square")


def safe_area(w: int, h: int) -> dict[str, float]:
    """Fractions of the frame that text must keep clear of."""
    return {
        "vertical": {"top": 0.12, "bottom": 0.20, "side": 0.07},
        "wide": {"top": 0.07, "bottom": 0.07, "side": 0.07},
        "square": {"top": 0.07, "bottom": 0.12, "side": 0.07},
    }[_shape(w, h)]


def _sizes(w: int, h: int) -> tuple[int, int, int]:
    """Hero, headline, and caption, as libass sizes."""
    if _shape(w, h) == "wide":
        return int(h * 0.15), int(h * 0.105), int(h * 0.062)
    if _shape(w, h) == "square":
        return int(w * 0.135), int(w * 0.105), int(w * 0.058)
    return int(w * 0.155), int(w * 0.12), int(w * 0.066)


def title_centers(w: int, h: int) -> list[float]:
    """Where a title may sit, as a fraction of height, in order of preference."""
    return {"vertical": [0.26, 0.42, 0.60], "wide": [0.5, 0.25], "square": [0.3, 0.55]}[
        _shape(w, h)
    ]


@lru_cache(maxsize=32)
def _font(face: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / face), max(int(size / LIBASS_EM), 1))


def _wrap_lines(words: list[str], face: str, size: int, width: float) -> list[list[str]]:
    """Fill lines to the width, then even the last two, so a line never strands a single word."""
    font = _font(face, size)
    lines: list[list[str]] = [[]]
    for word in words:
        if lines[-1] and font.getlength(" ".join([*lines[-1], word])) > width:
            lines.append([])
        lines[-1].append(word)
    if len(lines) > 1 and len(lines[-1]) == 1 and len(lines[-2]) > 1:
        lines[-1].insert(0, lines[-2].pop())
    return lines


def scrim_alpha(level: float) -> float:
    """How much to darken a background of this grey level, 0..1, so white type is readable."""
    return max(0.0, 1.0 - SCRIM_TARGET_LEVEL / max(level, 1e-3))


def contrast_after(level: float, alpha: float) -> float:
    """WCAG contrast of white type over this grey level once the scrim is applied."""
    linear = (level * (1.0 - alpha)) ** 2.2
    return 1.05 / (linear + 0.05)


def calmest_band(gray: np.ndarray, centers: list[float]) -> float:
    """The candidate height with the least going on, leaning to the earlier candidates."""
    h = gray.shape[0]
    half = max(int(h * 0.12), 1)
    edges = np.abs(np.diff(gray.astype(np.float64), axis=1))

    def busy(index: int, center: float) -> float:
        mid = int(center * h)
        return float(edges[max(mid - half, 0) : mid + half].mean()) * (1 + 0.15 * index) + 1e-6

    return min(enumerate(centers), key=lambda item: busy(*item))[1]


def studio_header(w: int, h: int) -> str:
    hero, head, cap = _sizes(w, h)
    side = int(w * safe_area(w, h)["side"])
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hero,Inter Display SemiBold,{hero},&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,0,0,0,0,100,100,-1,0,1,0,0,5,{side},{side},0,1
Style: Head,Inter Display SemiBold,{head},&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,0,0,0,0,100,100,-0.5,0,1,0,0,5,{side},{side},0,1
Style: Cap,Inter Display Medium,{cap},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,0,0,2,{side},{side},0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _scrim_event(
    start: float, end: float, w: int, y: int, band: int, alpha: float, fade: int
) -> str:
    """A feathered darkening behind type. Never a visible box."""
    opacity = int(255 * (1 - min(alpha * 1.15, 0.85)))
    return (
        f"Dialogue: 0,{ts(start)},{ts(end)},Cap,,0,0,0,,"
        f"{{\\an7\\pos({-w // 2},{y})\\bord0\\shad0\\1c&H000000&\\1a&H{opacity:02X}&"
        f"\\blur{max(band // 3, 1)}\\fad({fade},{fade})\\p1}}"
        f"m 0 0 l {w * 2} 0 l {w * 2} {band} l 0 {band}{{\\p0}}"
    )


def studio_titles(titles: list[dict], w: int, h: int) -> str:
    """One headline per beat, the first as the hero, with a fade and a short rise."""
    lines = [studio_header(w, h)]
    safe = safe_area(w, h)
    hero, head, _ = _sizes(w, h)
    x = w // 2
    width = w * (1 - 2 * safe["side"])
    for i, t in enumerate(titles):
        size, style = (hero, "Hero") if i == 0 else (head, "Head")
        wrapped = _wrap_lines(t["text"].split(), HEAD_FACE, size, width)
        tall = len(wrapped) * size * 1.05
        low, high = h * safe["top"] + tall / 2, h * (1 - safe["bottom"]) - tall / 2
        center = t.get("y_frac", title_centers(w, h)[0])
        y = int(min(max(h * center, low), high))
        intro = 420 if i == 0 else 360
        if t.get("scrim_alpha"):
            band = int(tall * 1.8)
            lines.append(
                _scrim_event(
                    t["start_sec"], t["end_sec"], w, y - band // 2, band, t["scrim_alpha"], intro
                )
            )
        text = "\\N".join(esc(" ".join(line)) for line in wrapped)
        rise = int(h * 0.015)
        lines.append(
            f"Dialogue: 1,{ts(t['start_sec'])},{ts(t['end_sec'])},{style},,0,0,0,,"
            f"{{\\move({x},{y + rise},{x},{y},0,{intro})\\fad({intro},260)\\blur4\\t(0,{intro},0.5,\\blur0)}}{text}"
        )
    return "\n".join(lines) + "\n"


def _karaoke_lines(words: list[dict], active: int, wrapped: list[list[str]]) -> str:
    parts: list[str] = []
    at = 0
    for row in wrapped:
        chunks = []
        for _ in row:
            word = esc(words[at]["text"])
            chunks.append(f"{{\\1a&H00&}}{word}{{\\1a{INACTIVE_ALPHA}}}" if at == active else word)
            at += 1
        parts.append(" ".join(chunks))
    return "\\N".join(parts)


def studio_captions(
    captions: list[dict], w: int, h: int, band_levels: list[float] | None = None
) -> tuple[str, dict]:
    """Quiet karaoke at the bottom of the safe area, darkened behind only where the picture needs it."""
    safe = safe_area(w, h)
    _, _, cap = _sizes(w, h)
    x, y = w // 2, int(h * (1 - safe["bottom"]))
    width = w * (1 - 2 * safe["side"])
    shadow = max(cap // 9, 2)
    lines = [studio_header(w, h)]
    worst = 21.0
    for n, card in enumerate(captions):
        words = card.get("words") or [
            {"text": card["text"], "start_sec": card["start_sec"], "end_sec": card["end_sec"]}
        ]
        wrapped = _wrap_lines([wd["text"] for wd in words], CAP_FACE, cap, width)
        level = band_levels[n] if band_levels and n < len(band_levels) else 0.0
        alpha = scrim_alpha(level)
        worst = min(worst, contrast_after(level, alpha))
        tall = int(len(wrapped) * cap * 1.1)
        if alpha:
            band = int(tall * 2.2)
            lines.append(
                _scrim_event(
                    card["start_sec"], card["end_sec"], w, y - tall - band // 4, band, alpha, 90
                )
            )
        body = "\\N".join(esc(" ".join(row)) for row in wrapped)
        lines.append(
            f"Dialogue: 1,{ts(card['start_sec'])},{ts(card['end_sec'])},Cap,,0,0,0,,"
            f"{{\\pos({x},{y})\\1a&HFF&\\3c&H000000&\\3a&H70&\\bord{shadow}\\blur{shadow * 2}}}{body}"
        )
        for i, active in enumerate(words):
            start = active["start_sec"] if i else card["start_sec"]
            end = words[i + 1]["start_sec"] if i + 1 < len(words) else card["end_sec"]
            if end <= start:
                continue
            fade = "\\fad(120,0)" if i == 0 else ""
            text = _karaoke_lines(words, i, wrapped)
            lines.append(
                f"Dialogue: 2,{ts(start)},{ts(end)},Cap,,0,0,0,,{{\\pos({x},{y})\\1a{INACTIVE_ALPHA}{fade}}}{text}"
            )
    return "\n".join(lines) + "\n", {"caption_contrast_min": round(worst, 2)}


# ---------------------------------------------------------------- timed-text files
def _clock(sec: float, mark: str) -> str:
    ms = int(round(sec * 1000))
    return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d}{mark}{ms % 1000:03d}"


def _smpte(sec: float, fps: float) -> str:
    base = round(fps)
    frames = int(round(sec * fps))
    return f"{frames // (3600 * base):02d}:{frames // (60 * base) % 60:02d}:{frames // base % 60:02d}:{frames % base:02d}"


def sidecars(cues: list[dict], fps: float, language: str = "en") -> dict[str, str]:
    """Captions as files: SubRip, WebVTT, and iTunes Timed Text, so nothing has to be burned in."""
    srt = "\n".join(
        f"{i}\n{_clock(c['start_sec'], ',')} --> {_clock(c['end_sec'], ',')}\n{c['text']}\n"
        for i, c in enumerate(cues, 1)
    )
    vtt = "WEBVTT\n\n" + "\n".join(
        f"{_clock(c['start_sec'], '.')} --> {_clock(c['end_sec'], '.')}\n{c['text']}\n"
        for c in cues
    )
    multiplier = "999 1000" if abs(fps - round(fps)) > 0.001 else "1 1"
    paragraphs = "\n".join(
        f'      <p begin="{_smpte(c["start_sec"], fps)}" end="{_smpte(c["end_sec"], fps)}">{escape(c["text"], quote=False)}</p>'
        for c in cues
    )
    itt = f"""<?xml version="1.0" encoding="UTF-8"?>
<tt xmlns="http://www.w3.org/ns/ttml" xmlns:ttp="http://www.w3.org/ns/ttml#parameter" ttp:timeBase="smpte" ttp:frameRate="{round(fps)}" ttp:frameRateMultiplier="{multiplier}" ttp:dropMode="nonDrop" xml:lang="{language}">
  <body>
    <div>
{paragraphs}
    </div>
  </body>
</tt>
"""
    return {"captions.srt": srt, "captions.vtt": vtt, "captions.itt": itt}
