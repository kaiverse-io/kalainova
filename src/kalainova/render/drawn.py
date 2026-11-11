"""Type drawn by HyperFrames: word-timed captions as a transparent layer, and cards as shots.

The caption layer is rendered alone, as a WebM with an alpha channel, and laid over the graded
picture with ffmpeg, so the grade path is never touched. Everything here is format only: the text
comes from the piece's own word timings or from the caller, never from the engine.

The layer stays inside the profile's `safe_zone` (a caption band and a right margin), so word-timed
type never lands where a player's interface overlays cover it.
"""

from __future__ import annotations

import json
import re
import shutil
from html import escape
from pathlib import Path
from typing import Any

from .. import captions as ass
from .. import media
from ..jobfs import ContractError
from ..providers import base

ACCENT, WHITE = "#ffd24a", "#ffffff"
FACE = "InterDisplay-SemiBold.ttf"
FACE_NAME = "Kalainova Type"
LINE_HEIGHT = 1.18
MAX_ROWS = 3
SIDE_FRACTION = 0.05
DEFAULT_ZONE = (0.70, 0.88, 0.05)  # lower band and right margin where a profile states none
REPORT = "captions.drawn.json"
CARD_KINDS = ("title", "quote", "stat")


# ---------------------------------------------------------------- shared
def _font_face() -> str:
    return (
        f"@font-face{{font-family:'{FACE_NAME}';src:url('assets/fonts/{FACE}');font-weight:600;}}"
    )


def _copy_font(folder: Path) -> None:
    dest = folder / "assets" / "fonts"
    dest.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ass.FONTS / FACE, dest / FACE)


def _tw(sel: str, start: float, frm: str, to: str, dur: float, ease: str) -> str:
    """One tween written out as a plain line, so a person can read the page."""
    args = f'"{sel}", {{{frm}}}, {{{to}, duration: {_num(dur)}, ease: "{ease}"}}, {_num(start)}'
    return f"tl.fromTo({args});"


def _num(value: float) -> str:
    return f"{round(float(value), 3):g}"


def _root(w: int, h: int, seconds: float, fps: float, body: str, script: str, style: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width={w}, height={h}">
<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>
<style>
{_font_face()}
html, body {{ margin: 0; padding: 0; background: transparent; }}
#root {{ position: relative; width: {w}px; height: {h}px; overflow: hidden; background: transparent;
  font-family: '{FACE_NAME}', 'Inter', sans-serif; font-weight: 600; }}
{style}
</style>
</head>
<body>
<div id="root" data-composition-id="main" data-start="0" data-duration="{_num(seconds)}"
  data-fps="{_num(fps)}" data-width="{w}" data-height="{h}">
{body}
</div>
<script>
window.__timelines = window.__timelines || {{}};
const tl = gsap.timeline({{ paused: true }});
{script}
window.__timelines["main"] = tl;
</script>
</body>
</html>
"""


# ---------------------------------------------------------------- kinetic captions
def band(zone: list[float] | tuple[float, ...] | None) -> tuple[float, float, float]:
    """The caption band (top and bottom, as fractions of the height) and the right margin."""
    if not zone:
        return DEFAULT_ZONE
    low, high, right = (float(x) for x in zone)
    if not 0 <= low < high <= 1 or not 0 <= right < 0.5:
        raise ContractError(f"safe zone {list(zone)} is not a band inside the frame")
    return low, high, right


def _layout(
    words: list[str], w: int, h: int, zone: tuple[float, float, float]
) -> tuple[list[list[str]], int]:
    """Rows and a font size such that the card fits the band and stays out of the right margin."""
    low, high, right = zone
    width = w * (1 - right - SIDE_FRACTION) * 0.94  # word spacing adds to the measured line
    room = (high - low) * h
    px = int(w * 0.085)
    while True:
        wrapped = ass._wrap_lines(words, ass.HEAD_FACE, int(px * ass.LIBASS_EM), width)
        if (len(wrapped) <= MAX_ROWS and len(wrapped) * px * LINE_HEIGHT <= room) or px <= 28:
            return wrapped, px
        px -= 2


def _card_entry(
    n: int, card: dict[str, Any], seconds: float, w: int, h: int, zone: tuple[float, float, float]
) -> tuple[str, list[str], dict[str, float]]:
    words = card.get("words") or [
        {"text": card["text"], "start_sec": card["start_sec"], "end_sec": card["end_sec"]}
    ]
    low, high, right = zone
    texts = [wd["text"].upper() for wd in words]
    rows, px = _layout(texts, w, h, zone)
    start = max(float(card["start_sec"]), 0.0)
    end = min(float(card["end_sec"]), seconds)
    block = len(rows) * px * LINE_HEIGHT
    top = low * h + ((high - low) * h - block) / 2
    emph = {e.lower() for e in card.get("emphasis", [])}
    html_rows, tweens, at = [], [], 0
    for row in rows:
        spans = []
        for _ in row:
            wd = words[at]
            cls = "w e" if wd["text"].lower() in emph else "w"
            spans.append(f'<span id="g{n}w{at}" class="{cls}">{escape(texts[at])}</span>')
            at += 1
        html_rows.append(f'<div class="row">{" ".join(spans)}</div>')
    g = f"#g{n}"
    tweens.append(_tw(g, start, "opacity: 0, y: 14", "opacity: 1, y: 0", 0.12, "power2.out"))
    for i, wd in enumerate(words):
        ws = float(wd["start_sec"]) if i else start
        we = float(words[i + 1]["start_sec"]) if i + 1 < len(words) else end
        if we <= ws:
            continue
        tweens.append(f'tl.set("{g}w{i}", {{color: "{ACCENT}"}}, {_num(ws)});')
        tweens.append(_tw(f"{g}w{i}", ws, "scale: 1.14", "scale: 1", 0.16, "back.out(2)"))
        if wd["text"].lower() not in emph:
            tweens.append(f'tl.set("{g}w{i}", {{color: "{WHITE}"}}, {_num(we)});')
    tweens.append(_tw(g, max(end - 0.1, start), "opacity: 1", "opacity: 0", 0.1, "power2.in"))
    tweens.append(f'tl.set("{g}", {{opacity: 0}}, {_num(end)});')
    div = (
        f'<div id="g{n}" class="clip cap" data-start="{_num(start)}" '
        f'data-duration="{_num(end - start)}" style="top:{int(top)}px;height:{int(block)}px;'
        f'font-size:{px}px">{"".join(html_rows)}</div>'
    )
    box = {
        "top": round(top / h, 4),
        "bottom": round((top + block) / h, 4),
        "right": round(1 - right, 4),
    }
    return div, tweens, box


def caption_composition(
    captions: list[dict[str, Any]],
    w: int,
    h: int,
    seconds: float,
    fps: float,
    zone: list[float] | tuple[float, ...] | None = None,
) -> tuple[str, dict[str, Any]]:
    """The caption layer as a HyperFrames page, and where its type sits (for the QA warning)."""
    z = band(zone)
    divs, script, boxes = [], [], []
    for n, card in enumerate(captions):
        if float(card["end_sec"]) <= float(card["start_sec"]):
            continue
        div, tweens, box = _card_entry(n, card, seconds, w, h, z)
        divs.append(div)
        script.extend(tweens)
        boxes.append(box)
    left = int(w * SIDE_FRACTION)
    across = int(w * (1 - z[2] - SIDE_FRACTION)) - left
    shadow = "0 2px 12px rgba(0,0,0,.55), 0 0 2px rgba(0,0,0,.7)"
    style = (
        f".cap {{ position: absolute; left: {left}px; width: {across}px; text-align: center;\n"
        f"  overflow: visible; opacity: 0; line-height: {LINE_HEIGHT}; letter-spacing: 0.01em;\n"
        f"  text-shadow: {shadow}; }}\n"
        ".row { white-space: nowrap; word-spacing: 0.14em; }\n"
        f".w {{ display: inline-block; color: {WHITE}; }}\n"
        f".w.e {{ color: {ACCENT}; }}"
    )
    page = _root(w, h, seconds, fps, "\n".join(divs), "\n".join(script), style)
    report = {"width": w, "height": h, "zone": list(z), "boxes": boxes}
    return page, report


def _provider() -> base.Provider:
    return base.get("hyperframes")


def render_layer(folder: Path, dst: Path, fps: float) -> None:
    """Render the composition in `folder` to a WebM with alpha. Free, local, and no model."""
    provider = _provider()
    if not provider.available():
        raise ContractError(
            f"kinetic captions need {', '.join(provider.missing_env())} on this machine"
        )
    provider.graphics(folder, dst, fps=fps)
    if not dst.exists():
        raise ContractError(f"the graphics provider wrote no file at {dst.name}")


def composite(work: Path, src: Path, layer: Path, out: Path) -> None:
    """The layer over the picture, keeping the picture's size, rate and colour tags."""
    pix = media.MASTER_PIX_FMT
    # the layer is converted with the picture's own matrix, so white stays white
    convert = f"{media.TO_BT709},format=yuva444p10le"
    graph = (
        f"[0:v]format={pix}[b];[1:v]{convert}[o];"
        f"[b][o]overlay=format=yuv444p10:eof_action=pass,{media.TO_BT709},format={pix}"
    )
    media.run(
        [
            "-i", src.name,
            "-c:v", "libvpx-vp9", "-i", layer.name,
            "-filter_complex", graph,
            *media.MASTER_ARGS, out.name,
        ],
        cwd=work,
    )  # fmt: skip


def burn_drawn_captions(work: Path, src: Path, out: Path, a: dict[str, Any]) -> None:
    """The picture with kinetic captions drawn over it by HyperFrames."""
    seconds = media.duration(src)
    page, report = caption_composition(
        a["captions"], a["width"], a["height"], seconds, a.get("fps") or 30.0, a.get("zone")
    )
    folder = work / "captions_drawn"
    folder.mkdir(exist_ok=True)
    (folder / "index.html").write_text(page)
    _copy_font(folder)
    (work / REPORT).write_text(json.dumps(report) + "\n")
    layer = work / "captions.layer.webm"
    render_layer(folder, layer, float(a.get("fps") or 30.0))
    composite(work, src, layer, out)


# ---------------------------------------------------------------- cards
_NUMBER = re.compile(r"^(\D*?)(\d+(?:\.\d+)?)(\D*)$")
CARD_STYLE = """
.bg { position: absolute; inset: -6%;
  background: radial-gradient(120% 90% at 50% 40%, #2a3350 0%, #1b2233 70%); }
.col { position: absolute; display: flex; flex-direction: column; justify-content: center;
  align-items: center; text-align: center; color: #fff; }
.big { font-size: BIGpx; line-height: 1.12; }
.small { font-size: SMALLpx; line-height: 1.25; color: #c9d2e8; margin-top: GAPpx; }
.rule { width: RULEpx; height: 4px; background: ACCENT; margin-top: GAPpx; }
"""
CARD_SCALE = {"title": 0.10, "quote": 0.065, "stat": 0.22}


def _card_fields(kind: str, fields: dict[str, str]) -> tuple[str, str]:
    needed = {"title": ("text",), "quote": ("text",), "stat": ("value", "label")}[kind]
    missing = [k for k in needed if not str(fields.get(k, "")).strip()]
    if missing:
        raise ContractError(f"a {kind} card needs {', '.join(missing)}")
    if kind == "stat":
        return str(fields["value"]), str(fields["label"])
    return str(fields["text"]), str(fields.get("sub") or "")


def _card_style(kind: str, w: int) -> str:
    style = CARD_STYLE
    sizes = {
        "BIG": int(w * CARD_SCALE[kind]),
        "SMALL": int(w * 0.045),
        "GAP": int(w * 0.04),
        "RULE": int(w * 0.12),
    }
    for token, value in sizes.items():
        style = style.replace(token + "px", f"{value}px")
    return style.replace("ACCENT", ACCENT)


def _counter(main: str) -> str:
    """A number that counts up to its value, as a function of timeline time only."""
    counted = _NUMBER.match(main)
    if not counted:
        return ""
    before, digits, after = counted.groups()
    places = len(digits.partition(".")[2])
    text = f"{json.dumps(before)} + c.n.toFixed({places}) + {json.dumps(after)}"
    update = f'document.getElementById("main").textContent = {text};'
    return (
        f'const c = {{n: 0}}; tl.to(c, {{n: {digits}, duration: 1.2, ease: "power2.out", '
        f"onUpdate: () => {{ {update} }}}}, 0.15);"
    )


def card_composition(
    kind: str, fields: dict[str, str], w: int, h: int, seconds: float, fps: float = 30.0
) -> str:
    """A title, quote or stat card as a full-frame composition. The caller supplies every word."""
    if kind not in CARD_KINDS:
        raise ContractError(f"card kind must be one of {', '.join(CARD_KINDS)}, not {kind!r}")
    main, sub = _card_fields(kind, fields)
    safe = ass.safe_area(w, h)
    left, top = int(w * safe["side"]), int(h * safe["top"])
    tall = int(h * (1 - safe["top"] - safe["bottom"]))
    area = f"left:{left}px;top:{top}px;width:{w - 2 * left}px;height:{tall}px"
    mark, close = ("&ldquo;", "&rdquo;") if kind == "quote" else ("", "")
    body = (
        '<div class="bg" id="bg"></div>\n'
        f'<div class="col" style="{area}">'
        f'<div class="big" id="main">{mark}{escape(main)}{close}</div>'
        '<div class="rule" id="rule"></div>'
        f'<div class="small" id="sub">{escape(sub)}</div></div>'
    )
    script = [
        _tw("#bg", 0, "scale: 1", "scale: 1.05", seconds, "none"),  # every frame moves
        _tw("#main", 0.15, "opacity: 0, y: 30", "opacity: 1, y: 0", 0.5, "power2.out"),
        _tw("#rule", 0.5, "opacity: 0, scaleX: 0", "opacity: 1, scaleX: 1", 0.4, "power2.out"),
        _tw("#sub", 0.7, "opacity: 0, y: 20", "opacity: 1, y: 0", 0.5, "power2.out"),
    ]
    if kind == "stat":
        script.append(_counter(main))
    return _root(w, h, seconds, fps, body, "\n".join(script), _card_style(kind, w))


def write_card(
    folder: Path,
    kind: str,
    fields: dict[str, str],
    w: int,
    h: int,
    seconds: float,
    fps: float = 30.0,
) -> Path:
    """Write a card into `folder` (a job's graphics/<beat>) and return its index.html."""
    page = card_composition(kind, fields, w, h, seconds, fps)
    folder.mkdir(parents=True, exist_ok=True)
    _copy_font(folder)
    out = folder / "index.html"
    out.write_text(page)
    return out
