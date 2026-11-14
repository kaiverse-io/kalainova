"""SONGS. song.json -> takes -> the best one, mastered, with lyric files and a lyric video.

The model sings. The engine asks for several takes, reads them, keeps them all, and finishes the one
chosen: a master at the target level, stems when something can split them, lyrics timed to what was
really heard, and a job that cuts a lyric video to the track. A person chooses in the end, and a
person's choice stands.
"""

from __future__ import annotations

import difflib
import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

from . import captions, config, media, render, takes, writers
from .bar import song as musicbar
from .bar.readings import summarise
from .jobfs import ContractError, Job
from .providers import router
from .render import release
from .song_repair import repair_take as repair_take

Song = dict[str, Any]
Cue = dict[str, Any]
SHOT = "song"
SAFE_TAKES = {
    "takes": 2,
    "max_takes": 3,
}  # the best of several beats the first of one, in every test
IMITATION = re.compile(
    r"\b(?:in the style of|sounds? (?:just )?like|voice of|cover of|like (?:a )?(?:young|early) )",
    re.I,
)
FADE_SEC = 3.0
CAPTION_RATE = 24.0
INTRO_GUARD_SEC = 0.5
LEAST_LINE_SEC = 0.8
SECTION_NAMES = {"pre-chorus": "Pre-Chorus"}


def style_text(song: Song) -> str:
    parts = [str(song["style"])]
    if song.get("bpm"):
        parts.append(f"{song['bpm']:g} bpm")
    if song.get("key"):
        parts.append(str(song["key"]))
    return ", ".join(parts)


def lyrics_text(song: Song) -> str:
    """Words with their section tags, which is how every song model takes structure."""
    out = []
    for section in song["sections"]:
        out.append(f"[{SECTION_NAMES.get(section['kind'], str(section['kind']).title())}]")
        out += list(section.get("lines") or [])
    return "\n".join(out) + "\n"


def problems(song: Song) -> list[str]:
    """What must not reach a model at all."""
    found = []
    for text in (song["style"], song.get("avoid") or ""):
        if IMITATION.search(str(text)):
            found.append(f"the style asks to imitate someone ({text[:60]!r}); describe the sound")
    if not song.get("instrumental") and not musicbar.lyric_lines(song):
        found.append("a song with a voice needs lines; set instrumental if it has none")
    return found


def _heard(job: Job, path: Path) -> list[dict[str, Any]] | None:
    """What a listener would pick out, kept with the take. None when nothing can transcribe here."""
    saved = path.with_suffix(".heard.json")
    if saved.exists():
        return list(json.loads(saved.read_text()))
    if not router.available(job, "transcribe"):
        return None
    try:
        _, res = router.generate(
            job,
            "transcribe",
            "transcribe",
            path,
            est={"duration": media.duration(path)},
            note="lyrics",
        )
    except (router.ProviderError, OSError) as exc:
        print(f"{job.id}: could not hear the lyrics: {exc}")
        return None
    saved.write_text(json.dumps(res.words))
    return list(res.words)


def _generate(job: Job, song: Song, brief: dict[str, Any]) -> dict[str, Any]:
    lyrics = lyrics_text(song)
    style = style_text(song)
    seconds = float(song.get("duration_sec") or brief.get("duration_sec") or 120)

    def make(seed: int, dst: Path) -> tuple[Any, Any]:
        return router.generate(
            job,
            "song",
            "song",
            lyrics,
            dst,
            style=style,
            duration=seconds,
            seed=seed,
            sections=song["sections"],
            avoid=song.get("avoid") or "",
            bpm=song.get("bpm"),
            key=song.get("key"),
            language=song.get("language"),
            instrumental=bool(song.get("instrumental")),
            est={"duration": seconds},
            note="song",
        )

    def assess(path: Path) -> tuple[dict[str, Any], bool]:
        report = musicbar.measure(path, song, _heard(job, path))
        misses = [r["id"] for r in report["readings"] if not r["ok"]]
        return {
            "score": musicbar.score(report),
            "misses": misses,
            "readings": report["readings"],
        }, not misses

    counts = {**SAFE_TAKES, **{k: brief[k] for k in SAFE_TAKES if k in brief}}
    return takes.make_until_good(
        job, SHOT, counts, suffix=".wav", make=make, assess=assess, prompt=f"{style}\n{lyrics}"
    )


def _sounding_span(path: Path) -> tuple[float, float]:
    """Where the sound starts and stops, leaving out silence at either end."""
    left, right, sr = media.decode_stereo(path)
    level = np.abs((left + right) / 2)
    found = np.flatnonzero(level > media.SOUND_FLOOR)
    if not found.size:
        return 0.0, float(level.size / max(sr, 1))
    return float(found[0] / sr), float(found[-1] / sr)


def _estimated_cues(lines: list[str], start: float, end: float) -> list[Cue]:
    """No transcript: spread the lines through the track by how many words each has."""
    weights = [max(len(line.split()), 1) for line in lines]
    span = max(end - start - INTRO_GUARD_SEC, LEAST_LINE_SEC * len(lines))
    at = start + INTRO_GUARD_SEC
    cues = []
    for line, weight in zip(lines, weights, strict=True):
        length = span * weight / sum(weights)
        cues.append({"start_sec": round(at, 3), "end_sec": round(at + length, 3), "text": line})
        at += length
    return cues


def _tokens_by_line(lines: list[str]) -> tuple[list[str], list[int]]:
    tokens, owners = [], []
    for n, line in enumerate(lines):
        for token in re.findall(r"[a-z0-9']+", line.lower()):
            tokens.append(token)
            owners.append(n)
    return tokens, owners


def _matched_times(
    lines: list[str], heard: list[dict[str, Any]]
) -> dict[int, list[tuple[float, float]]]:
    """Each line's words, matched in order against what was heard."""
    tokens, owners = _tokens_by_line(lines)
    spoken = [re.sub(r"[^a-z0-9']", "", str(w.get("text", "")).lower()) for w in heard]
    matcher = difflib.SequenceMatcher(a=tokens, b=spoken, autojunk=False)
    times: dict[int, list[tuple[float, float]]] = {}
    for block in matcher.get_matching_blocks():
        for k in range(block.size):
            word = heard[block.b + k]
            spot = (float(word["start_sec"]), float(word["end_sec"]))
            times.setdefault(owners[block.a + k], []).append(spot)
    return times


def _fill_unheard(cues: list[Cue | None], lines: list[str], start: float, end: float) -> list[Cue]:
    """A line the transcript missed sits between its heard neighbours."""
    out: list[Cue] = []
    for n, cue in enumerate(cues):
        if cue:
            out.append(cue)
            continue
        before = out[-1]["end_sec"] if out else start
        after = next((c["start_sec"] for c in cues[n + 1 :] if c), end)
        out.append(
            {
                "start_sec": round(float(before), 3),
                "end_sec": round(float(max(after, before + LEAST_LINE_SEC)), 3),
                "text": lines[n],
            }
        )
    return out


def timed_lines(
    path: Path, song: Song, heard: list[dict[str, Any]] | None
) -> tuple[list[Cue], str]:
    """Each lyric line with its time, and whether that time was heard or estimated."""
    lines = musicbar.lyric_lines(song)
    start, end = _sounding_span(path)
    if not lines:
        return [], "none"
    if not heard:
        return _estimated_cues(lines, start, end), "estimated"
    times = _matched_times(lines, heard)
    if not times:
        return _estimated_cues(lines, start, end), "estimated"
    cues: list[Cue | None] = [
        {
            "start_sec": round(times[n][0][0], 3),
            "end_sec": round(times[n][-1][1], 3),
            "text": lines[n],
        }
        if n in times
        else None
        for n in range(len(lines))
    ]
    return _fill_unheard(cues, lines, start, end), "heard"


def _lrc_stamp(seconds: float) -> str:
    minutes, rest = divmod(max(seconds, 0.0), 60)
    return f"[{int(minutes):02d}:{rest:05.2f}]"


def _lrc(song: Song, cues: list[Cue]) -> str:
    head = f"[ti:{song['title']}]\n"
    return head + "\n".join(f"{_lrc_stamp(c['start_sec'])}{c['text']}" for c in cues) + "\n"


def _write_lyric_files(job: Job, song: Song, cues: list[Cue]) -> None:
    if not cues:
        return
    (job.work / "final.lrc").write_text(_lrc(song, cues))
    language = str(song.get("language") or "en")
    for name, text in captions.sidecars(cues, CAPTION_RATE, language).items():
        (job.work / name).write_text(text)


def _finish(job: Job, take_file: Path, song: Song) -> Path:
    """The chosen take as a master: rumble out, a clean end, and the target level, once."""
    prof = config.profile("song")
    target = float(prof.get("target_lufs", -14))
    ceiling = float(prof.get("true_peak_dbtp_max", -1))
    _, end = _sounding_span(take_file)
    grid_path = take_file.with_suffix(".grid.json")
    if grid_path.exists():
        grid = json.loads(grid_path.read_text())
    else:
        from .editor import musiccuts

        grid = musiccuts.analyse(take_file, media.duration(take_file))
    bars = [float(at) for at in grid.get("bars", []) if float(at) <= end]
    if len(bars) >= 2:
        bar_interval = float(np.median(np.diff(bars)))
        if bars[-1] + bar_interval <= end + 0.05:
            cut_at = bars[-1] + bar_interval
        else:
            cut_at = bars[-1]
        fade = min(2 * bar_interval, cut_at)
    else:
        cut_at = end
        fade = min(FADE_SEC, end / 4)
    fade_start = max(cut_at - fade, 0.0)
    cleaned = job.work / "song.clean.wav"
    media.run(
        [
            "-i",
            str(take_file),
            "-t",
            f"{cut_at:.3f}",
            "-af",
            f"highpass=f=25,afade=t=out:st={fade_start:.3f}:d={fade:.3f}",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-c:a",
            "pcm_s24le",
            str(cleaned),
        ]
    )  # fmt: skip
    final = job.work / "final.wav"
    media.master_loudness(cleaned, final, target, ceiling)
    tags = [
        "-metadata",
        f"title={song['title']}",
        "-metadata",
        "comment=contains AI-generated media",
    ]
    media.run(["-i", str(final), "-c:a", "aac", "-b:a", "256k", *tags, str(job.work / "final.m4a")])
    return final


def _stems(job: Job, final: Path) -> dict[str, str]:
    """Vocals and everything else, when a provider that can split them is listed."""
    if not router.available(job, "separate"):
        return {}
    vocals, rest = job.work / "vocals.wav", job.work / "instrumental.wav"
    try:
        router.generate(
            job,
            "separate",
            "separate",
            final,
            vocals,
            rest,
            est={"duration": media.duration(final)},
            note="stems",
        )
    except (router.ProviderError, OSError) as exc:
        print(f"{job.id}: no stems: {exc}")
        return {}
    return {"vocals": vocals.name, "instrumental": rest.name}


def run(job: Job) -> Path:
    writers.ensure(job, "song")
    song = job.read("song")
    refused = problems(song)
    if refused:
        raise ContractError(f"{job.id}: " + "; ".join(refused))
    brief = job.job.get("brief") or {}
    router.refuse_too_long(
        job, "song", float(song.get("duration_sec") or brief.get("duration_sec") or 120)
    )
    take = _generate(job, song, brief)
    take_file = job.work / take["file"]
    from .editor import musiccuts

    grid = musiccuts.analyse(take_file, media.duration(take_file))
    lyric_cues = timed_lines(take_file, song, _heard(job, take_file))[0]
    grid.update(
        section_boundaries=musiccuts.section_boundaries(song.get("sections") or []),
        timed_lyrics_cues=lyric_cues,
    )
    take_file.with_suffix(".grid.json").write_text(json.dumps(grid))
    if takes.load(job)["shots"][SHOT]["chosen_by"] == "none_passed":
        print(
            f"{job.id}: song: no take passed QA readings; using take {take['n']} as candidate",
            file=sys.stderr,
        )
    final = _finish(job, take_file, song)
    cues, timing = timed_lines(final, song, _heard(job, take_file))
    _write_lyric_files(job, song, cues)
    stems = _stems(job, final)
    released = release.for_job(job, song, lyrics_text(song))
    job.write(
        "asset_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "duration_sec": media.duration(final),
            "words": _cue_words(cues),
            "assets": [
                {
                    "id": "song",
                    "kind": "audio",
                    "role": "song",
                    "path": take["file"],
                    "duration_sec": media.duration(take_file),
                    "rights": job.job["rights"],
                    "provider": take["provider"],
                    "model": take["model"],
                    "prompt": take.get("prompt", ""),
                    "synthetic": True,
                    "provenance": {
                        **takes.provider_meta(take),
                        "lyric_timing": timing,
                        **({"stems": stems} if stems else {}),
                        "release": released,
                    },
                }
            ],
        },
    )
    render.stamp(job, final)
    job.set_status("rendered")
    return final


def _cue_words(cues: list[Cue]) -> list[dict[str, Any]]:
    """Each line's words spread across its time, so captions can follow along."""
    words = []
    for cue in cues:
        parts = str(cue["text"]).split()
        span = (float(cue["end_sec"]) - float(cue["start_sec"])) / max(len(parts), 1)
        for n, part in enumerate(parts):
            words.append(
                {
                    "start_sec": round(float(cue["start_sec"]) + n * span, 3),
                    "end_sec": round(float(cue["start_sec"]) + (n + 1) * span, 3),
                    "text": part,
                    "confidence": 0.7,
                }
            )
    return words


def checks(job: Job) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """QA for a finished song: its level blocks, and the rest informs the person who listens."""
    song = job.read("song")
    final = job.artifact()
    prof = config.profile("song")
    report = musicbar.measure(final, song, _heard_of_chosen(job))
    readings = [
        *musicbar.master_readings(
            final, float(prof.get("target_lufs", -14)), float(prof.get("true_peak_dbtp_max", -1))
        ),
        *report["readings"],
    ]
    out = [
        {
            "id": r["id"],
            "status": "pass" if r["ok"] else ("fail" if r["blocks"] else "warn"),
            "detail": f"{r['value']} (limit {r['limit']})",
        }
        for r in readings
    ]
    out.append(
        {
            "id": "song.taste",
            "status": "warn",
            "detail": "no reading can judge a song; a human listens",
        }
    )
    return out, summarise(readings)


def _heard_of_chosen(job: Job) -> list[dict[str, Any]] | None:
    take = takes.chosen(job, SHOT)
    if not take:
        return None
    saved = (job.work / take["file"]).with_suffix(".heard.json")
    return list(json.loads(saved.read_text())) if saved.exists() else None


# ------------------------------------------------------------------ a video for it
def video_job(
    job: Job,
    new_id: str,
    *,
    profile: str = "landscape",
    still_only: bool = False,
    excerpt: dict[str, Any] | None = None,
    phrase_bars: int | None = None,
    stream: str | None = None,
    cast: list[str] | None = None,
) -> Path:
    """Open a job that cuts a video to this song: every shot on a beat, the lyrics as captions.

    With few or no lyric lines the cuts come from the music's bars and phrases. An excerpt is
    {"length": seconds, "start": seconds or None}; no start means the strongest stretch."""
    from .editor import musicvideo

    song = job.read("song")
    final = job.artifact()
    if not final.exists():
        raise ContractError(f"{job.id}: make the song first")
    manifest = job.read("asset_manifest")
    cues = [
        {"start_sec": c["start_sec"], "end_sec": c["end_sec"], "text": c["text"]}
        for c in timed_lines(final, song, _heard_of_chosen(job))[0]
    ]
    return musicvideo.build(
        job,
        new_id,
        song=song,
        cues=cues,
        words=list(manifest.get("words") or []),
        final=final,
        manifest=manifest,
        profile=profile,
        still_only=still_only,
        excerpt=excerpt,
        phrase_bars=phrase_bars,
        stream=stream,
        cast=cast,
    )
