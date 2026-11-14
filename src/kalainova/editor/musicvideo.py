"""A job that cuts a video to a finished track: lyric lines where there are lyrics, musical
structure where there are not, a short excerpt on request, and the cost said before anything runs.

Generated motion does not follow a tempo, so none is promised. The edit supplies the feel: cuts on
bars, whole-bar shot lengths, a push-in where the energy jumps.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import config, consistency, media, shots, streams, takes
from ..jobfs import ContractError, Job, open_child
from ..providers import router
from . import musiccuts as mc

Say = Callable[[str], None]
FULL_LENGTH_SEC = 90.0  # past this, default to stills with a few moving shots
FULL_LENGTH_MOVING = 6
FADE_IN_SEC, FADE_OUT_SEC = 0.25, 0.5
FEW_CUES = 2
RIGHTS_FOR = {
    "funded-clip": {"funded-brief"},
    "owned-derivative": {"owned", "licensed"},
    "client": {"licensed"},
}


def lyric_spans(
    cues: list[dict[str, Any]], title: str, length: float, grid: list[float]
) -> list[mc.Span]:
    """One shot per lyric line, starting on the beat. An instrumental stretch gets its own."""
    spans: list[mc.Span] = []
    at = 0.0
    for cue in cues:
        asked = float(cue["start_sec"])
        start = min(grid, key=lambda b: abs(b - asked)) if grid else asked
        if start - at > 1.0:
            spans.append({"start": at, "end": start, "text": ""})
            at = start
        if spans and start <= at and spans[-1]["text"]:
            spans[-1]["text"] += f" / {cue['text']}"
            continue
        spans.append({"start": at, "end": start, "text": cue["text"]})
        at = start
    spans.append({"start": at, "end": length, "text": spans[-1]["text"] if spans else title})
    return [{**s, "strong": False} for s in spans if s["end"] - s["start"] > 0.2]


def _visual(song: dict[str, Any], span: mc.Span) -> str:
    sections = song.get("sections") or []
    named = [s for s in sections if s.get("bars")]
    if span.get("section") is not None and span["section"] < len(named):
        if named[span["section"]].get("visual"):
            return str(named[span["section"]]["visual"])
    first = span["text"].split(" / ")[0]
    for section in sections:
        if first and first in (section.get("lines") or []):
            return str(section.get("visual") or span["text"] or song["style"])
    return str(song["style"])


def beats_for(
    song: dict[str, Any],
    spans: list[mc.Span],
    kinds: list[str],
    cast: list[str] | None = None,
    silent: bool = False,
) -> list[dict[str, Any]]:
    out = []
    for n, span in enumerate(spans):
        text = "" if (silent or song.get("instrumental")) else (span["text"] or song["title"])
        beat: dict[str, Any] = {
            "id": f"s{n:02d}",
            "role": "hook" if n == 0 else ("payoff" if n == len(spans) - 1 else "body"),
            "text": text,
            "visual_cue": _visual(song, span),
            "visual_kind": kinds[n],
            "duration_sec": round(span["end"] - span["start"], 3),
        }
        if cast:
            beat["cast"] = list(cast)
        shot: dict[str, str] = {}
        if span.get("angle"):
            shot["size"] = span["angle"]
        if span.get("strong"):
            shot["camera"] = "a short push in as the energy lifts"
        if shot:
            beat["shot"] = shot
        out.append(beat)
    return out


def _kinds(spans: list[mc.Span], still_only: bool, moving: int | None) -> list[str]:
    if still_only:
        return ["still"] * len(spans)
    if moving is None or moving >= len(spans):
        return ["video"] * len(spans)
    step = len(spans) / max(moving, 1)
    chosen = {int(i * step) for i in range(moving)}
    return ["video" if n in chosen else "still" for n in range(len(spans))]


def estimate(
    job: Job,
    spans: list[mc.Span],
    kinds: list[str],
    pad: float,
    say: Say,
    cap: float | None = None,
    only: list[str] | None = None,
    model: str | None = None,
) -> float:
    """Shots, seconds, and the price of the moving ones, said before any call. Refuses past the cap.
    Each clip is priced at its generated length: the slot plus a beat to trim from."""
    moving = [s for s, k in zip(spans, kinds, strict=True) if k == "video"]
    seconds = sum(s["end"] - s["start"] for s in spans)
    total, unpriced = 0.0, False
    for span in moving:
        quote = router.quote(
            job,
            "video",
            duration=span["end"] - span["start"] + pad,
            image=True,
            references=True,
            only=only,
            model=model,
        )
        if quote is None or quote[1] is None:
            unpriced = True
        else:
            total += quote[1]
    say(
        f"{len(spans)} shots, {seconds:.1f}s, {len(moving)} moving: about ${total:.2f}"
        + (" (some shots have no ready, priced provider)" if unpriced else "")
    )
    limit = cap if cap is not None else job.job.get("cost_cap")
    if limit is not None and total > float(limit):
        raise ContractError(
            f"{job.id}: this video is estimated at ${total:.2f}, over the ${float(limit):.2f} cap;"
            " ask for a shorter excerpt, use --stills, or raise cost_cap"
        )
    return total


def _excerpt_audio(src: Path, dst: Path, a: float, b: float, profile: str) -> dict[str, Any]:
    """The excerpt cut from the mastered file, faded at each end, then levelled for the profile."""
    prof = config.profile(profile)
    raw = dst.with_name("excerpt.raw.wav")
    span = b - a
    fade = f"afade=t=in:d={FADE_IN_SEC},afade=t=out:st={span - FADE_OUT_SEC:.3f}:d={FADE_OUT_SEC}"
    media.run(["-ss", f"{a:.3f}", "-t", f"{span:.3f}", "-i", str(src), "-af", fade, str(raw)])
    media.master_loudness(
        raw, dst, float(prof.get("target_lufs", -14)), float(prof.get("true_peak_dbtp_max", -1))
    )
    raw.unlink(missing_ok=True)
    return {**media.loudness(dst), "target_lufs": prof.get("target_lufs", -14)}


def _resolve_stream(
    job: Job, stream: str, new_id: str, cast: list[str] | None
) -> tuple[dict[str, Any], list[str], dict[str, Any], dict[str, list[str]] | None, str | None]:
    root = job.folder.parent.parent
    stream_data = streams.load(root, stream)
    if "video" not in (stream_data.get("media") or []):
        raise ContractError(f"stream {stream!r} does not make video")
    track_rights = job.job.get("rights")
    strategy = str(stream_data.get("strategy", ""))
    allowed = RIGHTS_FOR.get(strategy)
    if allowed and track_rights not in allowed:
        raise ContractError(
            f"track rights {track_rights!r} do not cover stream {stream!r} strategy {strategy!r}"
        )
    if track_rights == "funded-brief" and strategy != "funded-clip":
        raise ContractError(f"track rights 'funded-brief' cannot be used on strategy {strategy!r}")
    resolved = consistency.resolve(root, stream_data)
    chosen = consistency.choose_cast(resolved, cast)
    consistency.preflight(resolved, stream_data, chosen)
    kit_lock = consistency.build_lock(resolved, stream_data, new_id, chosen)
    pins = stream_data.get("generators") or {}
    stream_providers = {cap: [pin["provider"]] for cap, pin in pins.items()} if pins else None
    vpin = pins.get("video")
    stream_video_model = vpin.get("model") if vpin else None
    return stream_data, chosen, kit_lock, stream_providers, stream_video_model


def build(
    job: Job,
    new_id: str,
    *,
    song: dict[str, Any],
    cues: list[dict[str, Any]],
    words: list[dict[str, Any]],
    final: Path,
    manifest: dict[str, Any],
    profile: str,
    still_only: bool,
    excerpt: dict[str, Any] | None = None,
    phrase_bars: int | None = None,
    stream: str | None = None,
    cast: list[str] | None = None,
    say: Say = print,
) -> Path:
    stream_data, chosen, kit_lock, stream_providers, stream_video_model = (
        _resolve_stream(job, stream, new_id, cast) if stream else (None, None, None, None, None)
    )

    length = media.duration(final)
    take = takes.chosen(job, "song")
    saved_grid = None
    if take:
        gp = (job.work / take["file"]).with_suffix(".grid.json")
        if gp.exists():
            saved_grid = json.loads(gp.read_text())
    found = mc.analyse(final, length, saved_grid=saved_grid)
    by_music = len(cues) < FEW_CUES
    if by_music:
        mc.refuse_if_unclear(found, "cannot cut this track to its music")
    spans = (
        mc.music_spans(found, length, song, phrase_bars)
        if by_music
        else lyric_spans(cues, song["title"], length, found["beats"])
    )
    brief_in = job.job.get("brief") or {}
    stream_id = stream or job.job.get("stream")
    ceiling = (
        shots.character_ceiling({"profile": profile, "brief": brief_in}) if stream_id else None
    )
    if by_music:
        spans = mc.split_for_ceiling(spans, found, ceiling)
    notes = list(found["notes"])
    a, b = 0.0, length
    if excerpt:
        a, b = mc.window(found, float(excerpt["length"]), excerpt.get("start"))
        spans = mc.clip_to_window(spans, a, b)
    grid = [round(t - a, 3) for t in found["beats"] if a - 1e-6 <= t <= b + 1e-6]
    full = not excerpt and length > FULL_LENGTH_SEC
    moving = FULL_LENGTH_MOVING if full and not still_only else None
    if full and not still_only:
        say(
            f"full length ({length:.0f}s): stills with camera moves, and {FULL_LENGTH_MOVING}"
            " moving shots, so the price stays inside a cap"
        )
    kinds = _kinds(spans, still_only, moving)
    pad = (60 / found["bpm"]) if found["bpm"] else 0.5
    cost = estimate(
        job,
        spans,
        kinds,
        pad,
        say,
        cap=stream_data.get("cost_cap_per_job") if stream_data else None,
        only=stream_providers.get("video") if stream_providers else None,
        model=stream_video_model,
    )
    for note in notes:
        say(f"note: {note}")
    max_moving = kinds.count("video")
    brief = {
        "subject": brief_in.get("subject", song["title"]),
        "narration": False,
        "track": "track.wav",
        "track_model": manifest["assets"][0].get("model", "a finished track"),
        "words": [
            {**w, "start_sec": round(w["start_sec"] - a, 3), "end_sec": round(w["end_sec"] - a, 3)}
            for w in words
            if a <= w.get("start_sec", 0) < b
        ],
        "max_video_beats": max_moving,
        "visual_style": brief_in.get("visual_style", ""),
        "music_cuts": True,
    }
    track_rights = job.job.get("rights")
    child_rights = (
        "licensed"
        if track_rights == "licensed"
        else (stream_data.get("rights") if stream_data else None)
    )
    child = open_child(
        job,
        new_id,
        profile=profile,
        brief=brief,
        stream=stream,
        cast=chosen,
        strategy=stream_data.get("strategy") if stream_data else None,
        rights=child_rights,
        distribution_identity=stream_data.get("distribution_identity") if stream_data else None,
        cost_cap=stream_data.get("cost_cap_per_job") if stream_data else None,
        providers=stream_providers,
        kit_lock=kit_lock,
    )
    heard: dict[str, Any] = {}
    if excerpt and (a, b) != (0.0, length):
        heard = _excerpt_audio(final, child.work / "track.wav", a, b, profile)
    else:
        shutil.copyfile(final, child.work / "track.wav")
    cuts = [s["start"] for s in spans[1:]]
    (child.work / "music_cuts.json").write_text(
        json.dumps(
            {
                "beats": grid,
                "cuts": mc.cut_offsets(cuts, grid),
                "on_beat": mc.share_on_beat(cuts, grid),
                "window": [round(a, 3), round(b, 3)],
                "estimated_cost": round(cost, 4),
                "notes": notes,
                "loudness": heard,
            },
            indent=2,
        )
    )
    hooks_data = (
        {
            "hooks": [song["title"], f"{song['title']} (intro)", f"{song['title']} (hook)"],
            "chosen_hook": 0,
        }
        if stream
        else {}
    )
    child.write(
        "script_packet",
        {
            "schema_version": "0.1",
            "job_id": new_id,
            "title": song["title"],
            "beats": beats_for(
                song,
                spans,
                kinds,
                cast=chosen,
                silent=bool(stream_data and stream_data.get("silent")),
            ),
            **hooks_data,
            **({"publish": song["publish"]} if song.get("publish") else {}),
        },
    )
    return child.folder
