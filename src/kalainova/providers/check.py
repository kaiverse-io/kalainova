"""Prove an adapter against the live service, once, with the smallest call it supports.

Tests run on fakes, so nothing else shows that an adapter matches a vendor's real reply. This makes
one cheap call per capability through the same router every job uses, so the ledger records it, and
says whether the service was reached, whether the reply matched what the adapter reads, and what it
charged against what the price table said.

It is opt-in on every side. `plan` only prices the calls. `run` needs the caller to have said they
mean to spend, a job with a cost cap, and no sign of automation. CI and the tests never reach it.
"""

from __future__ import annotations

import math
import os
import struct
import wave
import zlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .. import config
from ..jobfs import ContractError, Job
from . import base, router
from .contract import (
    ImageRequest,
    JudgeRequest,
    MusicRequest,
    Reference,
    Request,
    SearchRequest,
    SfxRequest,
    TextRequest,
    TranscribeRequest,
    VideoRequest,
    VoiceRequest,
)

AUTOMATION = ("CI", "PYTEST_CURRENT_TEST", "GITHUB_ACTIONS")
WALL, SQUARE = "a plain grey wall", "a plain grey square"
SCHEMA_SIGNS = ("KeyError", "IndexError", "ValueError", "rejected output", "returned no file")


@dataclass
class Call:
    """One smallest call: what it asks, what the price table expects it to cost."""

    request: Request
    estimated: float | None
    label: str = ""  # what the line is called when one capability has several routes

    @property
    def capability(self) -> str:
        return self.request.capability


@dataclass
class Outcome:
    capability: str
    status: str  # passed, schema mismatch, not reached, unchecked
    model: str = ""
    estimated: float | None = None
    charged: float = 0.0
    detail: str = ""


def _tone(path: Path, seconds: float = 3.0) -> Path:
    """A quiet tone, written without a codec, to hand to a transcription service."""
    rate = 16000
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        frames = (
            struct.pack("<h", int(2000 * math.sin(2 * math.pi * 220 * i / rate)))
            for i in range(int(rate * seconds))
        )
        out.writeframes(b"".join(frames))
    return path


def _grey_png(path: Path, side: int = 256) -> Path:
    """A flat grey picture, written by hand, to give a model as a first frame or a reference.

    256 px a side: Wan refuses anything under 240 (found live, 2026-11-12).
    """

    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body)
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    rows = b"".join(b"\x00" + b"\x80\x80\x80" * side for _ in range(side))
    header = struct.pack(">IIBBBBB", side, side, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    return path


# What no cheap call exists for: a whole track, a clip plus a line to sync, a mix to split.
NO_CHEAP_CALL = {
    "song": "a song is a whole track, so no call is small",
    "lipsync": "needs a clip and a line, and bills by the minute",
    "separate": "needs a full mix to split",
    "graphics": "renders on this machine and calls no service",
}


def _request(capability: str, work: Path) -> Request:
    """The smallest call this capability has."""
    dst = work / f"check.{capability}"
    if capability == "llm":
        return TextRequest(prompt="Reply with the single word ok.", max_tokens=16)
    if capability == "judge":
        return JudgeRequest(prompt="Reply with the single word ok.", max_tokens=16)
    if capability == "voice":
        return VoiceRequest(text="Check.", dst=dst.with_suffix(".mp3"))
    if capability == "image":
        return ImageRequest(prompt=SQUARE, dst=dst.with_suffix(".png"), width=512, height=512)
    if capability == "video":
        return VideoRequest(prompt=WALL, dst=dst.with_suffix(".mp4"), duration=2.0, aspect="16:9")
    if capability == "music":
        return MusicRequest(prompt="a single soft note", dst=dst.with_suffix(".wav"), duration=5.0)
    if capability == "sfx":
        return SfxRequest(prompt="a short click", dst=dst.with_suffix(".wav"), duration=1.0)
    if capability == "transcribe":
        return TranscribeRequest(src=_tone(work / "check.tone.wav"))
    if capability == "search":
        return SearchRequest(query="water", limit=1)
    raise KeyError(capability)


def plan(job: Job, name: str, capability: str | None = None) -> tuple[list[Call], list[Outcome]]:
    """The calls that would be made and their cost, and the capabilities with no cheap one."""
    provider = base.get(name)
    wanted = [capability] if capability else list(provider.capabilities)
    work = job.work / "checks"
    work.mkdir(parents=True, exist_ok=True)
    calls: list[Call] = []
    unchecked: list[Outcome] = []
    for cap in wanted:
        if cap not in provider.capabilities:
            raise ContractError(f"{name} has no {cap}; it has {', '.join(provider.capabilities)}")
        if cap in NO_CHEAP_CALL:
            unchecked.append(Outcome(cap, "unchecked", detail=NO_CHEAP_CALL[cap]))
            continue
        request = _request(cap, work)
        calls.append(Call(request, provider.estimate(request.billable()), cap))
        if cap == "video":  # the routes a moving shot really takes, not only text to video
            calls.extend(_video_routes(provider, work))
    return calls, unchecked


def _video_routes(provider: base.Provider, work: Path) -> list[Call]:
    """A clip from a still, and one from a reference, for a provider that takes them."""
    still = _grey_png(work / "check.still.png")
    dst = work / "check.video.mp4"
    routes = [
        ("video from a still", VideoRequest(prompt=WALL, dst=dst, duration=2.0, aspect="16:9",
                                            start=still)),
        ("video from a reference", VideoRequest(
            prompt=WALL, dst=dst, duration=2.0, aspect="16:9",
            references=(Reference(path=still, label="a plain grey square"),),
        )),
    ]  # fmt: skip
    try:
        takes_refs = provider.inputs(
            "video", config.model_for(provider.name, "reference_to_video") or None
        ).references
    except KeyError:
        takes_refs = 0
    return [
        Call(request, provider.estimate(request.billable()), label)
        for label, request in routes
        if takes_refs or not request.references
    ]


def refuse_automation(env: Mapping[str, str]) -> None:
    for key in AUTOMATION:
        if env.get(key):
            raise ContractError(
                f"a live check makes real, paid calls, so never under automation ({key} is set)"
            )


def _classify(message: str) -> str:
    return "schema mismatch" if any(sign in message for sign in SCHEMA_SIGNS) else "not reached"


def run(job: Job, name: str, calls: list[Call], *, spend: bool) -> list[Outcome]:
    """Make each call once. Refuses unless the caller said they mean to spend, under a cap."""
    provider = base.get(name)
    if not spend:
        raise ContractError("a live check spends money: say so with --spend")
    if not provider.free and job.job.get("cost_cap") is None:
        raise ContractError(
            f"{job.id} has no cost_cap, and a live check runs inside one so the ledger holds it"
        )
    outcomes = []
    for call in calls:
        before = job.spent()
        try:
            _, res = router.generate(
                job, call.request, only=[name], fresh=True, note=f"live check {name}"
            )
        except (router.ProviderError, ContractError) as exc:
            message = str(exc)
            outcomes.append(
                Outcome(
                    call.label or call.capability,
                    _classify(message),
                    estimated=call.estimated,
                    charged=round(job.spent() - before, 6),
                    detail=message[:300],
                )
            )
            continue
        outcomes.append(
            Outcome(
                call.label or call.capability,
                "passed",
                model=res.model,
                estimated=call.estimated,
                charged=round(res.cost, 6),
            )
        )
    return outcomes


def verify_marks(model: str) -> list[str]:
    """Lines marked VERIFY for this model, in the repo's config and any private one laid over it."""
    paths = [config.REPO / "config" / "studio.yaml"]
    if private := os.environ.get("KALAINOVA_CONFIG"):
        paths.append(Path(private))
    if not model:
        return []
    return [
        line.strip()
        for path in paths
        if path.exists()
        for line in path.read_text().splitlines()
        if "VERIFY" in line and model in line
    ]


def cli(name: str, job_ref: str | None, capability: str | None, spend: bool) -> int:
    """Print what would be called and what it should cost, and make the calls only when told to."""
    from ..jobfs import open_job

    refuse_automation(os.environ)
    if not job_ref:
        raise ContractError("--check runs inside a job with a cost_cap: name it with --job")
    job = open_job(job_ref)
    calls, unchecked = plan(job, name, capability)
    known = [c.estimated for c in calls if c.estimated is not None]
    for c in calls:
        shown = "no price" if c.estimated is None else f"about ${c.estimated:.4f}"
        print(f"  {c.label or c.capability:<22} {shown}")
    for u in unchecked:
        print(f"  {u.capability:<11} unchecked: {u.detail}")
    print(f"estimated total ${sum(known):.4f}; cap {job.job.get('cost_cap')}")
    outcomes = run(job, name, calls, spend=spend)
    for o in outcomes:
        gap = "" if o.estimated is None else f", estimated {o.estimated:.4f}"
        print(f"  {o.capability:<11} {o.status}: {o.model} charged {o.charged:.4f}{gap} {o.detail}")
        if o.status == "passed":
            for line in verify_marks(o.model):
                print(f"    VERIFY still marked, clear it and date it: {line}")
    return 0 if all(o.status == "passed" for o in outcomes) else 1
