"""A finished piece in another language, over its own music and effects.

Each line is translated to fit its time, voiced, and placed where the original was. The flow follows
ShortGPT's translation engine (MIT); the difference is that the original's voice never leaks
through, because the engine kept a music-and-effects stem. A dub is a job of its own, with its own
human gate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import media, prompts, render
from .jobfs import ContractError, Job, open_child
from .providers import router

Cue = dict[str, Any]
SLOWEST, FASTEST = 0.85, 1.3  # how far a line can be stretched before it stops sounding like speech
ME_STEM = "me.stem.wav"
TRANSLATION_FILE = "translation.json"
DUB_GAIN_DB = 0.0


def cues_of(job: Job) -> list[Cue]:
    """The lines to dub, with their times, from the cut's closed captions."""
    em = job.read("edit_manifest")
    cues = em.get("closed_captions") or em.get("captions") or []
    return [
        {
            "id": n,
            "start_sec": float(c["start_sec"]),
            "end_sec": float(c["end_sec"]),
            "text": c["text"],
        }
        for n, c in enumerate(cues)
    ]


def translate(job: Job, cues: list[Cue], language: str) -> list[Cue]:
    """A model's translation, or a file the agent wrote. Every line has to come back."""
    from .plan import extract_json

    saved = job.folder / f"{TRANSLATION_FILE}.{language}"
    if saved.exists():
        reply: dict[str, Any] = json.loads(saved.read_text())
    elif router.available(job, "llm"):
        request = [
            {"id": c["id"], "seconds": round(c["end_sec"] - c["start_sec"], 2), "text": c["text"]}
            for c in cues
        ]
        text = prompts.load("dub_translate").format(
            language=language, cues=json.dumps(request, ensure_ascii=False)
        )
        _, res = router.generate(job, "llm", "llm", text, max_tokens=4000, note=f"dub {language}")
        reply = extract_json(res.text)
        saved.write_text(json.dumps(reply, indent=2, ensure_ascii=False) + "\n")
    else:
        raise ContractError(f"{job.id}: no LLM provider is ready. Have the agent write {saved}.")
    lines = {int(c["id"]): str(c["text"]) for c in reply.get("cues", [])}
    missing = [c["id"] for c in cues if c["id"] not in lines]
    if missing:
        raise ContractError(f"{job.id}: the translation left out cues {missing}")
    return [{**c, "text": lines[c["id"]]} for c in cues]


def tempo_for(spoken: float, slot: float) -> float:
    """How much to speed a line up or slow it down to fit, within what still sounds like speech."""
    if spoken <= 0 or slot <= 0:
        return 1.0
    return max(SLOWEST, min(FASTEST, spoken / slot))


def _voice_lines(
    job: Job, cues: list[Cue], folder: Path, voice: str | None
) -> list[tuple[Cue, Path]]:
    out = []
    for cue in cues:
        raw = folder / f"{cue['id']:04d}.raw.wav"
        router.generate(
            job,
            "voice",
            "voice",
            cue["text"],
            raw,
            voice=voice,
            est={"chars": len(cue["text"])},
            note="dub",
        )
        fitted = folder / f"{cue['id']:04d}.wav"
        slot = cue["end_sec"] - cue["start_sec"]
        tempo = tempo_for(media.duration(raw), slot)
        media.run(
            ["-i", str(raw), "-af", f"atempo={tempo:.3f}", "-ar", "48000", "-ac", "2", str(fitted)]
        )
        out.append((cue, fitted))
    return out


def _mix(lines: list[tuple[Cue, Path]], bed: Path | None, length: float, dst: Path) -> None:
    inputs: list[str] = []
    chains, labels = [], []
    for n, (cue, path) in enumerate(lines):
        inputs += ["-i", str(path)]
        delay = int(cue["start_sec"] * 1000)
        chains.append(f"[{n}:a]adelay={delay}|{delay}[v{n}]")
        labels.append(f"[v{n}]")
    if bed:
        inputs += ["-i", str(bed)]
        labels.append(f"[{len(lines)}:a]")
    graph = ";".join(
        [
            *chains,
            f"{''.join(labels)}amix=inputs={len(labels)}:normalize=0,atrim=0:{length:.3f}[out]",
        ]
    )
    media.run(
        [*inputs, "-filter_complex", graph, "-map", "[out]", "-ar", "48000", "-ac", "2", str(dst)]
    )


def _lay_new_sound(job: Job, child: Job, lines: list[tuple[Cue, Path]], profile: str) -> None:
    """The new lines over the old music and effects, under the old picture, not re-encoded."""
    final = job.work / "final.mp4"
    stem = job.work / ME_STEM
    mix = child.work / "mix.wav"
    _mix(lines, stem if stem.exists() else None, media.duration(final), mix)
    targets = _targets(profile)
    master = child.work / "mix.norm.wav"
    media.master_loudness(mix, master, targets[0], targets[1])
    media.run(
        ["-i", str(final), "-i", str(master), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart",
         "-metadata", "comment=Made with Kalainova; contains AI-generated media",
         str(child.work / "final.mp4")]
    )  # fmt: skip


def run(
    job: Job,
    language: str,
    new_id: str,
    *,
    voice: str | None = None,
    lipsync: bool = False,
) -> Job:
    """Open a new job holding this piece dubbed. The picture is copied; only the sound changes."""
    final = job.work / "final.mp4"
    if not final.exists():
        raise ContractError(f"{job.id}: render the piece first")
    cues = cues_of(job)
    if not cues:
        raise ContractError(f"{job.id}: this piece has no captions, so nothing says what to dub")
    translated = translate(job, cues, language)
    source = job.job
    child = open_child(
        job,
        new_id,
        profile=source.get("profile") or "short-9x16",
        brief={"subject": f"{job.id} in {language}", "language": language},
    )
    lines_dir = child.work / "lines"
    lines_dir.mkdir(exist_ok=True)
    lines = _voice_lines(child, translated, lines_dir, voice)
    _lay_new_sound(job, child, lines, source.get("profile") or "")
    if lipsync:
        _lipsync(job, child)
    _record(child, translated, language, job.id)
    render.stamp(child, child.work / "final.mp4")
    child.set_status("rendered")
    return child


def _lipsync(job: Job, child: Job) -> None:
    """Match mouths on the dubbed picture to the new mix, when a lipsync provider is ready."""
    if not router.available(child, "lipsync"):
        raise ContractError(f"{job.id}: lipsync requested but no lipsync provider is configured")
    synced = child.work / "final.lipsync.mp4"
    router.generate(
        child,
        "lipsync",
        "lipsync",
        str(child.work / "final.mp4"),
        str(child.work / "mix.norm.wav"),
        synced,
        note="dub lipsync",
    )
    synced.replace(child.work / "final.mp4")


def _targets(profile_name: str) -> tuple[float, float]:
    from . import config

    prof = config.profile(profile_name)
    return float(prof.get("target_lufs", -14)), float(prof.get("true_peak_dbtp_max", -1))


def _record(child: Job, cues: list[Cue], language: str, parent: str) -> None:
    from . import captions

    child.write(
        "asset_manifest",
        {
            "schema_version": "0.1",
            "job_id": child.id,
            "assets": [
                {
                    "id": "picture",
                    "kind": "video",
                    "role": "visual",
                    "path": "final.mp4",
                    "rights": child.job["rights"],
                    "provider": "track",
                    "model": f"the picture of {parent}",
                    "synthetic": True,
                },
                {
                    "id": "voice",
                    "kind": "audio",
                    "role": "voice",
                    "path": "mix.wav",
                    "rights": child.job["rights"],
                    "provider": _voice_provider(child),
                    "model": _voice_model(child),
                    "synthetic": True,
                },
            ],
        },
    )
    closed = [{k: c[k] for k in ("start_sec", "end_sec", "text")} for c in cues]
    for name, text in captions.sidecars(closed, 24.0, language).items():
        (child.work / name).write_text(text)


def _generation(child: Job) -> dict[str, Any]:
    path = child.folder / router.GENERATIONS
    entries = (
        [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []
    )
    return dict(entries[-1]) if entries else {}


def _voice_provider(child: Job) -> str:
    return str(_generation(child).get("provider") or "local")


def _voice_model(child: Job) -> str:
    return str(_generation(child).get("model") or "local-voice")
