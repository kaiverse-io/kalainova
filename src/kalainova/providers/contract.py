"""What the engine asks a model for and what comes back, in the engine's own terms (ADR 0023).

Nothing here names a vendor or a vendor's field. A request is one frozen value per capability:
the router reads its capability, its output files, what it bills on, and its content key from it;
an adapter maps it to its vendor's payload and maps the reply back to a `Result`. A field an adapter
does not know is a type error, not a silently dropped keyword.

A pin names a model at one provider. The router hands the pinned model only to that provider, so a
fallback provider never receives another vendor's model id; it uses its own default.

Each call carries a `Context` the router makes fresh per attempt. Its `receipt` is filled by
whoever learns its parts (the vendor's request id, billed units, what the vendor charged), so the
router can still read them when the call fails.

This module is the whole vocabulary of the port: the requests are here, and the results
(providers/results.py) and the errors (providers/errors.py) are imported through it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from pathlib import Path
from typing import Any, ClassVar, Self

from ..blobstore import sha256_file
from .errors import BilledError as BilledError
from .errors import InvalidRequestError as InvalidRequestError
from .errors import RateLimitedError as RateLimitedError
from .errors import RefusalError as RefusalError
from .errors import UnauthorizedError as UnauthorizedError
from .errors import UnavailableError as UnavailableError
from .errors import VendorError as VendorError
from .results import RECORDED as RECORDED
from .results import Context as Context
from .results import Hit as Hit
from .results import Inputs as Inputs
from .results import Receipt as Receipt
from .results import Result as Result
from .results import Sent as Sent
from .results import Word as Word


# ------------------------------------------------------------------ parts of a request
@dataclass(frozen=True, kw_only=True)
class Pin:
    """A model chosen at one provider, by a stream's lock, a kit, or a person."""

    provider: str
    model: str


@dataclass(frozen=True, kw_only=True)
class Reference:
    """A picture the model must hold to: a kit's face, a look, a place, or a first frame."""

    path: Path
    label: str
    group: str = ""  # pictures of one character share a group, so a model can take them together
    sha256: str = ""  # the kit's record of the picture, when it came from a kit

    def shape(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "label": self.label, "group": self.group}


@dataclass(frozen=True, kw_only=True)
class Card:
    """How a provider that draws instead of generating should draw a still: a titled card."""

    title: str
    palette: int | None = 0
    theme: str = "studio"


@dataclass(frozen=True, kw_only=True)
class Repaint:
    """Remake one span of an existing song take and keep the rest."""

    source: Path
    start_sec: float
    end_sec: float
    lyrics: str = ""  # the words sung in the span, for a model that edits by replacing them
    vendor_id: str | None = None  # the vendor's own id of the take, when it made it


GUIDE_USES = ("reference", "remix")


@dataclass(frozen=True, kw_only=True)
class Guide:
    """A track a song model follows, made before anything is paid for (ADR 0016's free draft).

    `reference`: a clip whose sound and groove the new song takes up. `remix`: the whole track,
    sung and produced again from the words and the style, keeping its arrangement."""

    source: Path
    use: str

    def __post_init__(self) -> None:
        if self.use not in GUIDE_USES:
            raise ValueError(f"a guide is used as {' or '.join(GUIDE_USES)}, not {self.use!r}")


@dataclass(frozen=True, kw_only=True)
class Billable:
    """What a call is priced on, so a quote needs no file and no prompt."""

    capability: str
    duration: float = 0.0
    chars: int = 0
    image: bool = False  # a clip from a first frame
    references: bool = False  # a clip held to references
    guided: bool = False  # a song that follows a track, which the vendor may charge to take in


# ------------------------------------------------------------------ requests
def _plain(value: Any) -> Any:
    if isinstance(value, Path):
        return sha256_file(value) if value.is_file() else str(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_plain(v) for v in value]
    return value


def _seconds(path: Path) -> float:
    from .. import media

    return media.duration(path) if path.is_file() else 0.0


@dataclass(frozen=True, kw_only=True)
class Request:
    """One call's ask. Subclasses name their capability and which fields are files it writes."""

    capability: ClassVar[str] = ""
    OUTPUTS: ClassVar[tuple[str, ...]] = ()  # fields naming files the call writes; first is kept
    pin: Pin | None = None

    @property
    def method(self) -> str:
        return self.capability

    def output(self) -> Path | None:
        found: Path | None = getattr(self, self.OUTPUTS[0]) if self.OUTPUTS else None
        return found

    def writing_to(self, path: Path) -> Self:
        """The same request with its kept file written somewhere else (the router's temporary)."""
        changes: dict[str, Any] = {self.OUTPUTS[0]: path}
        return replace(self, **changes)

    def billable(self) -> Billable:
        return Billable(capability=self.capability)

    def model_for(self, provider: str) -> str | None:
        """The pinned model, for the provider the pin names only."""
        return self.pin.model if self.pin and self.pin.provider == provider else None

    def _shape(self) -> tuple[list[Any], dict[str, Any]]:
        """The call as positional inputs and named options, in the form the content key has hashed
        since keys were first written (v1), so a file paid for before ADR 0023 is still reused."""
        raise NotImplementedError

    def key(self) -> str:
        """The content key: the inputs by their bytes, the output by its name. Empty for a call that
        writes no file."""
        if not self.OUTPUTS:
            return ""
        args, kw = self._shape()
        if self.pin:
            kw = {**kw, "model": self.pin.model}
        out = self.output()
        assert out is not None
        request = {
            "capability": self.capability,
            "fn": self.method,
            "dst": Path(out).name,
            "args": [_plain(a) for a in args],
            "kw": {k: _plain(v) for k, v in kw.items()},
        }
        return hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()

    def described(self) -> dict[str, Any]:
        """The request as a record: every field, files named and hashed. For rehearsals, packages
        and traces; never sent to a vendor."""
        out: dict[str, Any] = {"capability": self.capability}
        for f in fields(self):
            value = getattr(self, f.name)
            if value in (None, (), [], "", {}):
                continue
            out[f.name] = _described(value)
        return out


def _described(value: Any) -> Any:
    if isinstance(value, Path):
        return {"file": value.name, "sha256": sha256_file(value)} if value.is_file() else value.name
    if isinstance(value, Reference | Pin | Card | Repaint | Guide):
        return {f.name: _described(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {k: _described(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_described(v) for v in value]
    return value


@dataclass(frozen=True, kw_only=True)
class TextRequest(Request):
    """Text, or a reading of pictures, from a language model."""

    capability: ClassVar[str] = "llm"
    prompt: str
    system: str = ""
    images: tuple[Path, ...] = ()
    max_tokens: int = 4000
    judging: bool = False  # a check of work, which a provider may run on its judge model


@dataclass(frozen=True, kw_only=True)
class JudgeRequest(TextRequest):
    """A check of work on the provider's judge model, priced as the judge."""

    capability: ClassVar[str] = "judge"
    judging: bool = True


@dataclass(frozen=True, kw_only=True)
class VoiceRequest(Request):
    capability: ClassVar[str] = "voice"
    OUTPUTS: ClassVar[tuple[str, ...]] = ("dst",)
    text: str
    dst: Path
    voice: str | None = None  # the voice's id at the pinned provider, or the brief's
    settings: Mapping[str, Any] | None = None
    previous_text: str | None = None  # the lines around this one, so the reading flows
    next_text: str | None = None

    def billable(self) -> Billable:
        return Billable(capability="voice", chars=len(self.text))

    def _shape(self) -> tuple[list[Any], dict[str, Any]]:
        kw: dict[str, Any] = {"voice": self.voice}
        if self.settings is not None:
            kw["settings"] = dict(self.settings)
        kw.update(previous_text=self.previous_text, next_text=self.next_text)
        return [self.text], kw


@dataclass(frozen=True, kw_only=True)
class ImageRequest(Request):
    capability: ClassVar[str] = "image"
    OUTPUTS: ClassVar[tuple[str, ...]] = ("dst",)
    prompt: str
    dst: Path
    width: int
    height: int
    references: tuple[Reference, ...] = ()
    seed: int | None = None
    card: Card | None = None

    def _shape(self) -> tuple[list[Any], dict[str, Any]]:
        kw: dict[str, Any] = {"width": self.width, "height": self.height}
        if self.card is not None:
            kw.update(title=self.card.title, palette=self.card.palette, style=self.card.theme)
        if self.seed is not None:
            kw["seed"] = self.seed
        if self.references:
            kw["references"] = [r.shape() for r in self.references]
        return [self.prompt], kw


@dataclass(frozen=True, kw_only=True)
class VideoRequest(Request):
    capability: ClassVar[str] = "video"
    OUTPUTS: ClassVar[tuple[str, ...]] = ("dst",)
    prompt: str
    dst: Path
    duration: float
    aspect: str
    start: Path | None = None  # the first frame
    end: Path | None = None  # the last frame, for a model that takes one
    references: tuple[Reference, ...] = ()
    seed: int | None = None
    sound: bool = False  # ask the model for the clip's own sound

    def billable(self) -> Billable:
        return Billable(
            capability="video",
            duration=float(self.duration),
            image=self.start is not None,
            references=bool(self.references),
        )

    def _shape(self) -> tuple[list[Any], dict[str, Any]]:
        kw: dict[str, Any] = {
            "duration": self.duration,
            "aspect": self.aspect,
            "image": self.start,
            "seed": self.seed,
            "audio": self.sound,
        }
        if self.end is not None:
            kw["end_image"] = self.end
        if self.references:
            kw["references"] = [r.shape() for r in self.references]
        return [self.prompt], kw


@dataclass(frozen=True, kw_only=True)
class MotionRequest(Request):
    """A character picture moved the way a driving clip moves."""

    capability: ClassVar[str] = "motion"
    OUTPUTS: ClassVar[tuple[str, ...]] = ("dst",)
    character: Path
    driving: Path
    dst: Path

    def billable(self) -> Billable:
        return Billable(capability="motion", duration=_seconds(self.driving))

    def _shape(self) -> tuple[list[Any], dict[str, Any]]:
        return [self.character, self.driving], {}


@dataclass(frozen=True, kw_only=True)
class MusicRequest(Request):
    capability: ClassVar[str] = "music"
    OUTPUTS: ClassVar[tuple[str, ...]] = ("dst",)
    prompt: str
    dst: Path
    duration: float

    def billable(self) -> Billable:
        return Billable(capability=self.capability, duration=float(self.duration))

    def _shape(self) -> tuple[list[Any], dict[str, Any]]:
        return [self.prompt], {"duration": self.duration}


@dataclass(frozen=True, kw_only=True)
class SfxRequest(MusicRequest):
    capability: ClassVar[str] = "sfx"


@dataclass(frozen=True, kw_only=True)
class SongRequest(Request):
    capability: ClassVar[str] = "song"
    OUTPUTS: ClassVar[tuple[str, ...]] = ("dst",)
    lyrics: str
    dst: Path
    style: str = ""
    duration: float | None = None
    seed: int | None = None
    sections: Sequence[Mapping[str, Any]] = ()  # the song's own structure: kind, lines, style
    avoid: str = ""
    bpm: float | None = None
    musical_key: str | None = None
    language: str | None = None
    vocal_gender: str | None = None  # "female" or "male", for a model with its own setting
    instrumental: bool = False
    repaint: Repaint | None = None
    guide: Guide | None = None

    def billable(self) -> Billable:
        return Billable(
            capability="song", duration=float(self.duration or 0.0), guided=self.guide is not None
        )

    def _shape(self) -> tuple[list[Any], dict[str, Any]]:
        kw: dict[str, Any] = {"style": self.style, "duration": self.duration, "seed": self.seed}
        if self.repaint is not None:
            kw.update(
                task_type="repaint",
                src_audio_path=self.repaint.source,
                repainting_start=self.repaint.start_sec,
                repainting_end=self.repaint.end_sec,
            )
        else:
            kw.update(
                sections=[dict(s) for s in self.sections],
                avoid=self.avoid,
                bpm=self.bpm,
                key=self.musical_key,
                language=self.language,
                instrumental=self.instrumental,
            )
            if self.vocal_gender:
                kw["vocal_gender"] = self.vocal_gender
        if self.guide is not None:  # only when set, so a take paid for before guides keeps its key
            kw["guide"] = {"source": self.guide.source, "use": self.guide.use}
        return [self.lyrics], kw


@dataclass(frozen=True, kw_only=True)
class TranscribeRequest(Request):
    capability: ClassVar[str] = "transcribe"
    src: Path

    def billable(self) -> Billable:
        return Billable(capability="transcribe", duration=_seconds(self.src))


@dataclass(frozen=True, kw_only=True)
class LipsyncRequest(Request):
    """A clip with its mouth matched to a line. The shorter of the two sets the length."""

    capability: ClassVar[str] = "lipsync"
    OUTPUTS: ClassVar[tuple[str, ...]] = ("dst",)
    video: Path
    audio: Path
    dst: Path

    def billable(self) -> Billable:
        return Billable(capability="lipsync", duration=_seconds(self.video))

    def _shape(self) -> tuple[list[Any], dict[str, Any]]:
        return [self.video, self.audio], {}


@dataclass(frozen=True, kw_only=True)
class SingRequest(Request):
    """A shot sung in one call: its still and the line it sings in, and the voice moves the face,
    the mouth and the body, so nothing is synced afterwards. It runs as long as the line, unless
    the model makes set lengths."""

    capability: ClassVar[str] = "sing"
    OUTPUTS: ClassVar[tuple[str, ...]] = ("dst",)
    prompt: str
    still: Path
    audio: Path
    dst: Path
    aspect: str
    references: tuple[Reference, ...] = ()  # the kit, for a model that takes pictures besides it
    seed: int | None = None

    def billable(self) -> Billable:
        return Billable(capability="sing", duration=_seconds(self.audio), image=True)

    def _shape(self) -> tuple[list[Any], dict[str, Any]]:
        kw: dict[str, Any] = {"aspect": self.aspect, "seed": self.seed}
        if self.references:
            kw["references"] = [r.shape() for r in self.references]
        return [self.prompt, self.still, self.audio], kw


@dataclass(frozen=True, kw_only=True)
class SeparateRequest(Request):
    """A mix split into its vocals and everything else."""

    capability: ClassVar[str] = "separate"
    OUTPUTS: ClassVar[tuple[str, ...]] = ("vocals", "rest")
    src: Path
    vocals: Path
    rest: Path

    def billable(self) -> Billable:
        return Billable(capability="separate", duration=_seconds(self.src))

    def _shape(self) -> tuple[list[Any], dict[str, Any]]:
        return [self.src, self.rest], {}


@dataclass(frozen=True, kw_only=True)
class GraphicsRequest(Request):
    """A composition folder rendered to a file."""

    capability: ClassVar[str] = "graphics"
    OUTPUTS: ClassVar[tuple[str, ...]] = ("dst",)
    folder: Path
    dst: Path
    fps: float | None = None

    def _shape(self) -> tuple[list[Any], dict[str, Any]]:
        return [self.folder], ({"fps": self.fps} if self.fps else {})


@dataclass(frozen=True, kw_only=True)
class SearchRequest(Request):
    capability: ClassVar[str] = "search"
    query: str
    limit: int = 5
