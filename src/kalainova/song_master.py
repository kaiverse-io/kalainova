"""SONG MASTER. A song take's master as options a person hears blind and chooses (ADR 0029).

The engine renders each option exactly and measures it. It chooses nothing a person must hear: the
operator listens at one loudness and picks, and that pick is the creative decision on the record.
Each option is a take of the `master` shot, beside the others (ADR 0016), made in four steps:

  clean     the song take with its rumble out and a clean end, as a finished song is (songs.clean)
  vocal     the lead vocal moved a few dB as a change added to the mix: mix + (gain - 1) x vocal.
            At 0 dB the mix is untouched, and the separated stems are never summed back, because
            a model's stems do not add up to the mix they came from (17 dB short, on one take)
  match     matched to a reference track the operator owns, by Matchering run as its own program
            with its limiter off (providers/runners/matchering_run.py)
  level     set by the engine's oversampled limiter to a profile's loudness and true peak, then
            encoded as each delivery format and decoded again, since true peak rises in a codec

`kalainova review <job> --blind --shot master` puts them on one page at one loudness, and
`kalainova take <job> master <n>` records the person's choice.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from . import config, media, songs, takes
from .bar import song as musicbar
from .bar.judges import RUNNERS
from .bar.readings import at_most
from .jobfs import ContractError, Job
from .providers import base, router
from .providers.contract import SeparateRequest, TranscribeRequest

SHOT = "master"
MOST_OPTIONS = 12  # more than a person can hear well in one sitting
ENCODINGS = {  # each master is encoded as it is delivered, then decoded and read again
    "aac": ["-c:a", "aac", "-b:a", "256k"],
    "mp3": ["-c:a", "libmp3lame", "-b:a", "320k"],
}


@dataclass(frozen=True)
class Option:
    vocal_db: float
    reference: Path | None

    def label(self) -> str:
        vocal = f"vocal {self.vocal_db:+g} dB" if self.vocal_db else "vocal as made"
        return (
            f"{vocal}, {f'matched to {self.reference.name}' if self.reference else 'no reference'}"
        )


def _settings() -> dict[str, Any]:
    return {"vocal_db_most": 3.0, **(config.studio().get("song_master") or {})}


def plan(vocal_db: list[float], references: list[Path]) -> list[Option]:
    """Every vocal level with no reference and with each reference, refused before any work when
    a move is past the most a separated vocal stands, or there are more options than a person
    can hear in one sitting."""
    most = float(_settings()["vocal_db_most"])
    levels = sorted({round(float(v), 2) for v in vocal_db or [0.0]})
    past = [v for v in levels if abs(v) > most]
    if past:
        raise ContractError(
            f"a vocal move of {past[0]:+g} dB is past {most:g} dB, where a separated vocal's "
            "artefacts are heard; move it less, or change song_master.vocal_db_most"
        )
    for ref in references:
        if not ref.is_file():
            raise ContractError(f"no reference file at {ref}")
    options = [Option(v, r) for v, r in itertools.product(levels, [None, *references])]
    if len(options) > MOST_OPTIONS:
        raise ContractError(f"{len(options)} options is more than {MOST_OPTIONS} to hear at once")
    return options


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _db(x: np.ndarray) -> float:
    return float(10 * np.log10(np.mean(np.square(x, dtype=np.float64)) + 1e-20))


def _write(pcm: np.ndarray, sr: int, dst: Path) -> Path:
    """Float samples as a 32-bit float WAV, so a sum past full scale is kept for the limiter."""
    subprocess.run(  # noqa: S603 - a list, never a shell string
        [media.FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-f", "f32le", "-ar", str(sr),
         "-ac", "2", "-i", "-", "-c:a", "pcm_f32le", str(dst)],
        input=np.ascontiguousarray(pcm, dtype=np.float32).tobytes(),
        check=True,
    )  # fmt: skip
    return dst


def stems(job: Job, source: Path) -> dict[str, Any]:
    """The source's vocal and the rest, split once and kept beside it, with how far the two
    stems fall short of adding back to the source (the residual, in dB under the source).

    The kept stems are named for the source's bytes and the provider and model that split it, so
    a changed source or a changed model splits again rather than reusing another model's stems."""
    by = free_provider(job, "separate")
    if by is None:
        raise ContractError(
            f"{job.id}: moving the vocal needs a stem split on this machine, and no free separate "
            "provider is ready: install the separator (docs/how-to/try-the-open-tools.md)"
        )
    model = config.model_for(by, "separate")
    key = hashlib.sha256(f"{_sha(source)}|{by}|{model}".encode()).hexdigest()[:12]
    vocals = source.with_name(f"{source.stem}.{key}.vocals.wav")
    rest = source.with_name(f"{source.stem}.{key}.rest.wav")
    if not (vocals.is_file() and rest.is_file()):
        req = SeparateRequest(src=source, vocals=vocals, rest=rest)
        router.generate(job, req, only=[by], note="master stems")
    left, right, sr = media.decode_stereo(source)
    mix = np.stack([left, right], axis=1)
    sung = np.stack(media.decode_stereo(vocals, sr)[:2], axis=1)
    other = np.stack(media.decode_stereo(rest, sr)[:2], axis=1)
    n = min(len(mix), len(sung), len(other))
    residual = _db(mix[:n] - sung[:n] - other[:n]) - _db(mix[:n])
    found = {"vocals": vocals, "rest": rest, "residual_db": round(residual, 1), "by": by}
    return {**found, "model": model}


def balanced(source: Path, vocals: Path | None, vocal_db: float, dst: Path) -> Path:
    """The source with its vocal moved by vocal_db, as mix + (gain - 1) x vocal. At 0 dB, or
    with no vocal stem, it is the source sample for sample."""
    left, right, sr = media.decode_stereo(source)
    mix = np.stack([left, right], axis=1)
    if vocal_db and vocals is not None:
        sung = np.stack(media.decode_stereo(vocals, sr)[:2], axis=1)
        n = min(len(mix), len(sung))
        mix = mix.copy()
        mix[:n] += (10 ** (vocal_db / 20) - 1) * sung[:n]
    return _write(mix, sr, dst)


def matched(source: Path, reference: Path, dst: Path) -> dict[str, Any]:
    """The source matched to a reference by Matchering, its limiter off. What it said is kept."""
    entry = config.adapter("reference_master")
    if entry["use"] != "matchering" or not entry.get("python"):
        raise ContractError(
            "matching to a reference needs Matchering: set adapters.reference_master to {use: "
            "matchering, python: <its environment's python>} (docs/how-to/try-the-open-tools.md)"
        )
    report = dst.with_suffix(".matchering.json")
    proc = subprocess.run(  # noqa: S603 - a list, never a shell string
        [str(Path(entry["python"]).expanduser()), str(RUNNERS / "matchering_run.py"),
         "--target", str(source), "--reference", str(reference), "--out", str(dst),
         "--report", str(report)],
        capture_output=True, text=True, timeout=float(entry.get("timeout_sec", 600)), check=False,
    )  # fmt: skip
    if proc.returncode != 0 or not dst.is_file():
        raise ContractError(f"Matchering failed: {(proc.stderr or proc.stdout)[-800:]}")
    return dict(json.loads(report.read_text()))


def encoded(master: Path) -> dict[str, dict[str, float | None]]:
    """Loudness and true peak of the master as each delivery format decodes it again."""
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, codec in ENCODINGS.items():
            coded = Path(tmp) / f"master.{'m4a' if name == 'aac' else name}"
            media.run(["-i", str(master), *codec, str(coded)])
            loud = media.loudness(coded)
            out[name] = {"lufs": loud["integrated_lufs"], "true_peak": loud["true_peak_dbtp"]}
    return out


def free_provider(job: Job, capability: str) -> str | None:
    """The first ready provider of a capability that costs nothing, the job's and the studio's
    order first. Master options are free to make: a dozen of them never spend, so their stems
    and their hearing come only from this machine."""
    listed = config.preference(capability, job.job)
    for name in [*listed, *(n for n in base.names() if n not in listed)]:
        found = base.get(name)
        if capability in found.capabilities and found.free and found.available(capability):
            return name
    return None


def heard(job: Job, master: Path, by: str) -> list[dict[str, Any]]:
    """What a transcriber picks out of one option, kept beside it."""
    saved = master.with_suffix(musicbar.MIX_HEARD)
    if saved.exists():
        return list(json.loads(saved.read_text()))
    _, res = router.generate(job, TranscribeRequest(src=master), only=[by], note="master lyrics")
    saved.write_text(json.dumps(res.words))
    return [dict(w) for w in res.words]


def _readings(
    master: Path, song: dict[str, Any], level: dict[str, float], hear: tuple[Job, str] | None
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    words = heard(hear[0], master, hear[1]) if hear else None
    report = musicbar.measure(master, song, words)
    coded = encoded(master)
    peak = max((v["true_peak"] for v in coded.values() if v["true_peak"] is not None), default=0.0)
    after = asdict(at_most("master.encoded_true_peak", peak, "master_encoded_true_peak_max"))
    found = [*report["readings"], *musicbar.master_readings(master, level["lufs"], level["peak"]),
             after]  # fmt: skip
    return found, {"encoded": coded, "score": musicbar.score(report)}


def _level(name: str) -> dict[str, float]:
    prof = config.profile(name)
    if "target_lufs" not in prof:
        raise ContractError(f"no profile {name!r} with a target_lufs; try song or song-loud")
    return {"lufs": float(prof["target_lufs"]), "peak": float(prof.get("true_peak_dbtp_max", -1))}


def make(
    job: Job,
    *,
    take_n: int | None = None,
    vocal_db: list[float] | None = None,
    references: list[Path] | None = None,
    level: str = "song",
    hear: bool = False,
) -> list[dict[str, Any]]:
    """Render every option of one song take as a take of the master shot, and measure each."""
    asked = vocal_db or [float(v) for v in _settings().get("vocal_db") or [0.0]]
    options = plan(asked, list(references or []))
    lv = _level(level)
    entry = takes.load(job)["shots"].get("song")
    if not entry or not entry.get("takes"):
        raise ContractError(f"{job.id}: no song takes yet, so there is nothing to master")
    take = next((t for t in entry["takes"] if t["n"] == take_n), None) if take_n is not None \
        else takes.chosen(job, "song")  # fmt: skip
    if take is None:
        raise ContractError(f"{job.id}: song has no take {take_n}")
    song = job.read("song")
    hearer = free_provider(job, "transcribe") if hear else None
    if hear and hearer is None:
        raise ContractError(
            f"{job.id}: --hear needs a transcriber that costs nothing on this machine (mac or "
            "whispercpp), and none is ready; leave out --hear to measure without the words"
        )
    folder = job.work / "takes" / SHOT
    folder.mkdir(parents=True, exist_ok=True)
    source = songs.clean(job.work / take["file"], folder / f"source-{take['n']:02d}.wav")
    split = stems(job, source) if any(o.vocal_db for o in options) else None
    made = []
    for option in options:
        n = takes.next_take_number(job, SHOT)
        dst = takes.take_path(job, SHOT, n, ".wav")
        with tempfile.TemporaryDirectory() as tmp:
            vocals = split["vocals"] if split else None
            mix = balanced(source, vocals, option.vocal_db, Path(tmp) / "mix.wav")
            said = None
            if option.reference is not None:
                said = matched(mix, option.reference, Path(tmp) / "matched.wav")
                mix = Path(tmp) / "matched.wav"
            media.master_loudness(mix, dst, lv["lufs"], lv["peak"])
        readings, extra = _readings(dst, song, lv, (job, hearer) if hearer else None)
        misses = [r["id"] for r in readings if not r["ok"]]
        made_take = {
            "n": n,
            "seed": 0,  # rendered exactly: nothing in a master is drawn at random
            "file": str(dst.relative_to(job.work)),
            "sha256": _sha(dst),
            "ok": not misses,
            "readings": {"score": extra["score"], "misses": misses, "readings": readings},
            "provider": "engine",
            "model": option.label(),
            "master": {
                "from_take": take["n"],
                "source_sha256": take.get("sha256"),
                "vocal_db": option.vocal_db,
                "reference": {"name": option.reference.name, "sha256": _sha(option.reference)}
                if option.reference
                else None,  # fmt: skip
                "level": level,
                "stems": {k: split[k] for k in ("by", "model", "residual_db")} if split else None,
                "matchering": said,
                "encoded": extra["encoded"],
                "heard_by": hearer,
            },
        }
        takes.record(job, SHOT, made_take)
        made.append(made_take)
    return made


def release(job: Job) -> Path:
    """The master a person chose becomes the song's final file and its release folder.

    Only a person's choice is released, because that choice is the creative decision on the record:
    a master the readings picked is refused. The master must come from the song take the song
    stands on, so the lyric files timed to that take still fit it. The record of the master goes
    into the asset manifest, and the render stamp moves to the new bytes, so QA and approval bind
    the file that ships."""
    from . import render
    from .render import release as releasing

    entry = takes.load(job)["shots"].get(SHOT)
    if not entry:
        raise ContractError(f"{job.id}: no master options yet; make them with `song master`")
    if entry["chosen_by"] != "human":
        raise ContractError(
            f"{job.id}: no one has chosen a master. Hear them blind, then "
            f"`kalainova take {job.id} master <n>`; a master the readings picked is not released"
        )
    master = takes.chosen(job, SHOT)
    song_take = takes.chosen(job, "song")
    if master is None or song_take is None:
        raise ContractError(f"{job.id}: no song take to release a master of")
    if master["master"]["from_take"] != song_take["n"]:
        raise ContractError(
            f"{job.id}: master take {master['n']} is of song take {master['master']['from_take']}, "
            f"but the song stands on take {song_take['n']}, whose lyric files these are; choose "
            f"that song take (`kalainova take {job.id} song {master['master']['from_take']}`) and "
            "run `kalainova song` again first"
        )
    song = job.read("song")
    final = job.work / "final.wav"
    media.run(["-i", str(job.work / master["file"]), "-c:a", "pcm_s24le", str(final)])
    tags = [
        "-metadata",
        f"title={song['title']}",
        "-metadata",
        "comment=contains AI-generated media",
    ]
    media.run(["-i", str(final), "-c:a", "aac", "-b:a", "256k", *tags, str(job.work / "final.m4a")])
    chosen = {"take": master["n"], "chosen_by": "a person", "sha256": master["sha256"]}
    made_by = f"{song_take['provider']}: {song_take['model']}"
    made = releasing.for_job(job, song, songs.lyrics_text(song), made_by=made_by, master=chosen)
    manifest = job.read("asset_manifest")
    for asset in manifest["assets"]:
        if asset.get("role") == "song":
            asset["provenance"] = {
                **(asset.get("provenance") or {}),
                "master": {**chosen, **master["master"]},
                "release": made,
            }
    job.write("asset_manifest", manifest)
    render.stamp(job, final)
    return final


def lines(made: list[dict[str, Any]]) -> list[str]:
    """One line per option for the terminal: what it is and how it measured."""
    out = []
    for take in made:
        read = {r["id"]: r["value"] for r in take["readings"]["readings"]}
        coded = take["master"]["encoded"]
        peaks = ", ".join(f"{k} {v['true_peak']}" for k, v in coded.items())
        words = read.get("song.words_found")
        heard = f", words heard {words:.0%}" if isinstance(words, float) else ""
        missed = ", ".join(take["readings"]["misses"]) or "none"
        out.append(f"master take {take['n']}: {take['model']}; {read.get('song.loudness')} LUFS, "
                   f"true peak {read.get('song.true_peak')} (after encoding: {peaks}){heard}; "
                   f"misses {missed}")  # fmt: skip
    return out
