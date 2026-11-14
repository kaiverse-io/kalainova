"""A studio that makes real media with ffmpeg and runs no model, for testing the whole line."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from kalainova import media
from kalainova.jobfs import Job
from kalainova.providers import base

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

    def takes_end_image(self, capability, model=None):
        return Studio.end_image and capability == "video"

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

    def _log(self, capability: str, **kw) -> None:
        Studio.calls.append({"capability": capability, **kw})

    def voice(self, text, dst, *, voice=None, **kw):
        self._log("voice", text=text)
        media.run(["-f", "lavfi", "-i", "sine=f=220:d=1.2:r=48000", "-ac", "1", str(dst)])
        words = [
            {"start_sec": i * 0.2, "end_sec": (i + 1) * 0.2, "text": w, "confidence": 0.9}
            for i, w in enumerate(text.split())
        ]
        return base.Result(path=dst, model="fake-voice", words=words)

    def image(self, prompt, dst, *, width, height, **kw):
        self._log("image", prompt=prompt, **{k: v for k, v in kw.items() if k == "seed"})
        Image.linear_gradient("L").resize((width, height)).convert("RGB").save(dst, format="PNG")
        return base.Result(path=dst, model="fake-image")

    def video(self, prompt, dst, *, duration, aspect, image=None, **kw):
        n = sum(1 for c in Studio.calls if c["capability"] == "video")
        self._log(
            "video",
            prompt=prompt,
            image=image,
            seed=kw.get("seed"),
            duration=duration,
            end_image=kw.get("end_image"),
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
                f"{source}:d={duration + 0.5:.2f}:r=24",
                "-pix_fmt",
                "yuv420p",
                str(dst),
            ]
        )
        return base.Result(path=dst, model="fake-video", meta={"seed": kw.get("seed")})

    def music(self, prompt, dst, *, duration, **kw):
        self._log("music", prompt=prompt)
        media.run(["-f", "lavfi", "-i", f"sine=f=330:d={duration}:r=48000", "-ac", "2", str(dst)])
        return base.Result(path=dst, model="fake-music")

    def song(self, lyrics, dst, *, style="", duration=None, **kw):
        self._log("song", lyrics=lyrics, style=style, seed=kw.get("seed"), kw=kw)
        seconds = float(duration or 20)
        source = (
            f"anullsrc=r=48000:cl=stereo:d={seconds}"
            if Studio.silent_song
            else _PULSED.format(seconds=seconds)
        )
        media.run(["-f", "lavfi", "-i", source, "-ac", "2", str(dst)])
        return base.Result(path=dst, model="fake-song", meta={"seed": kw.get("seed")})

    def sfx(self, prompt, dst, *, duration=1.0, **kw):
        self._log("sfx", prompt=prompt)
        media.run(
            [
                "-f",
                "lavfi",
                "-i",
                f"anoisesrc=d={duration}:c=pink:r=48000:a=0.2",
                "-ac",
                "2",
                str(dst),
            ]
        )
        return base.Result(path=dst, model="fake-sfx")

    def transcribe(self, src, **kw):
        self._log("transcribe")
        return base.Result(model="fake-whisper", words=list(Studio.heard))

    def lipsync(self, video, audio, dst, **kw):
        self._log("lipsync", video=video, audio=audio)
        # like the vendor's cut_off: the shorter input sets the length
        shortest = min(media.duration(video), media.duration(audio))
        media.run(["-i", str(video), "-t", f"{shortest:.3f}", "-c", "copy", str(dst)])
        return base.Result(path=dst, model="fake-lipsync")

    def separate(self, src, vocals, rest, **kw):
        self._log("separate")
        shutil.copyfile(src, vocals)
        shutil.copyfile(src, rest)
        return base.Result(path=vocals, model="fake-split")

    def graphics(self, folder, dst, **kw):
        self._log("graphics", folder=folder)
        media.run(
            ["-f", "lavfi", "-i", "testsrc2=s=320x180:d=2:r=24", "-pix_fmt", "yuv420p", str(dst)]
        )
        return base.Result(path=dst, model="fake-graphics")

    def llm(self, prompt, **kw):
        self._log("llm", prompt=prompt, **kw)
        return base.Result(
            text=Studio.replies.pop(0) if Studio.replies else "{}",
            model=kw.get("model") or "fake-llm",
        )

    def judge(self, prompt, **kw):
        self._log("judge", prompt=prompt, **kw)
        return base.Result(
            text=Studio.replies.pop(0) if Studio.replies else "{}",
            model=kw.get("model") or "fake-judge",
        )

    def search(self, query, *, limit=5, **kw):
        self._log("search", query=query)
        return base.Result(model="fake-search", meta={"hits": list(Studio.hits)})


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
