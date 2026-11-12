"""A cut an editor can open.

Rendering a finished file is one way out of the engine. This is the other: the same cut as a
timeline
for Final Cut, Resolve, or Premiere, so a person can take it further. Shapes follow auto-editor's
public-domain exporters and the published FCPXML reference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any
from xml.sax.saxutils import quoteattr  # noqa: S406 - writes XML; nothing here parses any

from . import config, media, nle_otio
from .jobfs import ContractError, Job

NTSC = (Fraction(24000, 1001), Fraction(30000, 1001), Fraction(60000, 1001))
FORMATS = ("fcpxml", "otio", "edl")
REC709 = "1-1-1 (Rec. 709)"


@dataclass(frozen=True)
class Clip:
    name: str
    path: Path
    start: float  # where it sits on the timeline
    duration: float
    source_in: float  # where it starts in its source
    source_length: float | None = None  # the whole source, when it can be probed


@dataclass(frozen=True)
class Timeline:
    name: str
    rate: Fraction
    width: int
    height: int
    picture: list[Clip]
    sound: list[Clip]
    duration: float


def rate_of(fps: float) -> Fraction:
    """A frame rate as a fraction. 23.976 is really 24000/1001, and a rounded one drifts."""
    for rate in NTSC:
        if abs(float(rate) - fps) < 0.01:
            return rate
    return Fraction(round(fps))


def frames(seconds: float, rate: Fraction) -> int:
    return round(Fraction(seconds).limit_denominator(100000) * rate)


def _time(seconds: float, rate: Fraction) -> str:
    """FCPXML time: a whole number of frames, as a fraction of a second."""
    count = frames(seconds, rate)
    if count == 0:
        return "0s"
    exact = count / rate
    return f"{exact.numerator}/{exact.denominator}s"


def _spans(cuts: list[dict[str, Any]], total: float) -> list[tuple[float, float]]:
    starts = [float(c.get("start_sec", 0.0)) for c in cuts]
    return list(zip(starts, [*starts[1:], total], strict=True))


def _length(path: Path) -> float | None:
    """The probed length of a source, or None when it is not on disk to probe."""
    if not path.is_file():
        return None
    try:
        return media.duration(path)
    except (media.MediaError, KeyError, ValueError):
        return None


def build(job: Job) -> Timeline:
    """The cut as the job records it, with every source as a full path."""
    em = job.read("edit_manifest")
    am = job.read("asset_manifest")
    assets = {a["id"]: a for a in am["assets"]}
    if not em.get("cuts"):
        raise ContractError(f"{job.id}: this piece has no cuts to export")
    total = float(em["duration_sec"])
    picture = []
    for cut, (start, end) in zip(em["cuts"], _spans(em["cuts"], total), strict=True):
        path = (job.work / assets[cut["source"]]["path"]).resolve()
        picture.append(
            Clip(
                name=str(cut.get("id") or cut["source"]),
                path=path,
                start=start,
                duration=end - start,
                source_in=float(cut.get("in_sec") or 0.0),
                source_length=_length(path),
            )
        )
    audio = em.get("audio") or {}
    sound = [
        Clip(
            name=role,
            path=(job.work / assets[aid]["path"]).resolve(),
            start=0.0,
            duration=total,
            source_in=0.0,
            source_length=_length((job.work / assets[aid]["path"]).resolve()),
        )
        for role, aid in (
            ("voice", audio.get("voice_asset_id")),
            ("music", audio.get("music_asset_id")),
        )
        if aid
    ]
    profile = em["profile"]
    return Timeline(
        name=job.id,
        rate=rate_of(float(profile["fps"])),
        width=int(profile["width"]),
        height=int(profile["height"]),
        picture=picture,
        sound=sound,
        duration=total,
    )


def _assets_xml(sources: list[Path], tl: Timeline, sound_paths: set[Path]) -> list[str]:
    out = []
    for n, path in enumerate(sources):
        is_sound = path in sound_paths
        out.append(
            f'    <asset id="r{n + 2}" name={quoteattr(path.stem)} start="0s" '
            f'hasVideo="{0 if is_sound else 1}" hasAudio="1" audioSources="1" audioChannels="2" '
            f'format="r1" duration={quoteattr(_time(tl.duration, tl.rate))}>\n'
            f'      <media-rep kind="original-media" src={quoteattr(path.as_uri())}/>\n'
            f"    </asset>"
        )
    return out


def fcpxml(tl: Timeline) -> str:
    """Final Cut Pro XML, which Resolve also reads. Voice and music connect below the picture."""
    sources = list(dict.fromkeys([c.path for c in tl.picture] + [c.path for c in tl.sound]))
    ref = {path: f"r{n + 2}" for n, path in enumerate(sources)}
    connected = [
        f'          <asset-clip name={quoteattr(c.name)} ref="{ref[c.path]}" lane="-{n + 1}" '
        f'offset={quoteattr(_time(tl.picture[0].source_in, tl.rate))} start="0s" '
        f'duration={quoteattr(_time(c.duration, tl.rate))} audioRole="dialogue"/>'
        for n, c in enumerate(tl.sound)
    ]
    spine = []
    for n, clip in enumerate(tl.picture):
        head = (
            f'        <asset-clip name={quoteattr(clip.name)} ref="{ref[clip.path]}" '
            f"offset={quoteattr(_time(clip.start, tl.rate))} "
            f"start={quoteattr(_time(clip.source_in, tl.rate))} "
            f'duration={quoteattr(_time(clip.duration, tl.rate))} tcFormat="NDF"'
        )
        inner = connected if n == 0 and connected else []
        spine.append(
            f"{head}>\n" + "\n".join(inner) + "\n        </asset-clip>" if inner else f"{head}/>"
        )
    frame = 1 / tl.rate
    body = "\n".join(spine)
    assets = "\n".join(_assets_xml(sources, tl, {c.path for c in tl.sound}))
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.11">\n'
        "  <resources>\n"
        f'    <format id="r1" name="FFVideoFormatRateUndefined" '
        f'frameDuration="{frame.numerator}/{frame.denominator}s" '
        f'width="{tl.width}" height="{tl.height}" colorSpace="{REC709}"/>\n'
        f"{assets}\n  </resources>\n"
        f'  <library>\n    <event name="Kalainova">\n      <project name={quoteattr(tl.name)}>\n'
        '        <sequence format="r1" tcStart="0s" tcFormat="NDF" audioLayout="stereo" '
        'audioRate="48k">\n'
        f"      <spine>\n{body}\n      </spine>\n"
        "        </sequence>\n      </project>\n    </event>\n  </library>\n</fcpxml>\n"
    )


def _otio_time(seconds: float, rate: Fraction) -> dict[str, Any]:
    return {
        "OTIO_SCHEMA": "RationalTime.1",
        "rate": float(rate),
        "value": float(frames(seconds, rate)),
    }


def _otio_clip(clip: Clip, rate: Fraction) -> dict[str, Any]:
    reference: dict[str, Any] = {
        "OTIO_SCHEMA": "ExternalReference.1",
        "target_url": clip.path.as_uri(),
    }
    if clip.source_length is not None:
        reference["available_range"] = {
            "OTIO_SCHEMA": "TimeRange.1",
            "start_time": _otio_time(0.0, rate),
            "duration": _otio_time(clip.source_length, rate),
        }
    return {
        "OTIO_SCHEMA": "Clip.1",
        "name": clip.name,
        "source_range": {
            "OTIO_SCHEMA": "TimeRange.1",
            "start_time": _otio_time(clip.source_in, rate),
            "duration": _otio_time(clip.duration, rate),
        },
        "media_reference": reference,
    }


def _otio_track(name: str, kind: str, clips: list[Clip], rate: Fraction) -> dict[str, Any]:
    return {
        "OTIO_SCHEMA": "Track.1",
        "name": name,
        "kind": kind,
        "children": [_otio_clip(c, rate) for c in clips],
    }


def otio(tl: Timeline) -> str:
    """OpenTimelineIO, which Premiere and Resolve read."""
    tracks = [_otio_track("Picture", "Video", tl.picture, tl.rate)]
    tracks += [_otio_track(c.name.title(), "Audio", [c], tl.rate) for c in tl.sound]
    document = {
        "OTIO_SCHEMA": "Timeline.1",
        "name": tl.name,
        "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "children": tracks},
    }
    return json.dumps(document, indent=2) + "\n"


def _smpte(count: int, rate: Fraction) -> str:
    """Timecode for a whole number of frames."""
    base = round(float(rate))
    hours, rest = divmod(count, base * 3600)
    minutes, rest = divmod(rest, base * 60)
    secs, left = divmod(rest, base)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{left:02d}"


def edl(tl: Timeline) -> str:
    """CMX 3600, the oldest format every editing system still reads. Picture only.

    Whole frames throughout: each event's length is counted once, and source and record both end
    that many frames after they begin, so a reader never sees the two lengths disagree. An EDL
    does not carry its rate, so a closing comment says it (the CMX 3600 reader refuses a comment
    before the first event).
    """
    rate = tl.rate
    lines = [f"TITLE: {tl.name}", "FCM: NON-DROP FRAME", ""]
    rec_in = 0
    for n, clip in enumerate(tl.picture, 1):
        length = frames(clip.duration, rate)
        src_in = frames(clip.source_in, rate)
        times = (src_in, src_in + length, rec_in, rec_in + length)
        lines.append(
            f"{n:03d}  AX       V     C        " + " ".join(_smpte(t, rate) for t in times)
        )
        lines.append(f"* FROM CLIP NAME: {clip.path.name}")
        rec_in += length
    lines.append(f"* FRAME RATE: {float(rate):.3f} FPS")
    return "\n".join(lines) + "\n"


def export(job: Job, to: str = "fcpxml") -> Path:
    """Write the cut in a format an editor can open, next to the rendered file. `adapters.timeline`
    picks who writes it: this module (default), or `otioconvert` for FCPXML and EDL."""
    if to not in FORMATS:
        raise ContractError(f"no export to {to}; choose from {FORMATS}")
    timeline = build(job)
    chosen = config.adapter("timeline")["use"]
    if chosen == "otio":
        return nle_otio.export(job, to, otio(timeline))
    if chosen != "inhouse":
        raise ContractError(f"adapters.timeline: unknown adapter {chosen!r} (inhouse, otio)")
    writers = {"fcpxml": fcpxml, "otio": otio, "edl": edl}
    dst = job.work / f"timeline.{to}"
    dst.write_text(writers[to](timeline))
    return dst


def read_back(job: Job, path: Path) -> Path:
    """Read a timeline an editor saved into a summary in the job's folder (otio adapter only)."""
    return nle_otio.read_back(job, path)
