"""SONGS. song.json -> takes -> the best one, mastered, with lyric files and a lyric video.

The model sings. The engine asks for several takes, reads them, keeps them all, and finishes the one
chosen: a master at the target level, stems when something can split them, lyrics timed to what was
really heard, and a job that cuts a lyric video to the track. A person chooses in the end, and a
person's choice stands.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

from . import captions, config, genres, media, render, song_guide, song_lead, takes, writers
from .bar import judges
from .bar import song as musicbar
from .bar.readings import summarise
from .editor.singing import sounding_span
from .editor.singing import timed_lines as timed_lines
from .jobfs import ContractError, Job
from .providers import router, song_text
from .providers.contract import Guide, Pin, SeparateRequest, SongRequest, TranscribeRequest
from .render import release
from .song_repair import repair_take as repair_take

Song = dict[str, Any]
Cue = dict[str, Any]
SHOT = "song"
# One take, then more only while they are free (takes.make_until_good): a paid song is one take
# whose request is made right, and a weak section is repaired, not retaken (ADR 0031).
SAFE_TAKES = {"takes": 1, "max_takes": 3}
IMITATION = re.compile(
    r"\b(?:in the style of|sounds? (?:just )?like|voice of|cover of|like (?:a )?(?:young|early) )",
    re.I,
)
# A sound named after "no" is still named: a style is read for what it mentions (vendor prompt
# guides ask for positive descriptors), so what to keep out goes in `avoid`.
NEGATION = re.compile(r"\b(?:no|not|without|never|avoid|don't|zero)\s+[a-z][\w-]*", re.I)
FADE_SEC = 3.0
CAPTION_RATE = 24.0
# A line is sung as written: a stage direction among the lines would be sung too.
DIRECTION = re.compile(r"^\W*(?:instrumental|inst|no vocals?|music only)\W*$", re.I)


def style_text(song: Song) -> str:
    """The style as a model reads it: the brief, how its uncommon words are said, then the tempo
    and key as numbers."""
    parts = [str(song["style"]).strip().rstrip(".,; ")]  # one clean join, not "pads., 122 bpm"
    said = dict(song.get("pronounce") or {})
    if said:
        parts.append("pronounce " + ", ".join(f'"{w}" as "{s}"' for w, s in said.items()))
    if song.get("bpm"):
        parts.append(f"{song['bpm']:g} bpm")
    if song.get("key"):
        parts.append(str(song["key"]))
    return ", ".join(parts)


def lyrics_text(song: Song) -> str:
    """Words with their section tags, which is how every song model takes structure. A model that
    reads a section's note on its tag gets it from the provider (song_text)."""
    return song_text.tagged(song["sections"])


def problems(song: Song) -> list[str]:
    """What must not reach a model at all. A section's note is sent as its style is."""
    found = []
    notes = [str(s.get("style") or "") for s in song.get("sections") or []]
    kept_out = [str(s.get("avoid") or "") for s in song.get("sections") or []]
    for text in (song["style"], song.get("avoid") or "", *notes, *kept_out):
        if IMITATION.search(str(text)):
            found.append(f"the style asks to imitate someone ({text[:60]!r}); describe the sound")
    for where, text in (("style", song["style"]), *(("a section's style", n) for n in notes)):
        said = NEGATION.search(str(text))
        if said:
            found.append(
                f"the {where} says {said.group(0)!r}: a song model reads every word of it, so a "
                "sound named there is asked for. Name what you want, and put what to keep out in "
                "avoid"
            )
    words = " ".join(musicbar.lyric_lines(song)).casefold()
    unsung = [w for w in song.get("pronounce") or {} if str(w).casefold() not in words]
    if unsung:
        found.append(f"pronounce names words no line sings: {', '.join(unsung)}")
    directions = [line for line in musicbar.lyric_lines(song) if DIRECTION.match(line)]
    if directions:
        found.append(
            f"the line {directions[0]!r} would be sung; a section with no voice has no lines, and "
            'its style says "instrumental"'
        )
    if not song.get("instrumental") and not musicbar.lyric_lines(song):
        found.append("a song with a voice needs lines; set instrumental if it has none")
    return found


def _heard(job: Job, path: Path, saved: Path | None = None) -> list[dict[str, Any]] | None:
    """What a listener would pick out, kept with the take. None when nothing can transcribe here."""
    saved = saved or path.with_suffix(".heard.json")
    if saved.exists():
        return list(json.loads(saved.read_text()))
    if not router.available(job, "transcribe"):
        return None
    try:
        _, res = router.generate(job, TranscribeRequest(src=path), note="lyrics")
    except (router.ProviderError, OSError) as exc:
        print(f"{job.id}: could not hear the lyrics: {exc}")
        return None
    saved.write_text(json.dumps(res.words))
    return [dict(w) for w in res.words]


def _song_pin(brief: dict[str, Any]) -> Pin | None:
    """The one song model a job asks for, so jobs that differ only in it can be heard side by side.
    brief.song_model is {"provider": ..., "model": ...}; it goes there and nowhere else."""
    asked = brief.get("song_model")
    if not asked:
        return None
    if not isinstance(asked, dict) or not asked.get("provider") or not asked.get("model"):
        raise ContractError('brief.song_model is {"provider": "...", "model": "..."}')
    return Pin(provider=str(asked["provider"]), model=str(asked["model"]))


def song_request(
    song: Song, brief: dict[str, Any], seed: int, dst: Path, guide: Guide | None = None
) -> SongRequest:
    """One take's request, as the run sends it and a rehearsal writes it down."""
    return SongRequest(
        lyrics=lyrics_text(song),
        dst=dst,
        style=style_text(song),
        duration=float(song.get("duration_sec") or brief.get("duration_sec") or 120),
        seed=seed,
        sections=song["sections"],
        avoid=song.get("avoid") or "",
        bpm=song.get("bpm"),
        musical_key=song.get("key"),
        language=song.get("language"),
        vocal_gender=song.get("vocal_gender"),
        instrumental=bool(song.get("instrumental")),
        pronounce=dict(song.get("pronounce") or {}) or None,
        pin=_song_pin(brief),  # the pinned provider only: a take never comes from another vendor
        guide=guide,
    )


def planned_takes(brief: dict[str, Any]) -> dict[str, int]:
    return {**SAFE_TAKES, **{k: brief[k] for k in SAFE_TAKES if k in brief}}


def rehearse_takes(job: Job) -> None:
    """Every take a paid song model would be asked for, under an open rehearsal: the requests are
    written down and nothing is sent. Refused first, as the run refuses, when the song cannot go."""
    song = job.read("song")
    brief = job.job.get("brief") or {}
    refused = (
        problems(song)
        + genres.problems(song, genres.for_brief(brief))
        + song_lead.length_problems(brief, song)
    )
    if refused:
        raise ContractError(f"{job.id}: " + "; ".join(refused))
    guide, _ = song_guide.follow(job, brief, _song_pin(brief))
    prompt = f"{style_text(song)}\n{lyrics_text(song)}"
    for n in range(planned_takes(brief)["takes"]):
        dst = job.work / f"rehearsed-{n}.wav"
        req = song_request(song, brief, takes.seed_for(prompt, n), dst, guide)
        router.generate(job, req, note="song", only=[req.pin.provider] if req.pin else None)


def _generate(job: Job, song: Song, brief: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    lyrics = lyrics_text(song)
    style = style_text(song)
    guide, guided = song_guide.follow(job, brief, _song_pin(brief))

    def make(seed: int, dst: Path) -> tuple[Any, Any]:
        take = song_request(song, brief, seed, dst, guide)
        only = [take.pin.provider] if take.pin else None
        return router.generate(job, take, note="song", only=only)

    def assess(path: Path) -> tuple[dict[str, Any], bool]:
        found, ok = musicbar.assessed(path, song, _heard(job, path))
        return {**found, **judges.of_take("song", path)}, ok  # a judge ranks; it never blocks

    counts = planned_takes(brief)
    made = takes.make_until_good(
        job, SHOT, counts, suffix=".wav", make=make, assess=assess, prompt=f"{style}\n{lyrics}"
    )
    return made, guided


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
    cleaned = clean(take_file, job.work / "song.clean.wav")
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


def clean(take_file: Path, cleaned: Path) -> Path:
    """A take with its rumble out and a clean end: cut after its last full bar, faded over two
    bars, at 48 kHz and 24 bits. Its level is left as it was, for a master to set."""
    _, end = sounding_span(take_file)
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
    media.run(["-i", str(take_file), "-t", f"{cut_at:.3f}",
               "-af", f"highpass=f=25,afade=t=out:st={fade_start:.3f}:d={fade:.3f}",
               "-ar", "48000", "-ac", "2", "-c:a", "pcm_s24le", str(cleaned)])  # fmt: skip
    return cleaned


def _stems(job: Job, final: Path) -> dict[str, str]:
    """Vocals and everything else, when a provider that can split them is listed."""
    if not router.available(job, "separate"):
        return {}
    vocals, rest = job.work / "vocals.wav", job.work / "instrumental.wav"
    try:
        router.generate(job, SeparateRequest(src=final, vocals=vocals, rest=rest), note="stems")
    except (router.ProviderError, OSError) as exc:
        print(f"{job.id}: no stems: {exc}")
        return {}
    return {"vocals": vocals.name, "instrumental": rest.name}


def write(job: Job, keep_words: bool = False, again: bool = False, revise: str = "") -> Song:
    """The song file, written from the brief inside its genre when there is none yet. With
    keep_words, its sound is written again around its own lines; with again, a new song apart
    from the one it replaces; with revise, the song revised by a person's notes. A song is
    replaced only once nothing was made from it and its replacement passes, and the old one is set
    aside. Each draft is held to the song's rules and its genre, and a faulted one is written
    again."""
    if (again or revise) and job.has("song") and takes.load(job)["shots"].get(SHOT):
        raise ContractError(f"{job.id}: takes were made from this song; open a new job instead")
    if revise and not job.has("song"):
        raise ContractError(f"{job.id}: there is no song to revise; write one first")
    profile = genres.for_brief(job.job.get("brief") or {})

    def check(draft: Song) -> list[str]:
        return problems(draft) + song_lead.draft_problems(draft) + genres.problems(draft, profile)

    if keep_words:  # its words, tempo and key stand, so only its sound is held
        return writers.sound(job, check=check)

    def fresh(draft: Song) -> list[str]:  # a revision is not a repeat of the song it revises
        return check(draft) + song_lead.problems(job, draft, own=not revise)

    writers.ensure(job, "song", check=fresh, replace=again or bool(revise), revise=revise)
    return dict(job.read("song"))


def run(job: Job) -> Path:
    brief = job.job.get("brief") or {}
    profile = genres.for_brief(brief)
    song = write(job)
    refused = (
        problems(song) + genres.problems(song, profile) + song_lead.length_problems(brief, song)
    )
    if refused:
        raise ContractError(f"{job.id}: " + "; ".join(refused))
    router.refuse_too_long(
        job, "song", float(song.get("duration_sec") or brief.get("duration_sec") or 120)
    )
    take, guided = _generate(job, song, brief)
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
    if stems:
        _sung_words(job, job.work / stems["vocals"], take_file)
    released = release.for_job(
        job, song, lyrics_text(song), made_by=f"{take['provider']}: {take['model']}"
    )
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
                        **({"guide": guided} if guided else {}),
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
    take = takes.chosen(job, SHOT)
    off_stem = (
        take is not None and (job.work / take["file"]).with_suffix(musicbar.STEM_HEARD).exists()
    )
    out.append(
        {
            "id": "song.lyrics_heard_from",
            "status": "pass" if off_stem else "warn",
            "detail": "the vocal stem" if off_stem else "the full mix; the vocal stem hears more",
        }
    )
    out.append(
        {
            "id": "song.taste",
            "status": "warn",
            "detail": "no reading can judge a song; a human listens",
        }
    )
    return out, summarise(readings)


def _sung_words(job: Job, stem: Path, take_file: Path) -> None:
    """The lyrics heard again off the voice alone: a transcriber hears far more of a song without
    its band, so the finished song's lyric readings are read from this when there is one."""
    try:
        _heard(job, stem, take_file.with_suffix(musicbar.STEM_HEARD))
    except ContractError as exc:  # a paid call no one signed off: the mix's transcript stands
        print(f"{job.id}: the lyrics were not heard off the vocal stem: {exc}", file=sys.stderr)


def _heard_of_chosen(job: Job) -> list[dict[str, Any]] | None:
    """What was heard of the chosen take, off its vocal stem when that was transcribed."""
    take = takes.chosen(job, SHOT)
    if not take:
        return None
    return musicbar.saved_heard(job.work / take["file"])


# ------------------------------------------------------------------ a video for it
def video_job(
    job: Job,
    new_id: str,
    *,
    profile: str | None = None,
    still_only: bool = False,
    excerpt: dict[str, Any] | None = None,
    phrase_bars: int | None = None,
    stream: str | None = None,
    cast: list[str] | None = None,
    shots: Path | None = None,
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
    heard = _heard_of_chosen(job)
    cues = [
        {"start_sec": c["start_sec"], "end_sec": c["end_sec"], "text": c["text"]}
        for c in timed_lines(final, song, heard)[0]
    ]
    return musicvideo.build(
        job,
        new_id,
        song=song,
        cues=cues,
        words=list(manifest.get("words") or []),
        final=final,
        manifest=manifest,
        profile=profile or ("short-9x16" if excerpt else "landscape"),  # an excerpt is a short
        still_only=still_only,
        excerpt=excerpt,
        phrase_bars=phrase_bars,
        stream=stream,
        cast=cast,
        shot_list=musicvideo.read_shots(shots) if shots else None,
        sung_words=heard,
    )
