"""One page to judge a piece's takes: every take of every moving shot side by side, with readings.

The readings say what a machine can: whether a clip moved, how large the model made it, whether it
was given its start frame. They cannot see a hand with six fingers, a mixer that melts, or a face
that drifts from the kit. The page puts the kit's faces and each shot's start frame beside the
takes, lists what to look for, and gives the command that records the verdict. It is a local file
next to the takes; it changes nothing and spends nothing.
"""

from __future__ import annotations

import datetime as dt
import json
import secrets
import string
from html import escape
from pathlib import Path
from typing import Any

from . import config, consistency, kits, media, takes
from .bar import judges
from .bar import song as musicbar
from .blobstore import sha256_file
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


# ------------------------------------------------------------------ hearing songs blind
BLIND, RANKING = "listen.html", "ranking.json"


def blind(jobs: list[Job]) -> Path:
    """Every song take of these jobs, shuffled, at one loudness, named by letter only.

    Louder sounds better to a listener, so each take is copied at the song profile's level, with
    the source's tags stripped. Which job, take and model made each letter is kept away from the
    page, in a key folder beside it, and is told only once the ranking is recorded (rank), so the
    ranking cannot lean on a model's name or on a score."""
    found = []
    for job in jobs:
        shot = takes.load(job)["shots"].get("song")
        if not shot or not shot.get("takes"):
            raise ContractError(f"{job.id}: no song takes yet, so there is nothing to hear")
        found += [(job, t) for t in shot["takes"] if not t.get("bench")]
    if not 2 <= len(found) <= len(string.ascii_uppercase):
        raise ContractError(f"a blind comparison takes 2 to 26 takes, not {len(found)}")
    secrets.SystemRandom().shuffle(found)
    level = config.profile("song")
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out = jobs[0].work.parent / f"listen-{stamp}"
    out.mkdir(parents=True)
    key = []
    for letter, (job, take) in zip(string.ascii_uppercase, found, strict=False):
        src, levelled = job.work / take["file"], out / f".{letter}.levelled.wav"
        media.master_loudness(
            src, levelled, float(level.get("target_lufs", -14)),
            float(level.get("true_peak_dbtp_max", -1)),
        )  # fmt: skip
        media.run(["-i", str(levelled), "-map_metadata", "-1", "-fflags", "+bitexact",
                   str(out / f"{letter}.wav")])  # fmt: skip
        levelled.unlink()
        key.append({"letter": letter, "job": job.id, "take": take["n"], "file": take["file"],
                    "provider": take.get("provider", ""), "model": take.get("model", ""),
                    "sha256": sha256_file(src)})  # fmt: skip
    _key_path(out).parent.mkdir(exist_ok=True)
    _key_path(out).write_text(json.dumps({"made_at": stamp, "takes": key}, indent=2) + "\n")
    rows = "".join(
        f"<div class=card><b>{k['letter']}</b><br>"
        f'<audio controls preload=none src="{k["letter"]}.wav"></audio></div>'
        for k in key
    )
    letters = ",".join(k["letter"] for k in key)
    (out / BLIND).write_text(
        "<!doctype html><html lang=en><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>Blind listening</title><style>{STYLE}</style><main><h1>Blind listening</h1>"
        f"<p class=muted>{len(key)} takes, shuffled and set to one loudness. Listen to each in"
        " full. Which take is which is told when your ranking is recorded.</p>"
        f"<div class=row>{rows}</div><h2>Record your ranking, best first</h2>"
        f"<pre>kalainova review {escape(str(out))} --rank {letters} --reviewer NAME</pre></main>"
        "</html>\n"
    )
    return out / BLIND


def _key_path(folder: Path) -> Path:
    """Where a blind set's answers are kept: beside its folder, never in it."""
    return folder.parent / "listen-keys" / f"{folder.name}.json"


def rank(folder: Path, order: str, reviewer: str) -> str:
    """Record one ranking of a blind set, best first, then say what each letter was. A set is
    ranked once: a second ranking would be made knowing the answers."""
    if not reviewer.strip():
        raise ContractError("say who ranked it (--reviewer)")
    key_path, out = _key_path(folder), folder / RANKING
    if not key_path.is_file():
        raise ContractError(f"{folder} is not a blind listening set")
    key = {k["letter"]: k for k in json.loads(key_path.read_text())["takes"]}
    asked = [x.strip().upper() for x in order.split(",") if x.strip()]
    if sorted(asked) != sorted(key):
        raise ContractError(f"rank every letter once: {','.join(sorted(key))}")
    ranked = [{"place": i, **key[x]} for i, x in enumerate(asked, 1)]
    at = dt.datetime.now(dt.UTC).isoformat(timespec="seconds")
    try:  # made only if absent, so two rankings at once cannot both be kept
        with out.open("x") as fh:
            fh.write(
                json.dumps({"reviewer": reviewer, "at": at, "ranked": ranked}, indent=2) + "\n"
            )
    except FileExistsError as exc:
        raise ContractError(
            f"{folder} was ranked already; a second would know the answers"
        ) from exc
    return "\n".join(
        f"{r['place']}. {r['letter']}: {r['job']} take {r['take']} ({r['model'] or r['provider']})"
        for r in ranked
    )


def judged(jobs: list[Job]) -> str:
    """Every song take of these jobs scored by the configured judges, one run each, kept on each
    take (`judged`, `rank`), and listed best first with what its readings missed. A judge's
    score ranks; the misses say where a take it likes still fails the brief.

    Each take is read again first, with today's bar and the transcript kept beside it, so a reading
    added since it was made counts and nothing is spent. Last comes the pick between the jobs, by
    the rule that chooses within one (`takes.best`). A job's own choice is left as it stands."""
    if not judges.configured("song"):
        raise ContractError("no judges.song in config/studio.yaml; see docs/how-to/make-a-song.md")
    held = [(job, takes.load(job)) for job in jobs]
    found = [
        (job, t)
        for job, data in held
        for t in (data["shots"].get("song") or {}).get("takes", [])
        if not t.get("bench")
    ]
    if not found:
        raise ContractError("no song takes in these jobs, so there is nothing to judge")
    scores, notes = judges.score("song", [job.work / t["file"] for job, t in found])
    for job, take in found:
        path = job.work / take["file"]
        read, take["ok"] = musicbar.assessed(path, job.read("song"), musicbar.saved_heard(path))
        mine = scores.get(path, {})
        take["readings"] = {**read, "judged": mine, "rank": judges.rank_value("song", mine)}
    for job, data in held:
        job.write("takes", data)
    order = sorted(found, key=lambda f: -(f[1]["readings"]["rank"] or 0))
    lines = [*notes, *(_judged_line(job, take) for job, take in order)]
    return "\n".join([*lines, _pick(found)])


def _judged_line(job: Job, take: dict[str, Any]) -> str:
    readings = take["readings"]
    said = ", ".join(f"{k} {v:g}" for k, v in readings["judged"].items()) or "not judged"
    missed = ", ".join(readings["misses"]) or "none"
    stem = (job.work / take["file"]).with_suffix(musicbar.STEM_HEARD).exists()
    heard = "; words heard off its vocal stem" if stem else ""
    return f"{job.id} take {take['n']} ({take.get('model')}): {said}; misses {missed}{heard}"


def _pick(found: list[tuple[Job, dict[str, Any]]]) -> str:
    """Between jobs, the take the rule within one would choose, and why."""
    chosen = takes.best([take for _, take in found])
    job = next(job for job, take in found if take is chosen)
    named = f"{job.id} take {chosen['n']} ({chosen.get('model')})"
    if chosen["ok"]:
        return f"pick: {named}, the judge's highest of the takes that pass every reading"
    missed = ", ".join(chosen["readings"]["misses"])
    return f"pick: none passes every reading; the closest is {named}, which misses {missed}"


def cli(
    names: list[str], blind_set: bool, order: str | None, reviewer: str, *, judge: bool = False
) -> str:
    """`kalainova review`: one job's takes, several song jobs heard blind or judged, or a blind
    ranking."""
    from .jobfs import open_job

    if judge:
        return judged([open_job(n) for n in names])
    if order is not None:
        if len(names) != 1:
            raise ContractError("--rank takes the one blind listening folder it ranks")
        return rank(Path(names[0]), order, reviewer)
    if blind_set:
        return str(blind([open_job(n) for n in names]))
    if len(names) != 1:
        raise ContractError("several jobs are heard side by side with --blind")
    return str(write(open_job(names[0])))
