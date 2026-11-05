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

from .. import config, media
from ..jobfs import ContractError, Job
from ..providers import base
from . import analyze, beats, notes as notes_mod

PROFILES = {"reel": "short-9x16", "square": "square", "landscape": "landscape", "long": "landscape"}
BEATS_PER_SHOT = {"fast": 2, "medium": 4, "cinematic": 8}
MIN_QUALITY = 0.45


# ------------------------------------------------------------------ direction file
def direction(job: Job) -> dict:
    p = job.folder / "direction.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"schema_version": "0.1", "job_id": job.id, "notes": [], "settings": dict(notes_mod.DEFAULTS)}


def add_note(job: Job, text: str) -> dict:
    d = direction(job)
    d["notes"].append({"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "text": text})
    (job.folder / "direction.json").write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    return d


def _llm(job: Job):
    try:
        p = base.resolve("llm", config.preference("llm", job.job))
    except LookupError:
        return None
    return p


def settle(job: Job, footage: dict) -> dict:
    d = direction(job)
    shots = [{"id": s["id"], "name": next(x["name"] for x in footage["sources"] if x["id"] == s["source"])}
             for s in footage["shots"]]
    d["settings"] = notes_mod.resolve([n["text"] for n in d["notes"]], shots=shots, llm=_llm(job))
    (job.folder / "direction.json").write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n")
    return d["settings"]


# ------------------------------------------------------------------ helpers
def defects(shot: dict) -> list[str]:
    """Reasons an editor would reject this take outright, whatever its average score."""
    sc, out = shot["scores"], []
    # absolute camera jitter (px/frame² at 160 px analysis width): steady < 1, handheld ~2, shaky > 3
    if shot["kind"] == "video" and (shot.get("jitter_px", 0) > 3.0 or (sc["shake"] > 0.7 and shot.get("jitter_px", 9) > 1.5)):
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
    lum = sum(shot["series"]["lum"]) / max(len(shot["series"]["lum"]), 1) if shot["series"]["lum"] else 0.46
    lum = min(max(lum, 0.05), 0.95)
    return round(min(max(math.log(0.46) / math.log(lum), 0.75), 1.5), 3)


def _order(shots: list[dict], s: dict, sources: dict) -> list[dict]:
    if s["order"] == "chronological":
        ordered = sorted(shots, key=lambda x: (x["source"], x["in_sec"]))
    elif s["order"] == "best_first":
        ordered = sorted(shots, key=lambda x: -x["quality"])
    else:  # story: strongest moving shot as the hook, the rest in capture order, calm wide to close
        rest = sorted(shots, key=lambda x: (x["source"], x["in_sec"]))
        hook = max(rest, key=lambda x: x["quality"] + 0.25 * x["scores"]["motion"]) if rest else None
        rest = [x for x in rest if x is not hook]
        closer = max(rest, key=lambda x: x["quality"] - 0.3 * x["scores"]["motion"]) if len(rest) > 2 else None
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
    from ..assets import _gen
    p, res = _gen(job, "music", "music", prompt, job.work / "music.wav", duration=duration, est={"duration": duration})
    return {"id": "music", "kind": "audio", "role": "music", "path": "music.wav",
            "duration_sec": media.duration(job.work / "music.wav"), "rights": job.job.get("rights", "owned"),
            "provider": p.name, "model": res.model, "prompt": prompt, "synthetic": True}, p.name


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
    k = BEATS_PER_SHOT[s["pace"]]
    if s["pace"] == "fast" and period < 0.42:
        k = 4
    shot_len = min(max(k * period, 0.8), 6.0)
    beat_times = grid["beats"] if grid else [i * period for i in range(int(target / period) + 2)]

    # a pool of distinct moments: every usable shot offers non-overlapping windows of one shot length
    pool: list[dict] = []
    for rank, shot in enumerate(ordered):
        if shot["kind"] == "still":
            pool.append({"shot": shot, "rank": rank, "take": 0, "a": 0.0})
            continue
        span = shot["out_sec"] - shot["in_sec"]
        n_win = max(1, int(span // max(shot_len, 0.8)))
        for w in range(n_win):
            pool.append({"shot": shot, "rank": rank, "take": w, "a": shot["in_sec"] + w * span / n_win,
                         "b": shot["in_sec"] + (w + 1) * span / n_win})
    # story order first: each shot's best moment in shot order, then second moments, and so on
    pool.sort(key=lambda m: (m["take"], m["rank"]))

    cuts, t, i, last_src = [], 0.0, 0, None
    first_beat = next((b for b in beat_times if b > 0.05), 0.0) if beat_times else 0.0
    while t < target - 0.4 and pool:
        # never the same take twice in a row when another take is available
        pick = next((m for m in pool if m["shot"]["source"] != last_src), pool[0])
        pool.remove(pick)
        shot = pick["shot"]
        want = t + shot_len if i else max(first_beat + shot_len, shot_len)
        end = min((b for b in beat_times if b >= want - period * 0.5), default=want, key=lambda b: abs(b - want))
        end = min(end, target)
        if end - t < 0.6:
            break
        length = end - t
        speed = 0.6 if s["slow_motion"] and shot["kind"] == "video" and shot["scores"]["motion"] > 0.5 else 1.0
        if shot["kind"] == "video":
            avail = pick["b"] - pick["a"]
            if avail < length * speed:
                speed = 1.0
            need = min(length * speed, avail)
            if need < length * speed * 0.6:  # this moment is too short for the beat; shorten the cut to it
                end = t + need / speed
                length = end - t
            a, _ = analyze.best_window(shot, need, pick["a"], pick["b"])
            out_sec = round(a + need, 3)
        else:
            a, out_sec = 0.0, round(length, 3)
        cut = {"id": f"cut-{i:02d}", "source": shot["source"], "in_sec": round(a, 3), "out_sec": out_sec,
               "role": "hook" if i == 0 else "body", "start_sec": round(t, 3), "crop_x": shot["subject_x"],
               "grade": s["grade"], "gamma": _gamma(shot), "shot_id": shot["id"]}
        if speed != 1.0:
            cut["speed"] = speed
        if shot["kind"] == "still":
            cut["motion"] = ["push_in", "drift_up", "pan_right"][i % 3]
        if s["original_audio"] and shot["kind"] == "video" and sources[shot["source"]].get("has_audio") and speed == 1.0:
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
            sil = [(a, b) for a, b in media.silencedetect(path, -38, 0.55) if b - a >= 0.55]
            keep, cur = [], 0.0
            for a, b in sil:
                if a - cur > 0.25:
                    keep.append((max(cur - 0.08, 0), min(a + 0.12, dur)))
                cur = b
            if dur - cur > 0.25:
                keep.append((max(cur - 0.08, 0), dur))
        for j, (a, b) in enumerate(keep):
            shot = min(footage["shots"], key=lambda x: abs(x["in_sec"] - a) if x["source"] == src["id"] else 1e9)
            cut = {"id": f"cut-{n:03d}", "source": src["id"], "in_sec": round(a, 3), "out_sec": round(b, 3),
                   "role": "body", "start_sec": round(t, 3), "crop_x": shot.get("subject_x", 0.5), "grade": s["grade"],
                   "gamma": _gamma(shot), "keep_audio": bool(src.get("has_audio"))}
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
        a = {"id": sid, "kind": "video" if src["kind"] == "video" else "still", "role": "visual", "path": src["path"],
             "rights": "licensed" if licensed else job.job.get("rights", "owned"),
             "provider": "operator", "synthetic": False}
        if src.get("duration_sec"):
            a["duration_sec"] = round(src["duration_sec"], 3)
        assets.append(a)
    assets += extra_assets
    job.write("asset_manifest", {"schema_version": "0.1", "job_id": job.id, "assets": assets, "duration_sec": total,
                                 "timeline": [{"beat_id": c["id"], "start_sec": c["start_sec"],
                                               "end_sec": round(cuts[k + 1]["start_sec"] if k + 1 < len(cuts) else total, 3)}
                                              for k, c in enumerate(cuts)]})

    beats_ = []
    for c in cuts:
        label = c.get("title") or sources[c["source"]]["name"].rsplit(".", 1)[0].replace("_", " ")
        beats_.append({"id": c["id"], "role": c["role"], "text": label, **({"on_screen": c["title"]} if c.get("title") else {})})
    job.write("script_packet", {"schema_version": "0.1", "job_id": job.id, "title": s["title"] or job.id,
                                "format": "edit", "target_duration_sec": s["duration_sec"], "beats": beats_,
                                "publish": {"title": (s["title"] or job.id)[:100], "description": _credits(job), "hashtags": []}})

    studio_cuts = [{k: v for k, v in c.items() if k != "shot_id"} for c in cuts]
    audio = {}
    if extra_assets:
        audio["music_asset_id"] = "music"
        audio["music_gain_db"] = -24.0 if s["original_audio"] else -12.0
        audio["duck"] = bool(s["original_audio"])
    em = {
        "schema_version": "0.1", "job_id": job.id, "runtime": "ffmpeg", "duration_sec": total,
        "profile": {"aspect": prof.get("aspect", "9:16"), "width": int(prof["width"]), "height": int(prof["height"]),
                    "fps": float(prof.get("fps", 30)), "target_lufs": float(prof.get("target_lufs", -14)),
                    "true_peak_dbtp_max": float(prof.get("true_peak_dbtp_max", -1))},
        "theme": "studio",
        "transition": "dissolve" if s["pace"] == "cinematic" else "cut",
        "caption_style": "studio" if words else "none",
        "cuts": studio_cuts, "captions": [], "overlays": [], "audio": audio,
        "original_audio": bool(s["original_audio"]),
        "fade_out_sec": 0.8 if s["format"] != "long" else 1.2,
    }
    if grid:
        em["beat_grid"] = {"bpm": grid["bpm"], "confidence": grid["confidence"]}
    job.write("edit_manifest", em)
    note = None
    if total < s["duration_sec"] - 1:
        note = (f"footage supports {total:.1f}s of distinct moments at this pace (asked {s['duration_sec']:.0f}s); "
                "add clips, choose a slower pace, or allow repeats")
    return {"settings": s, "cuts": len(cuts), "duration_sec": total, "bpm": grid.get("bpm") if grid else None,
            "note": note}
