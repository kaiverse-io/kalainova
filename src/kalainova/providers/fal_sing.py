"""What a shot sung in one call on fal is sent (ADR 0025), from its row in sing_models.

A model that takes one picture gets the still and the line. One that takes several gets the still
first, then the kit, with each picture and the line named in the prompt. The prompt goes under the
model's own field (`prompt_param`, or none at all when it is empty). A line shorter than the
shortest a model takes (`min_audio_sec`) is padded with silence at its end, and the clip that comes
back is cut to the line again, so the shot still runs as long as what it sings: a cut, with
nothing in the picture redrawn.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .. import media
from .contract import Reference, SingRequest

Fields = dict[str, Any]


def set_length(spec: Fields, duration: float) -> tuple[int, int | str]:
    """Seconds the vendor bills for this ask, and the length as this model wants it written."""
    allowed = [int(x) for x in str(spec.get("durations") or "5,10").split(",")]
    billed = min((d for d in allowed if d >= duration), default=max(allowed))
    return billed, billed if spec.get("duration_type") == "int" else str(billed)


def shortest(spec: Fields) -> float:
    """The shortest line the model takes, in seconds; 0 when it takes any."""
    return float(spec.get("min_audio_sec") or 0)


def sung_length(spec: Fields, line: float) -> tuple[float, int | str]:
    """A sung shot runs as long as its line (or the model's shortest), billed by the whole second,
    unless the model makes set lengths; then the next one up, as a plain clip is."""
    asked = max(line, shortest(spec))
    if spec.get("durations"):
        return set_length(spec, asked)
    return float(math.ceil(asked)), ""


def line_for(spec: Fields, audio: Path) -> Path:
    """The line as the model may take it: as it is, or padded with silence to its shortest."""
    least = shortest(spec)
    if not least or media.duration(audio) >= least:
        return audio
    padded = audio.with_name(f"{audio.stem}.padded.wav")
    media.run(["-i", str(audio), "-af", f"apad=whole_dur={least:.3f}", str(padded)])
    return padded


def references(spec: Fields, req: SingRequest) -> tuple[Reference, ...]:
    """The kit pictures sent after the still, as many as the model takes."""
    if not spec.get("images_param"):
        return ()
    return req.references[: max(int(spec.get("max_images", 1)) - 1, 0)]


def payload(
    spec: Fields, req: SingRequest, still: str, line: str, refs: list[str], length: int | str
) -> Fields:
    """The request body, with the still, the line and the kit already uploaded."""
    body: Fields = {**spec.get("extra", {})}
    text = req.prompt
    if spec.get("images_param"):
        tag = str(spec["image_tag"])
        named = references(spec, req)
        guide = [f"{tag.format(n=1)} is the first frame"]
        guide += [f"{tag.format(n=i)} is {r.label}" for i, r in enumerate(named, start=2)]
        guide += [f"{spec['audio_tag']} is the vocal she sings, her lips and breath on it"]
        text = f"{req.prompt}. {'; '.join(guide)}."
        body[spec["images_param"]] = [still, *refs]
        body[spec["audios_param"]] = [line]
    else:
        body[spec.get("image_param", "image_url")] = still
        body[spec.get("audio_param", "audio_url")] = line
    field = spec.get("prompt_param", "prompt")
    if field:
        body[field] = text
    if spec.get("durations"):
        body["duration"] = length
    if spec.get("aspect_param"):
        body[spec["aspect_param"]] = req.aspect
    if req.seed is not None and spec.get("takes_seed"):
        body["seed"] = req.seed
    return body


def cut_to_line(clip: Path, line: float) -> None:
    """A clip made from a padded line, cut back to the line's length."""
    if media.duration(clip) <= line + 0.02:
        return
    out = clip.with_suffix(".cut.mp4")
    media.run(["-i", str(clip), "-t", f"{line:.3f}", "-an", "-c:v", "libx264", "-crf", "10",
               "-pix_fmt", "yuv420p", str(out)])  # fmt: skip
    out.replace(clip)
