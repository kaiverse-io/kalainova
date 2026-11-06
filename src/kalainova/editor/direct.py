"""DIRECT. footage.json + direction notes -> script_packet, asset_manifest, edit_manifest.

Reels (reel / square / landscape): pick shots, cut on the music's beat, trim each shot to its
steadiest window, reframe to the target aspect around the subject, match exposure, grade, title.
Long form: keep the speech, cut dead air, hide jump cuts with alternating punch-ins, chapter title.
The output is the same contract the generated pipeline uses, so compile/render/qa/approve/publish
are shared.
"""

from __future__ import annotations

import datetime as dt
import json
import math

import numpy as np

from .. import config, media
from ..jobfs import ContractError, Job
from ..providers import router
from . import analyze, beats
from . import notes as notes_mod

PROFILES = {"reel": "short-9x16", "square": "square", "landscape": "landscape", "long": "landscape"}
# Beats per shot. An edit that cuts every N beats is a metronome, so each pace has a phrase it repeats.
BEAT_PHRASE = {
    "fast": [2, 2, 4, 2, 2, 6],
    "medium": [4, 4, 2, 2, 4, 8],
    "cinematic": [8, 8, 4, 12, 8],
}
MIN_QUALITY = 0.45
MAX_ENLARGE = 2.0  # past this, a source reads as soft on any good screen
SIMILAR_MIN_CORR = 0.9  # shots this alike read as the same shot twice
# Pauses in speech: leave short ones, shorten long ones, and never leave a sliver between two cuts.
MIN_PAUSE_TO_CUT_SEC = 0.9
PAUSE_KEPT_SEC = 0.3
MIN_SPEECH_SEC = 1.5


# ------------------------------------------------------------------ direction file
def direction(job: Job) -> dict:
    p = job.folder / "direction.json"
    if p.exists():
        return json.loads(p.read_text())
    return {
        "schema_version": "0.1",
        "job_id": job.id,
        "notes": [],
        "settings": dict(notes_mod.DEFAULTS),
    }


def add_note(job: Job, text: str) -> dict:
    d = direction(job)
    d["notes"].append({"at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "text": text})
    (job.folder / "direction.json").write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    return d


def _llm(job: Job):
    if not router.available(job, "llm"):
        return None

    class Billed:
        """The notes parser's LLM, with the same cap and ledger as every other call."""

        def llm(self, prompt: str, **kw):
            return router.generate(job, "llm", "llm", prompt, note="notes", **kw)[1]

    return Billed()


def settle(job: Job, footage: dict) -> dict:
    d = direction(job)
    shots = [
        {
            "id": s["id"],
            "name": next(x["name"] for x in footage["sources"] if x["id"] == s["source"]),
        }
        for s in footage["shots"]
    ]
    d["settings"] = notes_mod.resolve([n["text"] for n in d["notes"]], shots=shots, llm=_llm(job))
    (job.folder / "direction.json").write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    return d["settings"]


# ------------------------------------------------------------------ helpers
def defects(shot: dict) -> list[str]:
    """Reasons an editor would reject this take outright, whatever its average score."""
    sc, out = shot["scores"], []
    # absolute camera jitter (px/frame² at 160 px analysis width): steady < 1, handheld ~2, shaky > 3
    if shot["kind"] == "video" and (
        shot.get("jitter_px", 0) > 3.0 or (sc["shake"] > 0.7 and shot.get("jitter_px", 9) > 1.5)
    ):
        out.append("shaky")
    if shot["kind"] == "video" and sc["sharpness"] < 0.15:
        out.append("soft focus")
    if sc["exposure"] < 0.35:
        out.append("badly exposed")
    return out


def _matches(shot: dict, sources: dict, needle: str) -> bool:
    needle = needle.lower().strip()
    if not needle:
        return False
    name = sources[shot["source"]]["name"].lower()
    return needle == shot["id"] or needle == shot["source"] or needle in name


def _gamma(shot: dict) -> float:
    """A small exposure nudge for a shot that is truly off. Night stays night."""
    lum = shot["series"]["lum"]
    level = sum(lum) / len(lum) if lum else 0.46
    if 0.15 <= level <= 0.75:
        return 1.0
    level = min(max(level, 0.05), 0.95)
    # A gamma above 1 brightens, so the exponent that lands on mid-grey is log(level) / log(mid-grey).
    return round(min(max(math.log(level) / math.log(0.46), 0.85), 1.25), 3)


def beats_for(pace: str, index: int) -> int:
    phrase = BEAT_PHRASE[pace]
    return phrase[index % len(phrase)]


def _looks_like(a: list[float], b: list[float]) -> bool:
    x, y = np.array(a, np.float64), np.array(b, np.float64)
    if x.size != y.size or x.std() == 0 or y.std() == 0:
        return False
    return float(np.corrcoef(x, y)[0, 1]) >= SIMILAR_MIN_CORR


def next_moment(
    pool: list[dict],
    used: list[list[float]],
    last_source: str | None,
    *,
    usage: dict[str, int] | None = None,
    need: float = 0.0,
) -> dict | None:
    """The next moment unlike anything used. None means the footage has run out of new shots.

    It leans to the source used least, so two clips never just trade turns, and to a shot long enough
    for the length the rhythm wants, so the rhythm survives contact with the footage.
    """
    fresh = [m for m in pool if not any(_looks_like(m["shot"].get("sig", []), sig) for sig in used)]
    if not fresh:
        return None
    counts = usage or {}

    def rank(m: dict) -> tuple[bool, bool, int]:
        shot = m["shot"]
        span = shot.get("out_sec", 0) - shot.get("in_sec", 0)
        return (span < need, shot["source"] == last_source, counts.get(shot["source"], 0))

    return min(fresh, key=rank)


def speech_keeps(silences: list[tuple[float, float]], duration: float) -> list[tuple[float, float]]:
    """What to keep of a take. Speech is never cut, and each long pause keeps a natural breath."""
    keep: list[tuple[float, float]] = []
    start = 0.0
    for a, b in silences:
        if b - a < MIN_PAUSE_TO_CUT_SEC:
            continue
        end = a + PAUSE_KEPT_SEC / 2
        if end - start >= MIN_SPEECH_SEC:
            keep.append((round(start, 3), round(end, 3)))
            start = b - PAUSE_KEPT_SEC / 2
    keep.append((round(start, 3), round(duration, 3)))
    return keep


def _order(shots: list[dict], s: dict, sources: dict) -> list[dict]:
    if s["order"] == "chronological":
        ordered = sorted(shots, key=lambda x: (x["source"], x["in_sec"]))
    elif s["order"] == "best_first":
        ordered = sorted(shots, key=lambda x: -x["quality"])
    else:  # story: strongest moving shot as the hook, the rest in capture order, calm wide to close
        rest = sorted(shots, key=lambda x: (x["source"], x["in_sec"]))
        hook = (
            max(rest, key=lambda x: x["quality"] + 0.25 * x["scores"]["motion"]) if rest else None
        )
        rest = [x for x in rest if x is not hook]
        closer = (
            max(rest, key=lambda x: x["quality"] - 0.3 * x["scores"]["motion"])
            if len(rest) > 2
            else None
        )
        rest = [x for x in rest if x is not closer]
        ordered = ([hook] if hook else []) + rest + ([closer] if closer else [])
    for key, pos in (("start_with", 0), ("end_with", -1)):
        if s[key]:
            hit = next((x for x in ordered if _matches(x, sources, s[key])), None)
            if hit:
                ordered.remove(hit)
                ordered.insert(len(ordered) if pos == -1 else 0, hit)
    return ordered


def _gen_music(job: Job, prompt: str, duration: float) -> tuple[dict, str]:
    p, res = router.generate(
        job,
        "music",
        "music",
        prompt,
        job.work / "music.wav",
        duration=duration,
        est={"duration": duration},
    )
    return {
        "id": "music",
        "kind": "audio",
        "role": "music",
        "path": "music.wav",
        "duration_sec": media.duration(job.work / "music.wav"),
        "rights": job.job.get("rights", "owned"),
        "provider": p.name,
        "model": res.model,
        "prompt": prompt,
        "synthetic": True,
    }, p.name


# ------------------------------------------------------------------ reel
def _reel(job: Job, footage: dict, s: dict) -> tuple[list, list, dict, list, float]:
    sources = {x["id"]: x for x in footage["sources"]}
    shots = [x for x in footage["shots"] if not any(_matches(x, sources, d) for d in s["drop"])]
    good = [x for x in shots if x["quality"] >= MIN_QUALITY and not defects(x)]
    clean = [x for x in shots if not defects(x)]
    # prefer good takes; then any defect-free take; a defective take only if nothing clean exists
    shots = good if len(good) >= 3 else (clean or sorted(shots, key=lambda x: -x["quality"])[:3])
    if s["only_best"] and len(shots) > 4:
        shots = sorted(shots, key=lambda x: -x["quality"])[: max(4, int(len(shots) * 0.6))]
    if not shots:
        raise ContractError(f"{job.id}: no usable shots after drops")
    ordered = _order(shots, s, sources)

    target = float(s["duration_sec"])
    assets_extra, grid = [], None
    if s["music_on"]:
        music, _ = _gen_music(job, s["music"], target + 2)
        assets_extra.append(music)
        grid = beats.beat_grid(job.work / "music.wav", target + 2)
    period = 60 / grid["bpm"] if grid else 0.5
    # at a fast tempo every beat is too quick to read a picture, so count in twos
    tempo_factor = 2 if s["pace"] == "fast" and period < 0.42 else 1
    beat_times = grid["beats"] if grid else [i * period for i in range(int(target / period) + 2)]

    # one moment per shot, in story order: the window inside it is chosen once its length is known
    pool: list[dict] = [
        {"shot": shot, "a": shot["in_sec"], "b": shot["out_sec"]} for shot in ordered
    ]

    cuts, t, i, last_src = [], 0.0, 0, None
    used_looks: list[list[float]] = []
    usage: dict[str, int] = {}
    first_beat = next((b for b in beat_times if b > 0.05), 0.0) if beat_times else 0.0
    while t < target - 0.4 and pool:
        shot_len = min(max(beats_for(s["pace"], i) * tempo_factor * period, 0.8), 8.0)
        pick = next_moment(pool, used_looks, last_src, usage=usage, need=shot_len)
        if pick is None:  # no new picture left, and the note below tells the operator
            break
        pool.remove(pick)
        shot = pick["shot"]
        used_looks.append(shot.get("sig", []))
        usage[shot["source"]] = usage.get(shot["source"], 0) + 1
        want = t + shot_len if i else max(first_beat + shot_len, shot_len)
        end = min(
            (b for b in beat_times if b >= want - period * 0.5),
            default=want,
            key=lambda b: abs(b - want),
        )
        end = min(end, target)
        if end - t < 0.6:
            break
        length = end - t
        speed = (
            0.6
            if s["slow_motion"] and shot["kind"] == "video" and shot["scores"]["motion"] > 0.5
            else 1.0
        )
        if shot["kind"] == "video":
            avail = pick["b"] - pick["a"]
            if avail < length * speed:
                speed = 1.0
            need = min(length * speed, avail)
            if (
                need < length * speed * 0.6
            ):  # this moment is too short for the beat; shorten the cut to it
                end = t + need / speed
                length = end - t
            a, _ = analyze.best_window(shot, need, pick["a"], pick["b"])
            out_sec = round(a + need, 3)
        else:
            a, out_sec = 0.0, round(length, 3)
        cut = {
            "id": f"cut-{i:02d}",
            "source": shot["source"],
            "in_sec": round(a, 3),
            "out_sec": out_sec,
            "role": "hook" if i == 0 else "body",
            "start_sec": round(t, 3),
            "crop_x": shot["subject_x"],
            "grade": s["grade"],
            "gamma": _gamma(shot),
            "shot_id": shot["id"],
        }
        if speed != 1.0:
            cut["speed"] = speed
        if shot["kind"] == "still":
            cut["motion"] = ["push_in", "drift_up", "pan_right"][i % 3]
        if (
            s["original_audio"]
            and shot["kind"] == "video"
            and sources[shot["source"]].get("has_audio")
            and speed == 1.0
        ):
            cut["keep_audio"] = True
        cuts.append(cut)
        t, i, last_src = end, i + 1, shot["source"]
    if cuts:
        cuts[-1]["role"] = "payoff"
        if s["title"]:
            cuts[0]["title"] = s["title"]
        if s["end_card"]:
            cuts[-1]["title"] = s["end_card"]
    return cuts, assets_extra, grid or {}, [], round(t, 3)


# ------------------------------------------------------------------ long form
def _long(job: Job, footage: dict, s: dict) -> tuple[list, list, dict, list, float]:
    sources = [x for x in footage["sources"] if x["kind"] == "video"]
    cuts, t, n = [], 0.0, 0
    for src in sources:
        if any(d in src["name"].lower() or d == src["id"] for d in s["drop"]):
            continue
        path = job.work / src["path"]
        dur = src["duration_sec"]
        keep = [(0.0, dur)]
        if s["remove_silence"] and src.get("has_audio"):
            keep = speech_keeps(media.silencedetect(path, -38, MIN_PAUSE_TO_CUT_SEC), dur)
        for j, (a, b) in enumerate(keep):
            shot = min(
                footage["shots"],
                key=lambda x: abs(x["in_sec"] - a) if x["source"] == src["id"] else 1e9,
            )
            cut = {
                "id": f"cut-{n:03d}",
                "source": src["id"],
                "in_sec": round(a, 3),
                "out_sec": round(b, 3),
                "role": "body",
                "start_sec": round(t, 3),
                "crop_x": shot.get("subject_x", 0.5),
                "grade": s["grade"],
                "gamma": _gamma(shot),
                "keep_audio": bool(src.get("has_audio")),
            }
            # a jump cut inside one take gets a punch-in on alternate segments, the pro way to hide it
            if j % 2 == 1:
                cut["zoom"] = 1.08
            cuts.append(cut)
            t += b - a
            n += 1
    if not cuts:
        raise ContractError(f"{job.id}: no long-form footage")
    cuts[0]["role"] = "hook"
    if s["title"]:
        cuts[0]["title"] = s["title"]
    extra = []
    if s["music_on"]:
        music, _ = _gen_music(job, s["music"], min(t + 1, 600))
        extra.append(music)
    return cuts, extra, {}, [], round(t, 3)


def _too_small(cuts: list[dict], sources: dict, prof: dict) -> list[str]:
    """Sources this edit has to enlarge past what still looks sharp, named for the operator."""
    found = set()
    for cut in cuts:
        src = sources[cut["source"]]
        fit = max(
            prof["width"] / max(src.get("width", 1), 1),
            prof["height"] / max(src.get("height", 1), 1),
        )
        if fit > MAX_ENLARGE:
            found.add(src["name"])
    return sorted(found)


def _credits(job: Job) -> str:
    from .. import stock

    return stock.credits(job)


# ------------------------------------------------------------------ run
def run(job: Job) -> dict:
    footage_path = job.folder / "footage.json"
    if not footage_path.exists():
        raise ContractError(f"{job.id}: run `kalainova ingest` first")
    footage = json.loads(footage_path.read_text())
    s = settle(job, footage)
    builder = _long if s["format"] == "long" else _reel
    cuts, extra_assets, grid, words, total = builder(job, footage, s)
    prof = config.profile(PROFILES[s["format"]])
    sources = {x["id"]: x for x in footage["sources"]}

    assets = []
    for sid in sorted({c["source"] for c in cuts}):
        src = sources[sid]
        licensed = src["name"].split("_")[1:2] in (["pexels"], ["pixabay"])
        a = {
            "id": sid,
            "kind": "video" if src["kind"] == "video" else "still",
            "role": "visual",
            "path": src["path"],
            "rights": "licensed" if licensed else job.job.get("rights", "owned"),
            "provider": "operator",
            "synthetic": False,
        }
        if src.get("duration_sec"):
            a["duration_sec"] = round(src["duration_sec"], 3)
        assets.append(a)
    assets += extra_assets
    job.write(
        "asset_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "assets": assets,
            "duration_sec": total,
            "timeline": [
                {
                    "beat_id": c["id"],
                    "start_sec": c["start_sec"],
                    "end_sec": round(cuts[k + 1]["start_sec"] if k + 1 < len(cuts) else total, 3),
                }
                for k, c in enumerate(cuts)
            ],
        },
    )

    beats_ = []
    for c in cuts:
        label = c.get("title") or sources[c["source"]]["name"].rsplit(".", 1)[0].replace("_", " ")
        beats_.append(
            {
                "id": c["id"],
                "role": c["role"],
                "text": label,
                **({"on_screen": c["title"]} if c.get("title") else {}),
            }
        )
    job.write(
        "script_packet",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "title": s["title"] or job.id,
            "format": "edit",
            "target_duration_sec": s["duration_sec"],
            "beats": beats_,
            "publish": {
                "title": (s["title"] or job.id)[:100],
                "description": _credits(job),
                "hashtags": [],
            },
        },
    )

    studio_cuts = [{k: v for k, v in c.items() if k != "shot_id"} for c in cuts]
    audio = {}
    if extra_assets:
        audio["music_asset_id"] = "music"
        audio["music_gain_db"] = -24.0 if s["original_audio"] else -12.0
        audio["duck"] = bool(s["original_audio"])
    em = {
        "schema_version": "0.1",
        "job_id": job.id,
        "runtime": "ffmpeg",
        "duration_sec": total,
        "profile": {
            "aspect": prof.get("aspect", "9:16"),
            "width": int(prof["width"]),
            "height": int(prof["height"]),
            "fps": float(prof.get("fps", 30)),
            "target_lufs": float(prof.get("target_lufs", -14)),
            "true_peak_dbtp_max": float(prof.get("true_peak_dbtp_max", -1)),
        },
        "theme": "studio",
        "transition": "dissolve" if s["pace"] == "cinematic" else "cut",
        "caption_style": "studio" if words else "none",
        "cuts": studio_cuts,
        "captions": [],
        "overlays": [],
        "audio": audio,
        "original_audio": bool(s["original_audio"]),
        "speech": s["format"] == "long",
        "fade_out_sec": 0.8 if s["format"] != "long" else 1.2,
    }
    if grid:
        em["beat_grid"] = {"bpm": grid["bpm"], "confidence": grid["confidence"]}
    job.write("edit_manifest", em)
    notes = []
    if total < s["duration_sec"] - 1:
        notes.append(
            f"footage supports {total:.1f}s of distinct moments at this pace (asked {s['duration_sec']:.0f}s); "
            "add clips or choose a slower pace"
        )
    tiny = _too_small(cuts, sources, prof)
    if tiny:
        notes.append(
            f"sources too small for {prof['width']}x{prof['height']}: {tiny}. No edit can hide that"
        )
    return {
        "settings": s,
        "cuts": len(cuts),
        "duration_sec": total,
        "bpm": grid.get("bpm") if grid else None,
        "note": "; ".join(notes) or None,
    }
