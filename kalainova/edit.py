"""ASSET -> EDIT. Builds edit_manifest.json: timeline, motion, captions, overlays, audio.

Retention defaults (override on job.edit):
  * a new visual every beat, motion on every still (no static frames)
  * kinetic captions, 1-3 words per card, emphasis words colored
  * hook card over the first ~1.6s, progress bar the whole piece
  * music ducked under voice, a whoosh on each beat change
"""

from __future__ import annotations

import re

from . import config
from .jobfs import Job

MOTIONS = ["push_in", "pan_left", "push_out", "pan_right", "drift_up"]


def caption_cards(words: list[dict], emphasis: set[str], max_words: int = 3, max_chars: int = 14) -> list[dict]:
    cards, cur = [], []

    def flush():
        if cur:
            text = " ".join(w["text"] for w in cur)
            emph = [w["text"] for w in cur if re.sub(r"\W", "", w["text"]).lower() in emphasis]
            card = {"start_sec": cur[0]["start_sec"], "end_sec": cur[-1]["end_sec"], "text": text,
                    "words": [{"text": w["text"], "start_sec": w["start_sec"], "end_sec": w["end_sec"]} for w in cur]}
            if emph:
                card["emphasis"] = emph
            cards.append(card)
            cur.clear()

    for w in words:
        trial = " ".join(x["text"] for x in cur + [w])
        if cur and (len(cur) >= max_words or len(trial) > max_chars):
            flush()
        cur.append(w)
        if re.search(r"[.!?,;:]$", w["text"]):
            flush()
    flush()
    # close tiny gaps so captions don't flicker
    for a, b in zip(cards, cards[1:]):
        if 0 < b["start_sec"] - a["end_sec"] < 0.25:
            a["end_sec"] = b["start_sec"]
    return cards


def run(job: Job, *, force: bool = False) -> dict:
    if job.has("edit_manifest") and not force:
        return job.read("edit_manifest")
    data = job.job
    packet = job.read("script_packet")
    am = job.read("asset_manifest")
    opts = data.get("edit") or {}
    prof = config.profile(data.get("profile") or "short-9x16")
    by_id = {a["id"]: a for a in am["assets"]}
    beats = {b["id"]: b for b in packet["beats"]}

    cuts = []
    for i, span in enumerate(am["timeline"]):
        bid = span["beat_id"]
        beat = beats[bid]
        dur = round(span["end_sec"] - span["start_sec"], 3)
        src = by_id.get(f"{bid}.video") or by_id.get(f"{bid}.still")
        if not src:
            continue
        cut = {"id": f"cut-{bid}", "source": src["id"], "in_sec": 0, "out_sec": dur, "role": beat["role"],
               "start_sec": span["start_sec"]}
        if src["kind"] == "still":
            cut["motion"] = MOTIONS[i % len(MOTIONS)]
        if src["kind"] == "video" and src.get("duration_sec", dur) < dur:
            cut["out_sec"] = round(src["duration_sec"], 3)
            cut["hold_last_frame"] = True
        # typecards already carry the headline; titles only go over generated imagery/video
        if beat.get("on_screen") and i > 0 and src.get("model") != "local-typecard":
            cut["title"] = beat["on_screen"]
        cuts.append(cut)

    emphasis = {re.sub(r"\W", "", w).lower() for b in packet["beats"] for w in b.get("emphasis", [])}
    captions = caption_cards(am.get("words", []), emphasis) if opts.get("captions", True) else []

    overlays = []
    hook = packet["beats"][0]
    hook_text = hook.get("on_screen") or (packet.get("hooks") or [hook["text"]])[0]
    if hook_text:
        overlays.append({"kind": "hook_card", "text": hook_text, "start_sec": 0, "end_sec": min(1.6, am["duration_sec"])})
    if opts.get("progress_bar", True):
        overlays.append({"kind": "progress_bar", "start_sec": 0, "end_sec": am["duration_sec"]})

    audio: dict = {}
    if "voice" in by_id:
        audio["voice_asset_id"] = "voice"
    if "music" in by_id:
        audio["music_asset_id"] = "music"
        audio["music_gain_db"] = float(opts.get("music_gain_db", -19))
        audio["duck"] = True
    if "whoosh" in by_id and opts.get("whoosh", True):
        audio["sfx"] = [{"asset_id": "whoosh", "start_sec": max(0, c["start_sec"] - 0.25), "gain_db": -14} for c in cuts[1:]]

    manifest = {
        "schema_version": "0.1",
        "job_id": data["job_id"],
        "runtime": "ffmpeg",
        "duration_sec": am["duration_sec"],
        "profile": {
            "aspect": prof.get("aspect", "9:16"),
            "width": int(prof.get("width", 1080)),
            "height": int(prof.get("height", 1920)),
            "fps": float(prof.get("fps", 30)),
            "target_lufs": float(prof.get("target_lufs", -14)),
            "true_peak_dbtp_max": float(prof.get("true_peak_dbtp_max", -1)),
        },
        "caption_style": opts.get("caption_style", "kinetic"),
        "cuts": cuts,
        "captions": captions,
        "overlays": overlays,
        "audio": audio,
    }
    job.write("edit_manifest", manifest)
    return manifest
