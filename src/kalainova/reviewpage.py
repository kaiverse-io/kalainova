"""One page to judge a piece's takes: every take of every moving shot side by side, with readings.

The readings say what a machine can: whether a clip moved, how large the model made it, whether it
was given its start frame. They cannot see a hand with six fingers, a mixer that melts, or a face
that drifts from the kit. The page puts the kit's faces and each shot's start frame beside the
takes, lists what to look for, and gives the command that records the verdict. It is a local file
next to the takes; it changes nothing and spends nothing.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from . import consistency, kits, takes
from .jobfs import ContractError, Job

PAGE = "review.html"
LOOK_FOR = (
    ("face", "The face is the kit's and the start frame's: eyes, nose, mouth, hairline, skin"),
    ("", "Hands have five fingers each, nothing fuses, and they touch what they work"),
    ("", "Objects keep their shape: nothing melts, bends, multiplies or swaps between frames"),
    ("", "Nothing morphs: no frame where a body, a face or the set turns into something else"),
    ("", "Text and logos are not warped or invented"),
    ("", "Light and colour match the shots either side"),
    ("", "The motion is the one the shot asked for, with no stutter, jump or frozen stretch"),
)
STYLE = """
:root{color-scheme:light dark;--bg:#f6f5f2;--fg:#1d1d1b;--muted:#6b6a65;--card:#fff;--line:#dedcd6;
--bad:#b3261e;--good:#2e7d32}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe6;--muted:#9a9890;--card:#201f1d;
--line:#34332f;--bad:#f2b8b5;--good:#a5d6a7}}
body{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);
font:15px/1.5 system-ui,sans-serif}
main{max-width:1200px;margin:0 auto}h1{font-size:22px}h2{font-size:18px;margin-top:40px}
.row{display:flex;flex-wrap:wrap;gap:12px}.card{background:var(--card);border:1px solid var(--line);
border-radius:8px;padding:10px;width:280px}.card video,.card img{width:100%;border-radius:4px;
background:#000}.muted{color:var(--muted)}.bad{color:var(--bad);font-weight:600}
.good{color:var(--good)}code{font-size:12px;word-break:break-all}ul{padding-left:20px}
.ref img{height:140px;width:auto}
"""


def _kit_faces(job: Job) -> list[tuple[str, Path]]:
    """Each character's identity pictures, as the kit stores them."""
    try:
        locked = consistency.for_job(job)
    except ContractError:
        return []
    if not locked:
        return []
    resolved = locked[0]
    found = []
    for role, kit in resolved.characters.items():
        for ref in (kit.get("identity") or {}).get("refs") or []:
            path = kits.blob_path(resolved.root, ref)
            if path.exists():
                found.append((f"{role}: {ref.get('label') or 'face'}", path))
    return found


def _flags(take: dict[str, Any]) -> list[str]:
    readings = take.get("readings") or {}
    found = []
    if readings.get("unmeasurable"):
        found.append(f"could not be read: {readings['unmeasurable']}")
    if readings.get("below_source_floor"):
        found.append(f"under the source size: {readings['below_source_floor']}")
    if not take.get("ok") and not found:
        found.append("missed its motion reading")
    meta = take.get("meta") or {}
    if meta.get("start_frame_sent") is False:
        found.append("not given its start frame")
    return found


def _card(job: Job, shot: str, take: dict[str, Any], chosen: int, by: str) -> str:
    readings = take.get("readings") or {}
    size = f"{readings['width']}×{readings['height']}" if readings.get("width") else "size unread"
    motion = readings.get("shot_motion")
    cost = f" · ${take['cost']:.2f}" if take.get("cost") else ""
    head = f"take {take['n']}" + (
        f" ★ in use, chosen by {escape(by)}" if take["n"] == chosen else ""
    )
    model = escape(str(take.get("model") or "?"))
    unseeded = (take.get("meta") or {}).get("seed_sent") is False
    seed = "no seed: the model takes none" if unseeded else f"seed {take.get('seed')}"
    lines = [
        f"<b>{head}</b>",
        f"<span class=muted>{model} · {seed}{cost}</span>",
        f"<span class=muted>moves {motion if motion is not None else '?'} · {size}</span>",
    ]
    if take.get("conditioning"):
        lines.append(f"<span class=muted>bench, given {escape(take['conditioning'])}</span>")
    lines += [f"<span class=bad>{escape(f)}</span>" for f in _flags(take)]
    if not _flags(take):
        lines.append("<span class=good>readings pass; your eyes decide</span>")
    lines.append(
        f"<code>kalainova verdict {job.id} accept|fix|reject --reviewer NAME --shot {shot} "
        f"--take {take['n']}</code>"
    )
    if take["n"] != chosen:
        lines.append(f"<code>kalainova take {job.id} {shot} {take['n']}</code>")
    src = escape(str(take["file"]))
    return (
        f'<div class=card><video src="{src}" controls muted loop playsinline preload=metadata>'
        f"</video><br>{'<br>'.join(lines)}</div>"
    )


def _shot(job: Job, shot: str, entry: dict[str, Any], beat: dict[str, Any]) -> str:
    cast = beat.get("cast") or []
    who = f"with {escape(', '.join(cast))}" if cast else "no character: B-roll"
    still = job.work / "beats" / f"{shot}.still.png"
    first = (
        f'<div class=card><img src="beats/{shot}.still.png" alt="start frame"><br>'
        "<b>the start frame</b></div>"
        if still.exists()
        else ""
    )
    cards = "".join(
        _card(job, shot, t, entry["chosen"], entry["chosen_by"]) for t in entry["takes"]
    )
    items = "".join(f"<li>{escape(text)}</li>" for kind, text in LOOK_FOR if cast or kind != "face")
    prompt = next((t.get("prompt") for t in entry["takes"] if t.get("prompt")), "")
    asked = (
        f"<details><summary>what it asked for</summary>{escape(prompt)}</details>" if prompt else ""
    )
    must = str((beat.get("shot") or {}).get("must_show") or "")
    keep = (
        f"<p><b>A take is kept when it shows:</b> {escape(must)}</p>"
        if must
        else "<p class=muted>Nothing says what a take must show (shot.must_show).</p>"
    )
    return (
        f"<h2>{escape(shot)} <span class=muted>· {who}</span></h2>{keep}{asked}"
        f"<ul>{items}</ul><div class=row>{first}{cards}</div>"
    )


def write(job: Job) -> Path:
    """Write the page next to the takes and return its path."""
    shots = takes.load(job)["shots"]
    if not shots:
        raise ContractError(f"{job.id}: no takes yet, so there is nothing to review")
    beats = {}
    if job.has("script_packet"):
        beats = {b["id"]: b for b in job.read("script_packet").get("beats", [])}
    faces = "".join(
        f'<div class="card ref"><img src="{path.as_uri()}" alt=""><br>{escape(label)}</div>'
        for label, path in _kit_faces(job)
    )
    body = "".join(_shot(job, s, e, beats.get(s, {})) for s, e in shots.items())
    page = (
        "<!doctype html><html lang=en><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>Takes · {escape(job.id)}</title><style>{STYLE}</style><main>"
        f"<h1>Takes for {escape(job.id)}</h1><p class=muted>Every take of every moving shot. "
        "The readings pass or flag what a machine can see; the list under each shot is what only "
        "you can. Record what you decide with the command under the take.</p>"
        + (f"<h2>The kit's faces</h2><div class=row>{faces}</div>" if faces else "")
        + f"{body}</main></html>\n"
    )
    out = job.work / PAGE
    out.write_text(page)
    return out
