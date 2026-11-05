"""ASS subtitle builders for libass: kinetic word captions, hook card, beat titles.

This is the ffmpeg-native caption renderer. A browser overlay renderer
(Remotion / HyperFrames) can replace it behind the same burn_captions op.
"""

from __future__ import annotations

FONT = "Poppins"


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
    # libass sizes by line height (ascent+descent); Poppins' tall metrics render ~0.6x.
    # These give ~70px caption caps on a 1080-wide frame.
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
        words = card.get("words") or [{"text": card["text"], "start_sec": card["start_sec"], "end_sec": card["end_sec"]}]
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
                    parts.append(f"{{\\c{ACCENT}\\t(0,90,\\fscx112\\fscy112)\\t(90,180,\\fscx100\\fscy100)}}{t}{{\\c{WHITE}}}")
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
# Keynote restraint: Inter Display (closest open face to SF Pro), sentence case, no outlines,
# soft shadow, eased fades with a short rise and a blur that resolves. In libass, Inter's size 100
# renders a 60 px cap height; sizes below are chosen by cap height on a 1080-wide frame.
STUDIO_FONTS = "/usr/share/fonts/opentype/inter"


def studio_header(w: int, h: int) -> str:
    s = w / 1080
    hero, head, cap = int(170 * s), int(132 * s), int(70 * s)
    return f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Hero,Inter Display SemiBold,{hero},&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,0,0,0,0,100,100,-2,0,1,0,0,5,90,90,0,1
Style: Head,Inter Display SemiBold,{head},&H00FFFFFF,&H00FFFFFF,&H00000000,&HA0000000,0,0,0,0,100,100,-1.5,0,1,0,0,5,90,90,0,1
Style: Cap,Inter Display Medium,{cap},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,0,0,0,0,100,100,0,0,1,0,2,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _wrap(text: str, max_chars: int) -> str:
    words, lines, cur = text.split(), [], ""
    for wd in words:
        if cur and len(cur) + 1 + len(wd) > max_chars:
            lines.append(cur)
            cur = wd
        else:
            cur = f"{cur} {wd}".strip()
    if cur:
        lines.append(cur)
    # two lines: choose the break that balances them (and never strands one word)
    if len(lines) == 2:
        ws = text.split()
        best = min(range(1, len(ws)), key=lambda k: (max(len(" ".join(ws[:k])), len(" ".join(ws[k:]))),
                                                     abs(k - len(ws) / 2)))
        lines = [" ".join(ws[:best]), " ".join(ws[best:])]
    return "\\N".join(esc(l) for l in lines)


def studio_titles(titles: list[dict], w: int, h: int) -> str:
    """One headline per beat. The first is the hero. Fade + 28 px rise + blur resolving, eased by timing."""
    lines = [studio_header(w, h)]
    x = w // 2
    for i, t in enumerate(titles):
        hero = i == 0
        style = "Hero" if hero else "Head"
        y = int(h * (0.40 if hero else 0.33))
        dur = int((t["end_sec"] - t["start_sec"]) * 1000)
        intro = 420 if hero else 360
        text = _wrap(t["text"], 14 if hero else 17)
        if t.get("scrim"):  # over real footage: feathered falloff behind the type, never a visible box
            for k, (frac, alpha) in enumerate(((0.42, "E0"), (0.30, "D0"), (0.20, "C0"), (0.12, "B0"))):
                band = int(h * frac)
                lines.append(
                    f"Dialogue: 0,{ts(t['start_sec'])},{ts(t['end_sec'])},Head,,0,0,0,,"
                    f"{{\\an7\\pos({-w // 2},{y - band // 2})\\bord0\\shad0\\1c&H000000&\\1a&H{alpha}&"
                    f"\\blur{int(band * 0.35)}\\fad({intro},260)\\p1}}m 0 0 l {w * 2} 0 l {w * 2} {band} l 0 {band}{{\\p0}}"
                )
        lines.append(
            f"Dialogue: 1,{ts(t['start_sec'])},{ts(t['end_sec'])},{style},,0,0,0,,"
            f"{{\\move({x},{y + 28},{x},{y},0,{intro})\\fad({intro},260)\\blur6\\t(0,{intro},0.5,\\blur0)}}{text}"
        )
    return "\n".join(lines) + "\n"


def studio_captions(captions: list[dict], w: int, h: int, y_frac: float = 0.62) -> str:
    """Quiet karaoke: the whole line sits at 40% white; the spoken word is full white. No pops, no colour."""
    x, y = w // 2, int(h * y_frac)
    lines = [studio_header(w, h)]
    dim = "&H99&"  # alpha: 0x99 ≈ 40% opacity
    for card in captions:
        words = card.get("words") or [{"text": card["text"], "start_sec": card["start_sec"], "end_sec": card["end_sec"]}]
        for i, active in enumerate(words):
            start = active["start_sec"] if i else card["start_sec"]
            end = words[i + 1]["start_sec"] if i + 1 < len(words) else card["end_sec"]
            if end <= start:
                continue
            parts = [f"{{\\1a&H00&}}{esc(wd['text'])}{{\\1a{dim}}}" if j == i else esc(wd["text"]) for j, wd in enumerate(words)]
            fade = "\\fad(120,0)" if i == 0 else ""
            lines.append(f"Dialogue: 2,{ts(start)},{ts(end)},Cap,,0,0,0,,{{\\pos({x},{y})\\1a{dim}{fade}}}{' '.join(parts)}")
    return "\n".join(lines) + "\n"
