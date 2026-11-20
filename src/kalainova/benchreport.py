"""A bench, read: every take of one shot side by side with a label on each, a table of every
reading, and the engine's pick with the reason for it.

The pick is advice (ADR 0024, ADR 0026). The readings that rank are named in config (`rank`, by
capability), each with which way is better. Each is scaled within the takes being compared, never
held to a fixed mark, so the rule carries from a quiet close-up to a loud wide shot: it only says
which of these takes reads best. A take that misses a floor, or was not read by every ranking
judge, is listed but not ranked. When the first two are close, or nothing ranks, the engine says
so rather than choose; a person's verdicts (`kalainova agreement`) show whether its picks hold.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from . import config, media, resources, takejudges, takes
from .bar import judges
from .editor import singing
from .jobfs import ContractError, Job

Take = dict[str, Any]
PANEL_W, PANEL_H = 360, 640
LABEL_H = 46  # a strip above the panels names each one, so a viewer can say which is which
LABEL_FONT = "Inter-Medium.ttf"
CLOSE = 0.25  # in the takes' own spread: first and second nearer than this is a person's call
ROUTE = (
    "image-to-video",
    "reference-to-video",
    "audio-to-video",
    "text-to-video",
    "video-to-video",
)


def short(model: str) -> str:
    """A model's name for a label: its vendor path without the route words every model shares."""
    parts = []
    for one in model.split("+"):
        kept = [p for p in one.strip().removeprefix("fal-ai/").split("/") if p not in ROUTE]
        parts.append("/".join(kept))
    return " + ".join(parts)


def reading(take: Take, name: str) -> float | None:
    """One reading of a take, from its judges or its own readings; None when it was not read."""
    found = take.get("readings") or {}
    value = (found.get("judged") or {}).get(name, found.get(name))
    return float(value) if isinstance(value, int | float) else None


def rules(capability: str) -> tuple[list[dict[str, Any]], float]:
    """The readings that rank this capability's takes, and how near counts as close."""
    table = config.studio().get("rank") or {}
    rows = [r for r in table.get(capability) or [] if r.get("reading")]
    for row in rows:
        if row.get("better", "higher") not in ("higher", "lower"):
            raise ContractError(f"rank.{capability}: {row['reading']} is better higher or lower")
    return rows, float(table.get("close", CLOSE))


def _scaled(values: list[float], lower: bool) -> list[float]:
    spread = pstdev(values)
    signed = [-v for v in values] if lower else values
    centre = mean(signed)
    return [(v - centre) / spread if spread else 0.0 for v in signed]


def _floor_note(take: Take, floor: int) -> str:
    w, h = reading(take, "width"), reading(take, "height")
    return (
        f"made at {w:.0f}x{h:.0f}, under the {floor} px floor"
        if w and h and floor and min(w, h) < floor
        else ""
    )


def _readable(made: list[Take], names: list[str], left_out: dict[int, str]) -> list[Take]:
    """The takes every ranking reading read; the others are noted in `left_out`."""
    read = []
    for t in made:
        missing = [n for n in names if reading(t, n) is None]
        if t["n"] in left_out:
            continue
        if missing:
            left_out[t["n"]] = f"not read by {', '.join(missing)}"
        else:
            read.append(t)
    return read


def _scores(
    read: list[Take], ranking: list[dict[str, Any]]
) -> tuple[dict[int, float], dict[int, dict[str, Any]]]:
    """Each take's weighted, scaled score, and its value and place on each ranking reading."""
    scores = {t["n"]: 0.0 for t in read}
    places: dict[int, dict[str, Any]] = {t["n"]: {} for t in read}
    weights = sum(float(r.get("weight", 1.0)) for r in ranking)
    for row in ranking:
        values = [reading(t, row["reading"]) or 0.0 for t in read]
        lower = row.get("better", "higher") == "lower"
        for t, z in zip(read, _scaled(values, lower), strict=True):
            scores[t["n"]] += float(row.get("weight", 1.0)) * z / weights
        best_first = sorted(values, reverse=not lower)
        for t, v in zip(read, values, strict=True):
            places[t["n"]][row["reading"]] = (v, best_first.index(v) + 1)
    return scores, places


def _decide(
    rows: list[dict[str, Any]], places: dict[int, dict[str, Any]], close: float
) -> dict[str, Any]:
    """The pick among ranked rows: the first made at size, unless the next is too close."""
    if not rows:
        return {"status": "unsure", "reason": "no take was read by every ranking reading"}
    sized = [r for r in rows if not r["under_floor"]]
    if not sized:
        first = rows[0]
        return {
            "status": "unsure",
            "reason": f"take {first['n']} reads best, but every ranked "
            f"take is under the size floor ({first['under_floor']})",
        }
    pick = sized[0]
    said = ", ".join(
        f"{name} {v:.3g} ({place} of {len(rows)})" for name, (v, place) in places[pick["n"]].items()
    )
    reason = f"take {pick['n']} ({short(pick['model'])}): {said}"
    if pick is not rows[0]:
        reason += f"; take {rows[0]['n']} reads higher but was {rows[0]['under_floor']}"
    rest = [r for r in sized if r is not pick]
    if rest and pick["score"] - rest[0]["score"] < close:
        reason += f"; take {rest[0]['n']} is within {close} of it, so a person decides"
        return {"status": "close", "pick": pick["n"], "reason": reason}
    return {"status": "pick", "pick": pick["n"], "reason": reason}


def rank(
    made: list[Take], ranking: list[dict[str, Any]], close: float = CLOSE, floor: int = 0
) -> dict[str, Any]:
    """Order the takes by the ranking readings, each scaled within these takes; pick the first
    that meets the size floor, or say why there is no pick."""
    left_out: dict[int, str] = {t["n"]: "missed its floor" for t in made if not t.get("ok")}
    if not ranking:
        reason = "no readings are set to rank these takes (config: rank)"
        return {"status": "none", "order": [], "pick": None, "left_out": left_out, "reason": reason}
    read = _readable(made, [r["reading"] for r in ranking], left_out)
    scores, places = _scores(read, ranking)
    order = sorted(read, key=lambda t: (-scores[t["n"]], t["n"]))
    rows = [
        {
            "n": t["n"],
            "model": t.get("model", ""),
            "score": round(scores[t["n"]], 3),
            "under_floor": _floor_note(t, floor),
        }
        for t in order
    ]
    return {"order": rows, "left_out": left_out, "pick": None, **_decide(rows, places, close)}


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return resources.label_font(LABEL_FONT, size)


def labels(made: list[Take], dst: Path) -> Path:
    """One strip naming each panel: its place, its take, and the model that made it."""
    strip = Image.new("RGB", (PANEL_W * len(made), LABEL_H), "black")
    draw = ImageDraw.Draw(strip)
    for i, take in enumerate(made):
        lines = (f"{i + 1}   take {take['n']:02d}", short(str(take.get("model") or "")))
        for row, (text, size) in enumerate(zip(lines, (17, 13), strict=True)):
            font = _font(size)
            while size > 8 and draw.textlength(text, font=font) > PANEL_W - 14:
                size -= 1
                font = _font(size)
            draw.text((i * PANEL_W + 7, 4 + row * 22), text, fill="white", font=font)
    strip.save(dst)
    return dst


def side_by_side(job: Job, shot: str, made: list[Take], line: Path | None) -> Path:
    """The takes side by side under a strip naming each, in the order given. A sung bench plays
    its one line over them, each take slipped onto it by the offset its lip judge measured."""
    folder = job.work / "bench"
    folder.mkdir(exist_ok=True)
    out = folder / f"{shot}.mp4"
    aligned = []
    for take in made:
        copy = folder / f"{shot}.take-{take['n']:02d}.aligned.mp4"
        shutil.copyfile(job.work / take["file"], copy)
        if line:
            singing.slip(copy, singing.offset_of(take.get("readings") or {}))
        aligned.append(copy)
    strip = labels(made, folder / f"{shot}.labels.png")
    n = len(made)
    inputs = [arg for clip in aligned for arg in ("-i", str(clip))]
    fitted = "".join(
        f"[{i}:v]scale={PANEL_W}:{PANEL_H}:force_original_aspect_ratio=decrease,"
        f"pad={PANEL_W}:{PANEL_H}:-1:-1,fps=25,setsar=1[v{i}];"
        for i in range(n)
    )
    stack = "".join(f"[v{i}]" for i in range(n))
    joined = f"{stack}hstack=inputs={n}[s];" if n > 1 else "[v0]null[s];"
    named = f"[s]pad=iw:ih+{LABEL_H}:0:{LABEL_H}[p];[p][{n}:v]overlay=0:0[v]"
    sound = ["-i", str(line), "-map", f"{n + 1}:a", "-shortest", "-c:a", "aac"] if line else []
    media.run(
        [
            *inputs,
            "-i",
            str(strip),
            *sound[:2],
            "-filter_complex",
            fitted + joined + named,
            "-map",
            "[v]",
            *sound[2:],
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(out),
        ]
    )
    return out


def _beat(job: Job, shot: str) -> dict[str, Any]:
    beat = next((b for b in job.read("script_packet")["beats"] if b["id"] == shot), None)
    if not beat:
        raise ContractError(f"{job.id}: no shot {shot}")
    return dict(beat)


def _line(job: Job, beat: dict[str, Any]) -> Path | None:
    line = job.work / "beats" / f"{beat['id']}.voice.wav"
    return line if beat.get("sings") and line.exists() else None


def line_of(job: Job, shot: str) -> Path | None:
    """The shot's line of the vocal when it sings, else None."""
    return _line(job, _beat(job, shot))


def benched(job: Job, shot: str, only: list[int] | None = None) -> list[Take]:
    """The shot's bench takes, all of them in take order, or the ones named in the order named."""
    have = {
        t["n"]: t
        for t in (takes.load(job)["shots"].get(shot) or {}).get("takes", [])
        if t.get("bench")
    }
    if only is None:
        return [have[n] for n in sorted(have)]
    missing = [n for n in only if n not in have]
    if missing:
        raise ContractError(f"{job.id}: {shot} has no bench take {missing}; it has {sorted(have)}")
    return [have[n] for n in only]


def _aperture(found: dict[str, Any]) -> float | None:
    judged = found.get("judged") or {}
    return next((float(v) for k, v in judged.items() if k.endswith(".aperture_sd")), None)


def repaint_kept(job: Job, take: Take, line: Path | None) -> float | None:
    """How much of the mouth's movement a repaint kept: its spread over the clip it repainted.
    A redrawn mouth that barely moves on an open sung line reads near zero."""
    clip = job.work / take["file"]
    unsung = clip.with_name(f"{clip.stem}.unsung{clip.suffix}")
    if not line or not unsung.exists():
        return None
    before = _aperture(takejudges.lips(unsung, line))
    after = _aperture(take.get("readings") or {})
    return round(after / before, 3) if before and after is not None else None


def _unread(readings: dict[str, Any], kind: str) -> bool:
    """Whether a configured judge of this kind has left no score on the take yet."""
    have = readings.get("judged") or {}
    return any(not any(k.startswith(f"{j.name}.") for k in have) for j in judges.configured(kind))


def rejudge(job: Job, shot: str, only: list[int] | None = None, fresh: bool = True) -> None:
    """Run every configured judge again over stored bench takes, at no cost. With `fresh` off,
    only what a take is missing is read."""
    beat = _beat(job, shot)
    line = _line(job, beat)
    data = takes.load(job)
    names = {t["n"] for t in benched(job, shot, only)}
    for take in (data["shots"].get(shot) or {}).get("takes", []):
        if take["n"] not in names:
            continue
        old = take.get("readings") or {}
        lips = line is not None and (fresh or _unread(old, "lipsync"))
        moves = bool(beat.get("cast")) and (fresh or _unread(old, "performance"))
        if lips or moves:
            found = takejudges.judged(
                job.work / take["file"], line=line if lips else None, on_camera=moves
            )
            judged = {**(old.get("judged") or {}), **(found.get("judged") or {})}
            take["readings"] = {**old, "judged": judged}
            if found.get("rank") is not None:
                take["readings"]["rank"] = found["rank"]
        take.setdefault("readings", {})
        if "+" in str(take.get("model")) and "repaint_mouth_kept" not in take["readings"]:
            kept = repaint_kept(job, take, line)
            if kept is not None:
                take["readings"]["repaint_mouth_kept"] = kept
    job.write("takes", data)


def look(job: Job, shot: str, again: bool = False) -> None:
    """The comparing judges (`judges.look`) over every bench take of the shot at once. They score
    takes against each other, so they run again whenever the set of takes changes, and their
    scores mean nothing for a take judged in another set."""
    made = benched(job, shot)
    if not judges.configured("look") or len(made) < 2:
        return
    record = job.work / "bench" / f"{shot}.look.json"
    names = [t["n"] for t in made]
    if not again and record.exists() and json.loads(record.read_text()).get("takes") == names:
        return
    paths = [job.work / t["file"] for t in made]
    scores, notes = judges.score("look", paths)
    for note in notes:
        print(f"{job.id} {shot}: {note}", file=sys.stderr)
    data = takes.load(job)
    by_n = {t["n"]: t for t in data["shots"][shot]["takes"]}
    stale = tuple(f"{j.name}." for j in judges.configured("look"))
    for n, path in zip(names, paths, strict=True):
        found = by_n[n].setdefault("readings", {})
        kept = {k: v for k, v in (found.get("judged") or {}).items() if not k.startswith(stale)}
        found["judged"] = {**kept, **scores[path]}
    job.write("takes", data)
    record.parent.mkdir(exist_ok=True)
    record.write_text(json.dumps({"takes": names}) + "\n")


def judged_by_person(job: Job, shot: str, made: list[Take]) -> bool:
    """Whether a person has given a verdict on any of these takes. Until then the engine's
    readings and pick are kept from them, so its pick cannot steer the verdict it is held to."""
    from . import verdicts

    shown = {t["n"] for t in made}
    for entry in verdicts.load(job.folder):
        named = {entry.get("take"), entry.get("preferred"), entry.get("over")} - {None}
        if entry.get("shot") == shot and named & shown:
            return True
    return False


def revealed_mark(job: Job, shot: str) -> Path:
    """Written when a person asks to see the engine's pick before giving a verdict."""
    return job.work / "bench" / f"{shot}.revealed"


def _cell(value: Any) -> str:
    return f"{value:.3g}" if isinstance(value, float) else str(value)


def table(made: list[Take], ranking: list[dict[str, Any]], found: dict[str, Any]) -> str:
    """Every take as a row, every reading as a column: the ranking ones first, then the rest."""
    names = [r["reading"] for r in ranking]
    others = sorted(
        {k for t in made for k in ((t.get("readings") or {}).get("judged") or {})} - set(names)
    ) + ["shot_motion", "repaint_mouth_kept"]
    others = [k for k in others if any(reading(t, k) is not None for t in made)]
    score = {r["n"]: r["score"] for r in found["order"]}
    head = ["panel", "take", "model", "made at", "cost", *names, *others, "score", "note"]
    rows = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for i, t in enumerate(made):
        w, h = reading(t, "width"), reading(t, "height")
        cells = [
            i + 1,
            t["n"],
            short(str(t.get("model"))),
            f"{w:.0f}x{h:.0f}" if w and h else "",
            f"${t['cost']:.2f}" if t.get("cost") else "",
            *[_cell(reading(t, k)) if reading(t, k) is not None else "" for k in names + others],
            _cell(score[t["n"]]) if t["n"] in score else "",
            found["left_out"].get(t["n"], ""),
        ]
        rows.append("| " + " | ".join(str(c) for c in cells) + " |")
    return "\n".join(rows)


def write(
    job: Job, shot: str, only: list[int] | None = None, again: bool = False, reveal: bool = False
) -> dict[str, Any]:
    """Judge what is missing (or everything, with `again`), then write the labelled side by side,
    the table, and the pick with its reason beside the bench's takes. The readings and the pick
    go in the report a person reads only once they have given a verdict on these takes, or ask
    to see them (`reveal`, which is marked, so a verdict given after it is known to be seen)."""
    beat = _beat(job, shot)
    line = _line(job, beat)
    rejudge(job, shot, only, fresh=again)
    look(job, shot, again)
    made = benched(job, shot, only)
    if not made:
        raise ContractError(f"{job.id}: {shot} has no bench takes to report on")
    ranking, close = rules("sing" if line else "video")
    prof = config.profile(job.job.get("profile") or "short-9x16")
    floor = int(prof.get("character_source_min_px") or 0) if beat.get("cast") else 0
    found = rank(made, ranking, close, floor)
    video = side_by_side(job, shot, made, line)
    report = {
        "job_id": job.id,
        "shot": shot,
        "panels": [t["n"] for t in made],
        "ranking": ranking,
        **found,
        "video": str(video),
    }
    folder = job.work / "bench"
    (folder / f"{shot}.report.json").write_text(json.dumps(report, indent=2) + "\n")
    said = {
        "pick": f"pick: take {found['pick']}",
        "close": "close: a person decides",
        "unsure": "no pick",
        "none": "no pick",
    }[found["status"]]
    panels = ", ".join(f"take {t['n']} ({short(str(t.get('model')))})" for t in made)
    shown = reveal or judged_by_person(job, shot, made)
    if reveal and not judged_by_person(job, shot, made):
        revealed_mark(job, shot).write_text(json.dumps({"takes": report["panels"]}) + "\n")
    report["shown"] = shown
    if shown:
        body = f"{said}. {found['reason']}.\n\n{table(made, ranking, found)}"
    else:
        body = (
            "The engine's readings and pick are kept from you until you give a verdict on these "
            "takes, so they cannot steer it: `kalainova verdict <job> accept --reviewer NAME "
            f"--shot {shot} --best N --among {','.join(map(str, report['panels']))} --aspect "
            "overall`. Then run `kalainova bench-report` again, or pass --reveal to see them now."
        )
    text = f"# Bench {shot}\n\nPanels left to right: {panels}.\n\n{body}\n"
    (folder / f"{shot}.report.md").write_text(text)
    return report
