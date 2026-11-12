"""The mix: voice, music set against it, the sound of each place, effects, and the master level.

Fixed filter strings, so no value from a plan enters them except as a checked number.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import bar, media
from .spec import safe_path

# The sound of a finished voice: rumble out, sibilance tamed, mud eased, presence and air lifted,
# level held. Fixed strings, so no value from a plan enters them.
VOICE_CHAIN = (
    "highpass=f=75,deesser=i=0.4:m=0.5:f=0.5,equalizer=f=220:t=q:w=1.2:g=-1.5,"
    "equalizer=f=3000:t=q:w=1.5:g=1.5,equalizer=f=9500:t=h:w=2000:g=1,"
    "acompressor=threshold=-22dB:ratio=2.5:attack=6:release=120:makeup=3dB,"
    "alimiter=limit=0.9:attack=2:release=50:level=disabled"
)
# sidechaincompress reads two inputs whose frames reach it in whatever order the threads deliver
# them, and its output changes with that order. Cutting both into frames of one fixed size makes
# every render pair them the same way, so the same plan gives the same bytes.
PAIR_FRAMES = "asetnsamples=n=1024:p=0"
MUSIC_POCKET = "equalizer=f=2800:t=q:w=1.4:g=-3"  # a space in the music for the words to sit in
DUCK = "sidechaincompress=threshold=0.05:ratio=3:attack=25:release=450:makeup=1"  # gently: 5 dB
# A real room is never silent. A faint bed keeps speech gaps from dropping to digital zero.
ROOM_TONE = (
    "anoisesrc=d={duration:.3f}:c=pink:r=48000:a=0.0007:seed=7,lowpass=f=7000,"
    "aformat=channel_layouts=stereo[room]"
)
MUSIC_FADE_SEC = 2.5
AMBIENCE_FADE_SEC = 0.5
MUSIC_CLEAN = "highpass=f=25"  # generated music can carry DC and rumble nobody can hear
# Against the voice where it speaks, before ducking. On real speech it lands 15 dB under the words.
MUSIC_UNDER_VOICE_DB = -10.0
DUCK_KEY_LUFS = -27.0  # where the ducker hears the voice, so it ducks the same for any voice


@dataclass
class _Graph:
    """A filter graph as it is built: its inputs, its chains, what mixes, and what is kept apart."""

    inputs: list[str] = field(default_factory=list)
    chains: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    stems: list[str] = field(default_factory=list)
    count: int = 0

    def add_input(self, path: Path) -> int:
        self.inputs += ["-i", str(path)]
        self.count += 1
        return self.count - 1


def _music_under_voice(work: Path, a: dict[str, Any], bed: Path) -> tuple[Path, float, float]:
    """The bed to mix, its gain, and the ducking key's gain, all set against the measured voice."""
    level = media.even_out(bed, work / "music.even.wav")
    voice_path = safe_path(work, a["voice"])
    voice, _, sr = media.decode_stereo(voice_path)
    music, _, _ = media.decode_stereo(level)
    gain = bar.voice_to_music_db(voice, music, sr) + a.get("music_gain_db", MUSIC_UNDER_VOICE_DB)
    lufs = media.loudness(voice_path).get("integrated_lufs")
    return level, gain, DUCK_KEY_LUFS - lufs if lufs is not None else 0.0


def _music_chain(index: int, gain: float, duration: float, under_voice: bool) -> str:
    fade = min(MUSIC_FADE_SEC, duration * 0.25)
    pocket = f"{MUSIC_POCKET}," if under_voice else ""
    return (
        f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,{MUSIC_CLEAN},{pocket}"
        f"volume={gain:.2f}dB,"
        f"afade=t=in:d=0.2,afade=t=out:st={duration - fade:.3f}:d={fade:.3f}"
    )


def _add_voice(graph: _Graph, work: Path, a: dict[str, Any], seconds: float) -> None:
    index = graph.add_input(safe_path(work, a["voice"]))
    polish = f"{VOICE_CHAIN}," if a.get("voice_chain") else ""
    graph.chains.append(
        f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,{polish}"
        f"apad=whole_dur={seconds:.3f},atrim=0:{seconds:.3f},asplit=3[voice][vkey][vstem]"
    )
    graph.chains.append(ROOM_TONE.format(duration=seconds))
    graph.labels += ["[voice]", "[room]"]
    graph.stems += ["-map", "[vstem]", str(work / "voice.stem.wav")]


def _add_music(graph: _Graph, work: Path, a: dict[str, Any], seconds: float) -> None:
    has_voice = bool(a.get("voice"))
    bed = media.loop_audio(safe_path(work, a["music"]), work / "music.bed.wav", seconds)
    gain, key_gain = a.get("music_gain_db", MUSIC_UNDER_VOICE_DB), 0.0
    if has_voice:
        bed, gain, key_gain = _music_under_voice(work, a, bed)
    music = _music_chain(graph.add_input(bed), gain, seconds, has_voice)
    if has_voice and a.get("duck"):
        graph.chains.append(f"{music},{PAIR_FRAMES}[mus]")
        graph.chains.append(f"[vkey]volume={key_gain:.2f}dB,{PAIR_FRAMES}[key]")
        graph.chains.append(f"[mus][key]{DUCK},asplit=2[musd][mstem]")
    else:
        graph.chains.append(f"{music},asplit=2[musd][mstem]")
    graph.labels.append("[musd]")
    graph.stems += ["-map", "[mstem]", str(work / "music.stem.wav")]


def _ambience_chain(index: int, k: int, s: dict[str, Any]) -> str:
    """One place's sound, fading in and out so a cut between two places is never heard as a step."""
    span = max(float(s["end_sec"]) - float(s["start_sec"]), 0.1)
    fade = min(AMBIENCE_FADE_SEC, span / 3)
    start_ms = max(int(float(s["start_sec"]) * 1000), 0)
    return (
        f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,"
        f"aloop=loop=-1:size=2147483647,atrim=0:{span:.3f},"
        f"afade=t=in:d={fade:.3f},afade=t=out:st={span - fade:.3f}:d={fade:.3f},"
        f"volume={float(s.get('gain_db', -24)):.2f}dB,adelay={start_ms}|{start_ms}[amb{k}]"
    )


def _add_places(graph: _Graph, work: Path, places: list[dict[str, Any]]) -> None:
    if not places:
        return
    for k, place in enumerate(places):
        index = graph.add_input(safe_path(work, place["path"]))
        graph.chains.append(_ambience_chain(index, k, place))
    joined = "".join(f"[amb{k}]" for k in range(len(places)))
    graph.chains.append(f"{joined}amix=inputs={len(places)}:normalize=0,asplit=2[fx][fxstem]")
    graph.labels.append("[fx]")
    graph.stems += ["-map", "[fxstem]", str(work / "effects.stem.wav")]


def _add_effects(graph: _Graph, work: Path, effects: list[dict[str, Any]]) -> None:
    for k, effect in enumerate(effects):
        index = graph.add_input(safe_path(work, effect["path"]))
        ms = max(int(float(effect["start_sec"]) * 1000), 0)
        graph.chains.append(
            f"[{index}:a]aresample=48000,aformat=channel_layouts=stereo,"
            f"volume={float(effect.get('gain_db', -12)):.2f}dB,adelay={ms}|{ms}[sfx{k}]"
        )
        graph.labels.append(f"[sfx{k}]")


def _music_and_effects(work: Path) -> None:
    """Everything but the voice, which a dub or a foreign version is built on."""
    stems = [p for p in (work / "music.stem.wav", work / "effects.stem.wav") if p.exists()]
    if not stems:
        return
    inputs = [arg for stem in stems for arg in ("-i", str(stem))]
    graph = ["-filter_complex", f"amix=inputs={len(stems)}:normalize=0"] if len(stems) > 1 else []
    media.run([*inputs, *graph, "-ar", "48000", str(work / "me.stem.wav")])


def _add_voice_and_music(graph: _Graph, work: Path, a: dict[str, Any], seconds: float) -> None:
    has_voice = bool(a.get("voice"))
    if has_voice:
        _add_voice(graph, work, a, seconds)
    if a.get("music"):
        _add_music(graph, work, a, seconds)
    if has_voice and not (a.get("music") and a.get("duck")):
        graph.chains.append("[vkey]anullsink")  # nothing ducks, so the key feeds nothing


def op_mix_audio(work: Path, a: dict[str, Any]) -> None:
    seconds = a["duration_sec"]
    for stale in ("music.stem.wav", "effects.stem.wav", "me.stem.wav"):
        (work / stale).unlink(missing_ok=True)
    graph = _Graph()
    _add_voice_and_music(graph, work, a, seconds)
    _add_places(graph, work, a.get("ambience") or [])
    _add_effects(graph, work, a.get("sfx") or [])
    if not graph.labels:
        return
    mixed = (
        ";".join(graph.chains)
        + ";"
        + "".join(graph.labels)
        + f"amix=inputs={len(graph.labels)}:normalize=0:duration=longest,atrim=0:{seconds:.3f}[out]"
    )
    media.run(
        [
            *graph.inputs,
            "-filter_complex",
            mixed,
            "-map",
            "[out]",
            "-ar",
            "48000",
            str(safe_path(work, a["out"])),
            *graph.stems,
        ]
    )
    _music_and_effects(work)


def op_loudnorm(work: Path, a: dict[str, Any]) -> None:
    media.master_loudness(
        safe_path(work, a["input"]),
        safe_path(work, a["out"]),
        a["target_lufs"],
        a["true_peak_dbtp_max"],
    )


def op_export_audio(work: Path, a: dict[str, Any]) -> None:
    source = str(safe_path(work, a["audio"]))
    note = "Made with Kalainova; contains AI-generated media" if a.get("synthetic", True) else ""
    tag = ["-metadata", f"comment={note}"] if note else []
    media.run(["-i", source, "-c:a", "pcm_s24le", *tag, str(safe_path(work, a["master"]))])
    media.run(
        ["-i", source, "-c:a", "aac", "-b:a", "256k", *tag, str(safe_path(work, a["delivery"]))]
    )
