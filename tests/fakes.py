"""A studio that makes real media with ffmpeg and runs no model, for testing the whole line."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from kalainova import media
from kalainova.jobfs import Job
from kalainova.providers import base
from kalainova.providers.contract import Context, Result
from kalainova.providers.transport import Reply as TransportReply
from kalainova.providers.transport import Transport

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
EVERY = (
    "voice",
    "image",
    "video",
    "music",
    "song",
    "sfx",
    "transcribe",
    "lipsync",
    "separate",
    "graphics",
    "llm",
    "judge",
    "search",
)


# A 330 Hz tone struck every half second (120 bpm), the first strike of each four louder, so the
# placeholder song has the steady pulse a track must have to be cut to its music.
_PULSED = (
    "aevalsrc=sin(2*PI*330*t)*exp(-12*mod(t\\,0.5))*(0.5+0.5*lt(mod(t\\,2)\\,0.5))"
    ":d={seconds}:s=48000"
)


class Studio(base.Provider):
    """Each attempt is logged, so a test can read what the engine asked for."""

    name = "fake"
    capabilities = EVERY
    free = True
    calls: list[dict] = []
    frozen_takes = 0  # this many video attempts come back with nothing moving
    fail_video = False
    replies: list[str] = []
    heard: list[dict] = []
    hits: list[dict] = []
    silent_song = False
    end_image = False  # a model that takes the last frame as a picture
    can_repaint = True  # a song model that remakes one span of a take and keeps the rest

    references = 0  # takes no reference pictures, unless a test says it does

    def inputs(self, capability, model=None):
        return replace(
            super().inputs(capability, model),
            references=Studio.references,
            end_frame=Studio.end_image and capability == "video",
            repaint=self.can_repaint and capability == "song",
        )

    @classmethod
    def reset(cls) -> None:
        cls.calls = []
        cls.frozen_takes = 0
        cls.fail_video = False
        cls.replies = []
        cls.heard = []
        cls.hits = []
        cls.silent_song = False
        cls.end_image = False
        cls.references = 0

    def _log(self, capability: str, **kw) -> None:
        Studio.calls.append({"capability": capability, **kw})

    def voice(self, req, ctx):
        self._log("voice", text=req.text, voice=req.voice, model=ctx.model)
        media.run(["-f", "lavfi", "-i", "sine=f=220:d=1.2:r=48000", "-ac", "1", str(req.dst)])
        words = [
            {"start_sec": i * 0.2, "end_sec": (i + 1) * 0.2, "text": w, "confidence": 0.9}
            for i, w in enumerate(req.text.split())
        ]
        return Result(path=req.dst, model="fake-voice", words=words)

    def image(self, req, ctx):
        self._log(
            "image", prompt=req.prompt, **({"seed": req.seed} if req.seed is not None else {})
        )
        Image.linear_gradient("L").resize((req.width, req.height)).convert("RGB").save(
            req.dst, format="PNG"
        )
        return Result(path=req.dst, model="fake-image")

    def video(self, req, ctx):
        n = sum(1 for c in Studio.calls if c["capability"] == "video")
        self._log(
            "video",
            prompt=req.prompt,
            image=req.start,
            seed=req.seed,
            duration=req.duration,
            end_image=req.end,
            references=req.references,
            model=ctx.model,
        )
        if Studio.fail_video:
            raise RuntimeError("the model is down")
        # Bars have detail and never change: frozen, and still a picture.
        source = "smptebars=s=320x180" if n < Studio.frozen_takes else "testsrc2=s=320x180"
        media.run(
            [
                "-f",
                "lavfi",
                "-i",
                f"{source}:d={req.duration + 0.5:.2f}:r=24",
                "-pix_fmt",
                "yuv420p",
                str(req.dst),
            ]
        )
        return Result(path=req.dst, model="fake-video", seed=req.seed)

    def music(self, req, ctx):
        self._log("music", prompt=req.prompt)
        media.run(
            ["-f", "lavfi", "-i", f"sine=f=330:d={req.duration}:r=48000", "-ac", "2", str(req.dst)]
        )
        return Result(path=req.dst, model="fake-music")

    def song(self, req, ctx):
        kw = req._shape()[1]
        self._log("song", lyrics=req.lyrics, style=req.style, seed=req.seed, kw=kw)
        seconds = float(req.duration or 20)
        source = (
            f"anullsrc=r=48000:cl=stereo:d={seconds}"
            if Studio.silent_song
            else _PULSED.format(seconds=seconds)
        )
        media.run(["-f", "lavfi", "-i", source, "-ac", "2", str(req.dst)])
        return Result(path=req.dst, model="fake-song", seed=req.seed)

    def sfx(self, req, ctx):
        self._log("sfx", prompt=req.prompt)
        media.run(
            [
                "-f",
                "lavfi",
                "-i",
                f"anoisesrc=d={req.duration}:c=pink:r=48000:a=0.2",
                "-ac",
                "2",
                str(req.dst),
            ]
        )
        return Result(path=req.dst, model="fake-sfx")

    def transcribe(self, req, ctx):
        self._log("transcribe")
        return Result(model="fake-whisper", words=list(Studio.heard))

    def lipsync(self, req, ctx):
        self._log("lipsync", video=req.video, audio=req.audio)
        # like the vendor's cut_off: the shorter input sets the length
        shortest = min(media.duration(req.video), media.duration(req.audio))
        media.run(["-i", str(req.video), "-t", f"{shortest:.3f}", "-c", "copy", str(req.dst)])
        return Result(path=req.dst, model="fake-lipsync")

    def separate(self, req, ctx):
        self._log("separate")
        shutil.copyfile(req.src, req.vocals)
        shutil.copyfile(req.src, req.rest)
        return Result(path=req.vocals, model="fake-split")

    def graphics(self, req, ctx):
        self._log("graphics", folder=req.folder, fps=req.fps)
        media.run(
            [
                "-f",
                "lavfi",
                "-i",
                "testsrc2=s=320x180:d=2:r=24",
                "-pix_fmt",
                "yuv420p",
                str(req.dst),
            ]
        )
        return Result(path=req.dst, model="fake-graphics")

    def _text(self, capability, req, ctx, default):
        self._log(
            capability,
            prompt=req.prompt,
            system=req.system,
            images=list(req.images),
            max_tokens=req.max_tokens,
            model=ctx.model,
            judging=req.judging,
        )
        return Result(
            text=Studio.replies.pop(0) if Studio.replies else "{}",
            model=ctx.model or default,
        )

    def llm(self, req, ctx):
        return self._text("llm", req, ctx, "fake-llm")

    def judge(self, req, ctx):
        return self._text("judge", req, ctx, "fake-judge")

    def search(self, req, ctx):
        self._log("search", query=req.query)
        return Result(model="fake-search", hits=list(Studio.hits))


class Wire(Transport):
    """A vendor's transport with no network: each send is kept, and answered from `replies`.

    `files` maps a reply address to the bytes a fetch writes there; any other address gets a short
    tone or a frame, made by ffmpeg, of the destination's kind."""

    platform = "wire"

    def __init__(
        self, *replies: Any, files: dict[str, bytes] | None = None, default: Any = None
    ) -> None:
        self.sent: list[dict[str, Any]] = []
        self.replies = list(replies)
        self.default = default if default is not None else {}
        self.files = dict(files or {})
        self.uploaded: list[Path] = []

    def _send(self, endpoint, payload, ctx, *, wait, params):
        self.sent.append({"endpoint": endpoint, "payload": payload, "params": params, "ctx": ctx})
        reply = self.replies.pop(0) if self.replies else self.default
        if isinstance(reply, Exception):
            raise reply
        return reply if isinstance(reply, TransportReply) else TransportReply(data=reply)

    def _upload(self, path):
        self.uploaded.append(Path(path))
        return f"up:{Path(path).name}"

    def _download(self, url, dst):
        if url in self.files:
            Path(dst).write_bytes(self.files[url])
            return
        suffix = Path(dst).suffix.lower()
        if suffix in (".png", ".jpg"):
            Image.new("RGB", (64, 64), (128, 128, 128)).save(dst, format="PNG")
        elif suffix in (".mp4", ".mov"):
            media.run(["-f", "lavfi", "-i", "testsrc2=s=64x64:d=1:r=24", "-pix_fmt", "yuv420p",
                       "-f", "mp4", str(dst)])  # fmt: skip
        else:
            media.run(["-f", "lavfi", "-i", "sine=f=220:d=1:r=48000", "-f", "wav", str(dst)])

    @property
    def payloads(self) -> list[dict[str, Any]]:
        return [s["payload"] for s in self.sent]


def context(**kw: Any) -> Context:
    """The router's per-call context, for a test that calls an adapter directly."""
    return Context(job=kw.pop("job", "t"), attempt=kw.pop("attempt", "a1"), **kw)


@pytest.fixture
def studio(monkeypatch, tmp_path):
    """The fake provider, registered, and clean. Media goes in a folder of this test's own."""
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    base.names()
    monkeypatch.setitem(base._REGISTRY, "fake", Studio)
    Studio.reset()
    yield Studio
    Studio.reset()


def make_job(tmp_path: Path, *, beats=None, packet=None, job_id="p1", **extra) -> Job:
    """A job that uses only the fake provider, optionally with a script already written."""
    folder = tmp_path / "jobs" / job_id
    folder.mkdir(parents=True)
    data = {
        "schema_version": "0.1",
        "job_id": job_id,
        "strategy": "generated",
        "media": ["video", "audio"],
        "rights": "owned",
        "distribution_identity": "test",
        "status": "draft",
        "skip_funded": True,
        "cost_cap": None,
        "profile": "square",
        "providers": {capability: ["fake"] for capability in EVERY},
        "brief": {"subject": "a test", "max_video_beats": 9},
        **extra,
    }
    (folder / "job.json").write_text(json.dumps(data))
    job = Job(folder)
    if beats is not None:
        job.write(
            "script_packet",
            {"schema_version": "0.1", "job_id": job_id, "beats": beats, **(packet or {})},
        )
    return job


def cover_source(
    job: Job, *, origin: str = "a recording the operator made", reference: str = "brief.md"
) -> Job:
    """Give a job what a cut needs: where its source came from, and the file that covers its use."""
    (job.folder / reference).write_text("This job may cut the recording it was given.\n")
    data = json.loads((job.folder / "job.json").read_text())
    data.setdefault("brief", {})["source"] = {"origin": origin, "reference": reference}
    (job.folder / "job.json").write_text(json.dumps(data))
    return Job(job.folder)


class Reply:
    """A vendor's HTTP reply."""

    def __init__(self, *, status=200, body=None, content=b"", text=""):
        self.status_code = status
        self.body = body or {}
        self.content = content
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise OSError(f"{self.status_code}")

    def json(self):
        return self.body
