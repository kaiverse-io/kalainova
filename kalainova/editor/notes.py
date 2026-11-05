"""Direction notes -> edit settings.

The operator talks like an editor ("30s reel, warm, fast cuts, start with the sunset, drop the shaky one,
title: Three days in the hills"). Notes accumulate in direction.json; later notes override earlier ones.
An LLM parses notes when a key exists; this rule parser is the always-available fallback and also
validates whatever the LLM returns, so settings are always from the closed vocabulary below.
"""

from __future__ import annotations

import json
import re

FORMATS = ("reel", "square", "landscape", "long")
PACES = ("fast", "medium", "cinematic")
GRADES = ("natural", "warm", "cool", "teal_orange", "film", "bw", "vivid")
ORDERS = ("story", "chronological", "best_first")

DEFAULTS = {
    "format": "reel",
    "duration_sec": 30,
    "pace": "medium",
    "grade": "natural",
    "order": "story",
    "music": "warm cinematic instrumental, gentle build, no vocals",
    "music_on": True,
    "original_audio": False,
    "captions": True,
    "title": "",
    "end_card": "",
    "slow_motion": False,
    "drop": [],
    "start_with": "",
    "end_with": "",
    "only_best": False,
    "remove_silence": True,
}

GRADE_WORDS = {
    "teal_orange": ["teal", "orange and teal", "blockbuster", "hollywood"],
    "warm": ["warm", "warmer", "golden", "cozy", "sunny"],
    "cool": ["cool", "cooler", "cold", "colder", "blue tone", "icy", "moody blue"],
    "film": ["film", "filmic", "analog", "kodak", "grain", "vintage", "nostalgic"],
    "bw": ["black and white", "b&w", "monochrome", "noir", "bw"],
    "vivid": ["vivid", "punchy", "saturated", "vibrant", "more color", "more colour"],
    "natural": ["natural", "true to life", "clean grade", "no grade"],
}


def _dur(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)\s*(s|sec|secs|seconds|m|min|mins|minutes)\b", text)
    if not m:
        return None
    v = float(m.group(1))
    return v * 60 if m.group(2).startswith("m") else v


def parse(text: str, settings: dict | None = None) -> dict:
    s = dict(settings or DEFAULTS)
    low = text.lower()
    if (d := _dur(low)) is not None:
        s["duration_sec"] = max(5.0, min(d, 3600.0))
    if re.search(r"\b(long[- ]?form|youtube video|vlog|full video|episode)\b", low):
        s["format"], s["original_audio"] = "long", True
    elif re.search(r"\b(square|1:1|feed post)\b", low):
        s["format"] = "square"
    elif re.search(r"\b(landscape|16:9|horizontal|widescreen)\b", low):
        s["format"] = "landscape"
    elif re.search(r"\b(reel|short|shorts|vertical|9:16|tiktok|story)\b", low):
        s["format"] = "reel"
    if re.search(r"\b(fast|quick|snappy|energetic|hype|punchy cuts|faster)\b", low):
        s["pace"] = "fast"
    if re.search(r"\b(slow|cinematic|calm|relaxed|breathe|slower|dreamy)\b", low):
        s["pace"] = "cinematic"
    if re.search(r"\b(medium pace|normal pace|balanced)\b", low):
        s["pace"] = "medium"
    for grade, words in GRADE_WORDS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", low) for w in words):
            s["grade"] = grade
    if re.search(r"\b(chronological|in order|timeline order|as it happened)\b", low):
        s["order"] = "chronological"
    if re.search(r"\b(best first|strongest first|lead with the best)\b", low):
        s["order"] = "best_first"
    if re.search(r"\b(no music|without music|mute music)\b", low):
        s["music_on"] = False
    elif m := re.search(r"music\s*[:=]\s*([^.;\n]+)", text, re.I):
        s["music"], s["music_on"] = m.group(1).strip(), True
    if re.search(r"\b(keep (the )?(original|natural|real) (audio|sound)|original audio|ambient sound|nat sound)\b", low):
        s["original_audio"] = True
    if re.search(r"\b(no captions|without captions|no subtitles)\b", low):
        s["captions"] = False
    elif re.search(r"\b(captions|subtitles)\b", low):
        s["captions"] = True
    if m := re.search(r"title\s*[:=]\s*[\"“]?([^\"”\n]+?)[\"”]?\s*(?:$|[.;\n])", text, re.I):
        s["title"] = m.group(1).strip()
    if re.search(r"\bno title\b", low):
        s["title"] = ""
    if m := re.search(r"end(?:ing)? card\s*[:=]\s*[\"“]?([^\"”\n]+?)[\"”]?\s*(?:$|[.;\n])", text, re.I):
        s["end_card"] = m.group(1).strip()
    if re.search(r"\b(slow[- ]?mo|slow motion|speed ramp)\b", low):
        s["slow_motion"] = True
    if re.search(r"\bno slow[- ]?mo\b", low):
        s["slow_motion"] = False
    for m in re.finditer(r"\b(?:drop|remove|cut|lose|skip)\s+(?:the\s+)?([\w.\-]+(?:\s+(?:shot|clip|one|photo))?)", low):
        target = re.sub(r"\s+(shot|clip|one|photo)$", "", m.group(1))
        if target not in ("the", "silence", "silences", "pauses", "dead", "music", "captions") and target not in s["drop"]:
            s["drop"] = s["drop"] + [target]
    if m := re.search(r"\b(?:start|open|begin) with\s+(?:the\s+)?([\w.\-]+)", low):
        s["start_with"] = m.group(1)
    if m := re.search(r"\b(?:end|close|finish) (?:with|on)\s+(?:the\s+)?([\w.\-]+)", low):
        s["end_with"] = m.group(1)
    if re.search(r"\b(only (the )?best|best shots only|tight selects)\b", low):
        s["only_best"] = True
    if re.search(r"\b(keep (the )?pauses|keep silences|don't cut silence)\b", low):
        s["remove_silence"] = False
    return s


def validate(raw: dict) -> dict:
    """Clamp anything (LLM output included) into the closed vocabulary."""
    s = dict(DEFAULTS)
    for k, v in (raw or {}).items():
        if k not in DEFAULTS:
            continue
        default = DEFAULTS[k]
        if k == "format" and v in FORMATS or k == "pace" and v in PACES or k == "grade" and v in GRADES \
                or k == "order" and v in ORDERS:
            s[k] = v
        elif k == "duration_sec" and isinstance(v, (int, float)) and not isinstance(v, bool):
            s[k] = float(max(5, min(v, 3600)))
        elif isinstance(default, bool) and isinstance(v, bool):
            s[k] = v
        elif k in ("music", "title", "end_card", "start_with", "end_with") and isinstance(v, str):
            s[k] = v[:120]
        elif k == "drop" and isinstance(v, list):
            s[k] = [str(x)[:60] for x in v][:50]
    return s


LLM_PROMPT = """You are a senior film editor's assistant. Convert the editor's notes into settings JSON.
Keys (only these): format (reel|square|landscape|long), duration_sec (number), pace (fast|medium|cinematic),
grade (natural|warm|cool|teal_orange|film|bw|vivid), order (story|chronological|best_first), music (text),
music_on (bool), original_audio (bool), captions (bool), title (text), end_card (text), slow_motion (bool),
drop (list of shot ids or file-name fragments), start_with, end_with (shot id or file-name fragment),
only_best (bool), remove_silence (bool).
Current settings: {current}
Shots available (id: file): {shots}
Notes, oldest first (later notes override): {notes}
Return JSON only."""


def resolve(notes: list[str], *, shots: list[dict] | None = None, llm=None) -> dict:
    s = dict(DEFAULTS)
    for n in notes:
        s = parse(n, s)
    if llm is not None:
        try:
            from ..plan import extract_json
            res = llm.llm(LLM_PROMPT.format(current=json.dumps(s), notes=json.dumps(notes),
                                            shots=json.dumps({x["id"]: x.get("name", "") for x in shots or []})),
                          max_tokens=800)
            s = validate({**s, **extract_json(res.text)})
        except Exception:
            pass  # rules already produced a valid answer
    return validate(s)
