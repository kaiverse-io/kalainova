"""What comes back from a call, and what goes with it, in the engine's terms (ADR 0023).

`Result` carries the engine's facts as fields; the router writes them into a file's record under
the names in `RECORDED`, which no adapter may write itself. `Context` is one attempt as the router
hands it to an adapter, with the `Receipt` the adapter fills. `Inputs` is what a model can be given.
Imported through providers/contract.py.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypedDict

# What the router writes into a file's record from a result's typed facts. Adapters keep their own
# provenance in `Result.meta`, under any other name; these names belong to the engine.
RECORDED = ("seed", "seed_sent", "start_frame_sent", "end_frame_sent", "billed_sec")


class Word(TypedDict):
    start_sec: float
    end_sec: float
    text: str
    confidence: float


class Hit(TypedDict, total=False):
    """A candidate source. Nothing here decides it is true."""

    url: str
    title: str
    publisher: str
    published: str
    reliability: str
    text: str


@dataclass(frozen=True)
class Sent:
    """What reached the model, for a clip a frame or a seed decides."""

    start_frame: bool | None = None
    end_frame: bool | None = None
    seeded: bool | None = None  # False: the model takes no seed, so the take cannot be remade


@dataclass
class Receipt:
    """What the vendor said about one call. Filled as it is learned, so a failed call keeps it."""

    request_id: str | None = None  # the vendor's id for the request, as its bill lists it
    billed_units: float | None = None
    vendor_cost: float | None = None  # billed units times this account's unit price


@dataclass
class Result:
    path: Path | None = None
    cost: float = 0.0
    model: str = ""
    words: list[Word] = field(default_factory=list)  # seconds from the start of this file
    text: str = ""
    hits: list[Hit] = field(default_factory=list)
    seed: int | None = None  # the seed the model used, when it says or was given one
    sent: Sent | None = None
    billed_seconds: float | None = None
    version: str | None = None
    meta: dict[str, Any] = field(
        default_factory=dict
    )  # provenance; the engine decides nothing on it

    def recorded(self) -> dict[str, Any]:
        """The typed facts under the engine's own names, for the file's record."""
        out: dict[str, Any] = {}
        if self.seed is not None:
            out["seed"] = self.seed
        if self.sent is not None:
            if self.sent.start_frame is not None:
                out["start_frame_sent"] = self.sent.start_frame
            if self.sent.end_frame is not None:
                out["end_frame_sent"] = self.sent.end_frame
            if self.sent.seeded is False:
                out["seed_sent"] = False
                out.pop("seed", None)
        if self.billed_seconds is not None:
            out["billed_sec"] = self.billed_seconds
        return out


@dataclass(frozen=True)
class Context:
    """One attempt, as the router hands it to an adapter."""

    job: str = ""
    attempt: str = ""
    labels: Mapping[str, str] = field(default_factory=dict)  # job, attempt, run, stage, shot
    model: str | None = None  # the pinned model for this provider, else the adapter's default
    deadline_sec: float | None = None  # for an adapter that keeps its own deadline
    receipt: Receipt = field(default_factory=Receipt)
    signed: tuple[str, ...] | None = None  # the payload digests a person signed; None: unbound


@dataclass(frozen=True)
class Inputs:
    """What a model can be given, said in the engine's terms."""

    references: int = 0  # the most reference pictures it takes; 0: it cannot hold a face
    characters: int | None = None  # the most characters it holds at once, when it says
    start_with_references: bool = False  # takes the first frame apart from its references
    end_frame: bool = False  # takes the last frame as a picture
    seed: bool = True
    longest_sec: float | None = None
    repaint: bool = False  # can remake one span of a song and keep the rest
