"""ASSET -> EDIT. Builds edit_manifest.json: timeline, motion, captions, overlays, audio.

Retention defaults (override on job.edit):
  * a new visual every beat, motion on every still (no static frames)
  * kinetic captions, 1-3 words per card, emphasis words colored
  * hook card over the first ~1.6s, progress bar the whole piece
  * music ducked under voice, a whoosh on each beat change
"""

from __future__ import annotations

import hashlib
import re

from . import config
from .jobfs import Job

MOTIONS = ["push_in", "pan_left", "push_out", "pan_right", "drift_up"]
STUDIO_MOTIONS = ["push_in", "drift_up", "push_in", "pan_right", "push_out"]  # slow, mostly forward
THEMES = ("studio", "bold")
PICTURE_LEAD_SEC = 0.08


def caption_cards(
    words: list[dict], emphasis: set[str], max_words: int = 3, max_chars: int = 14
) -> list[dict]:
    cards, cur = [], []

    def flush():
        if cur:
            text = " ".join(w["text"] for w in cur)
            emph = [w["text"] for w in cur if re.sub(r"\W", "", w["text"]).lower() in emphasis]
            card = {
                "start_sec": cur[0]["start_sec"],
                "end_sec": cur[-1]["end_sec"],
                "text": text,
                "words": [
                    {"text": w["text"], "start_sec": w["start_sec"], "end_sec": w["end_sec"]}
                    for w in cur
                ],
            }
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
    # no orphans: fold a lone-word card into its neighbour when the line still fits
    merged: list[dict] = []
    for card in cards:
        if (
            merged
            and len(card["words"]) == 1
            and len(merged[-1]["text"]) + 1 + len(card["text"]) <= max_chars + 6
            and card["start_sec"] - merged[-1]["end_sec"] < 0.35
        ):
            prev = merged[-1]
            prev["words"] += card["words"]
            prev["text"] = f"{prev['text']} {card['text']}"
            prev["end_sec"] = card["end_sec"]
            if card.get("emphasis"):
                prev["emphasis"] = prev.get("emphasis", []) + card["emphasis"]
            continue
        merged.append(card)
    cards = merged
    # close tiny gaps so captions don't flicker
    for a, b in zip(cards, cards[1:]):
        if 0 < b["start_sec"] - a["end_sec"] < 0.25:
            a["end_sec"] = b["start_sec"]
    return cards


def run(job: Job, *, force: bool = False) -> dict:
    cut_from = hashlib.sha256(job.path("asset_manifest").read_bytes()).hexdigest()
    if job.has("edit_manifest") and not force:
        kept = job.read("edit_manifest")
        if kept.get("asset_manifest_sha256") == cut_from:
            return kept  # new assets must never be cut with the old edit, and a hand edit stays
    data = job.job
    packet = job.read("script_packet")
    am = job.read("asset_manifest")
    opts = data.get("edit") or {}
    prof = config.profile(data.get("profile") or "short-9x16")
    by_id = {a["id"]: a for a in am["assets"]}
    beats = {b["id"]: b for b in packet["beats"]}
    theme = opts.get("theme", "studio")
    studio = theme == "studio"
    mezzanine = prof.get("delivery") == "mezzanine"
    wants_captions = opts.get("captions", True) and not mezzanine

    cuts = []
    for i, span in enumerate(am["timeline"]):
        bid = span["beat_id"]
        beat = beats[bid]
        dur = round(span["end_sec"] - span["start_sec"], 3)
        src = by_id.get(f"{bid}.video") or by_id.get(f"{bid}.still")
        if not src:
            continue
        cut = {
            "id": f"cut-{bid}",
            "source": src["id"],
            "in_sec": 0,
            "out_sec": dur,
            "role": beat["role"],
            # the picture changes just before the words do, the way a line is cut in a film
            "start_sec": max(span["start_sec"] - (PICTURE_LEAD_SEC if i else 0.0), 0.0),
            "grade": opts.get("grade", "natural"),
        }
        if src["kind"] == "still":
            cut["motion"] = (STUDIO_MOTIONS if studio else MOTIONS)[i % len(MOTIONS)]
        # A shot runs to where the next one starts, which is earlier than the next line's first word.
        next_start = (
            am["timeline"][i + 1]["start_sec"] - PICTURE_LEAD_SEC
            if i + 1 < len(am["timeline"])
            else span["end_sec"]
        )
        needed = round(next_start - cut["start_sec"], 3)
        if src["kind"] == "video":
            have = src.get("duration_sec", needed)
            cut["out_sec"] = round(min(have, needed), 3)
            if have < needed:
                cut["hold_last_frame"] = True
        # bold typecards bake their headline; everything else gets an animated title (studio: every beat)
        # Two lines of text at once is noise. With captions up, only the opening and closing keep a title.
        key_beat = i == 0 or i == len(am["timeline"]) - 1 or not wants_captions
        if (
            beat.get("on_screen")
            and src.get("model") != "local-typecard"
            and (studio or i > 0)
            and (key_beat or opts.get("titles") == "all")
        ):
            cut["title"] = beat["on_screen"]
        cuts.append(cut)

    emphasis = {
        re.sub(r"\W", "", w).lower() for b in packet["beats"] for w in b.get("emphasis", [])
    }
    cw, cc = (4, 22) if studio else (3, 14)
    captions = caption_cards(am.get("words", []), emphasis, cw, cc) if wants_captions else []
    closed = [
        {k: card[k] for k in ("start_sec", "end_sec", "text")}
        for card in caption_cards(am.get("words", []), set(), 14, 74)
    ]

    overlays = []
    hook = packet["beats"][0]
    hook_text = hook.get("on_screen") or (packet.get("hooks") or [hook["text"]])[0]
    if (
        hook_text and not studio
    ):  # studio: the first beat's hero title is the hook, never a second card
        overlays.append(
            {
                "kind": "hook_card",
                "text": hook_text,
                "start_sec": 0,
                "end_sec": min(1.6, am["duration_sec"]),
            }
        )
    if opts.get("progress_bar", not studio):
        overlays.append({"kind": "progress_bar", "start_sec": 0, "end_sec": am["duration_sec"]})

    audio: dict = {}
    if "voice" in by_id:
        audio["voice_asset_id"] = "voice"
    if "music" in by_id:
        audio["music_asset_id"] = "music"
        if "music_gain_db" in opts:
            audio["music_gain_db"] = float(opts["music_gain_db"])
        audio["duck"] = True
    if "whoosh" in by_id and opts.get("whoosh", not studio):
        audio["sfx"] = [
            {"asset_id": "whoosh", "start_sec": max(0, c["start_sec"] - 0.25), "gain_db": -14}
            for c in cuts[1:]
        ]

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
            "delivery": prof.get("delivery", "web"),
        },
        "theme": theme,
        "transition": opts.get("transition", "cut"),
        "caption_style": "none"
        if mezzanine
        else opts.get("caption_style", "studio" if studio else "kinetic"),
        "cuts": cuts,
        "captions": captions,
        "closed_captions": closed,
        "fade_in_sec": float(opts.get("fade_in_sec", 0.5 if mezzanine else 0.0)),
        "fade_out_sec": float(opts.get("fade_out_sec", 1.0 if mezzanine else 0.5)),
        "overlays": overlays,
        "audio": audio,
        "asset_manifest_sha256": cut_from,
    }
    job.write("edit_manifest", manifest)
    return manifest
