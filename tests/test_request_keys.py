"""A request's content key is the one the router wrote before requests were typed (ADR 0023).

`generations.jsonl` names every paid file by this key, and a restart reuses a file whose key it
finds instead of paying for it again. So moving to typed requests must not change a key: the hex
values below were computed by the router before the change, for requests shaped as the engine
makes them, and `v1` is that router's function, kept here to compare against.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kalainova.blobstore import sha256_file
from kalainova.providers.contract import (
    Card,
    GraphicsRequest,
    ImageRequest,
    LipsyncRequest,
    MotionRequest,
    MusicRequest,
    Pin,
    Reference,
    Repaint,
    SeparateRequest,
    SfxRequest,
    SongRequest,
    TextRequest,
    VideoRequest,
    VoiceRequest,
)

OUTPUT_ARG = {"voice": 1, "image": 1, "video": 1, "music": 1, "song": 1, "sfx": 1,
              "lipsync": 2, "motion": 2, "separate": 1, "graphics": 1}  # fmt: skip


def v1(capability: str, fn_name: str, args: tuple, kw: dict) -> str:
    """The router's request key before ADR 0023, unchanged."""

    def plain(value):
        if isinstance(value, Path):
            return sha256_file(value) if value.is_file() else str(value)
        if isinstance(value, dict):
            return {k: plain(v) for k, v in value.items()}
        if isinstance(value, list | tuple):
            return [plain(v) for v in value]
        return value

    at = OUTPUT_ARG[capability]
    request = {
        "capability": capability,
        "fn": fn_name,
        "dst": Path(args[at]).name,
        "args": [plain(a) for i, a in enumerate(args) if i != at],
        "kw": {k: plain(v) for k, v in kw.items()},
    }
    return hashlib.sha256(json.dumps(request, sort_keys=True, default=str).encode()).hexdigest()


@pytest.fixture
def files(tmp_path):
    def made(name, data):
        path = tmp_path / name
        path.write_bytes(data)
        return path

    found = {
        "still": made("s.png", b"still"),
        "end": made("e.png", b"end"),
        "face": made("face.png", b"face"),
        "side": made("side.png", b"side"),
        "wav": made("v.wav", b"wave"),
        "clip": made("c.mp4", b"clip"),
        "dir": tmp_path,
    }
    (tmp_path / "comp").mkdir()
    return found


def _ref(path, label, group="", sha=""):
    return {"path": path, "sha256": sha, "label": label, "group": group}


def _cases(f):
    """(name, typed request, the old call: capability, fn, args, kw, recorded key or None)."""
    d = f["dir"]
    ana = Reference(path=f["face"], label="Ana", group="ana", sha256="abc")
    ana_side = Reference(path=f["side"], label="Ana side", group="ana", sha256="def")
    sections = [{"kind": "verse", "lines": ["la"]}]
    return [
        (
            "video_plain",
            VideoRequest(
                prompt="a wall",
                dst=d / "b1.video.mp4",
                duration=5,
                aspect="9:16",
                start=f["still"],
                seed=7,
            ),
            (
                "video",
                "video",
                ("a wall", d / "b1.video.mp4"),
                {"duration": 5, "aspect": "9:16", "image": f["still"], "seed": 7, "audio": False},
            ),
            "c2bfb8e7d9dffd1d74ff9ee3c6cdb5b97e2431d38ac8ccd4fd403428cdf05947",
        ),
        (
            "video_end",
            VideoRequest(
                prompt="a wall",
                dst=d / "b1.video.mp4",
                duration=5,
                aspect="9:16",
                start=f["still"],
                end=f["end"],
                seed=7,
            ),
            (
                "video",
                "video",
                ("a wall", d / "b1.video.mp4"),
                {
                    "duration": 5,
                    "aspect": "9:16",
                    "image": f["still"],
                    "seed": 7,
                    "audio": False,
                    "end_image": f["end"],
                },
            ),
            "91f7e87d9e59d99d9e1d292d9b05951f80832a4f7b6fba5137a2c5c5043eec0d",
        ),
        (
            "video_refs",
            VideoRequest(
                prompt="a wall",
                dst=d / "t.mp4",
                duration=5.0,
                aspect="9:16",
                start=f["still"],
                seed=3,
                sound=True,
                references=(ana, ana_side),
                pin=Pin(provider="fal", model="m/o3"),
            ),
            (
                "video",
                "video",
                ("a wall", d / "t.mp4"),
                {
                    "duration": 5.0,
                    "aspect": "9:16",
                    "image": f["still"],
                    "seed": 3,
                    "audio": True,
                    "references": [
                        _ref(f["face"], "Ana", "ana", "abc"),
                        _ref(f["side"], "Ana side", "ana", "def"),
                    ],
                    "model": "m/o3",
                },
            ),
            "59a8930cd2879f908a099ef647fd36a72a6819da3596e50aefbcd4851a017d36",
        ),
        (
            "image_plain",
            ImageRequest(prompt="a still", dst=d / "b1.still.png", width=1080, height=1920),
            ("image", "image", ("a still", d / "b1.still.png"), {"width": 1080, "height": 1920}),
            "89f70727bc81c663119699fc67fc92cf27d1dd4c1c91de615d4ff44a93a0827f",
        ),
        (
            "image_seed",
            ImageRequest(
                prompt="a still", dst=d / "b1.still.png", width=1080, height=1920, seed=11
            ),
            (
                "image",
                "image",
                ("a still", d / "b1.still.png"),
                {"width": 1080, "height": 1920, "seed": 11},
            ),
            "13ee310b5dcf3b868c57d542009dc565501cec88d3f4b3fa0da7149cfcb228d3",
        ),
        (
            "image_card",
            ImageRequest(
                prompt="end. style",
                dst=d / "b1.end.png",
                width=1080,
                height=1920,
                card=Card(title="end", palette=0, theme="studio"),
            ),
            (
                "image",
                "image",
                ("end. style", d / "b1.end.png"),
                {"width": 1080, "height": 1920, "title": "end", "palette": 0, "style": "studio"},
            ),
            "a83131492458bcca74ce4e5396f48d11f147cac14097148d1ba0ee04f1b1a078",
        ),
        (
            "image_refs",
            ImageRequest(
                prompt="a still",
                dst=d / "b1.still.png",
                width=1080,
                height=1920,
                references=(Reference(path=f["face"], label="Ana", sha256="abc"),),
                pin=Pin(provider="fal", model="m/nb"),
            ),
            (
                "image",
                "image",
                ("a still", d / "b1.still.png"),
                {
                    "width": 1080,
                    "height": 1920,
                    "references": [_ref(f["face"], "Ana", "", "abc")],
                    "model": "m/nb",
                },
            ),
            "2a0b900843c634d011588023a895402d305d62446b96ce33b7a9165eaa10ee06",
        ),
        (
            "voice",
            VoiceRequest(text="hello", dst=d / "b1.voice.wav", next_text="next"),
            (
                "voice",
                "voice",
                ("hello", d / "b1.voice.wav"),
                {"voice": None, "previous_text": None, "next_text": "next"},
            ),
            "ec0a86b39163b7606fcda96e12dc99b3d624b15e436b5fc0c7f9fab0a30ec495",
        ),
        (
            "voice_kit",
            VoiceRequest(
                text="hello",
                dst=d / "b1.voice.wav",
                voice="vid",
                settings={"stability": 0.5},
                previous_text="a",
                pin=Pin(provider="elevenlabs", model="ev3"),
            ),
            (
                "voice",
                "voice",
                ("hello", d / "b1.voice.wav"),
                {
                    "voice": "vid",
                    "model": "ev3",
                    "settings": {"stability": 0.5},
                    "previous_text": "a",
                    "next_text": None,
                },
            ),
            "fbde66ffa8440220e078534d64a7aa7d0bf34ee621263d22c5a5dc827cb44d2b",
        ),
        (
            "song",
            SongRequest(
                lyrics="la la",
                dst=d / "song.wav",
                style="pop",
                duration=30.0,
                seed=5,
                sections=sections,
            ),
            (
                "song",
                "song",
                ("la la", d / "song.wav"),
                {
                    "style": "pop",
                    "duration": 30.0,
                    "seed": 5,
                    "sections": sections,
                    "avoid": "",
                    "bpm": None,
                    "key": None,
                    "language": None,
                    "instrumental": False,
                },
            ),
            None,
        ),
        (
            "song_repaint",
            SongRequest(
                lyrics="la la",
                dst=d / "song.wav",
                style="pop",
                duration=30.0,
                seed=5,
                repaint=Repaint(source=f["wav"], start_sec=1.0, end_sec=2.0),
            ),
            (
                "song",
                "song",
                ("la la", d / "song.wav"),
                {
                    "style": "pop",
                    "duration": 30.0,
                    "seed": 5,
                    "task_type": "repaint",
                    "src_audio_path": f["wav"],
                    "repainting_start": 1.0,
                    "repainting_end": 2.0,
                },
            ),
            "5de782453684c470f22a349e24bc61396fea7dbe9563dc362d9c69a9da62298d",
        ),
        (
            "music",
            MusicRequest(prompt="calm", dst=d / "music.wav", duration=30.0),
            ("music", "music", ("calm", d / "music.wav"), {"duration": 30.0}),
            "a89d113521a6542d37e123d52316f9c86f819a1d48dd7c8a75f7375062633010",
        ),
        (
            "sfx",
            SfxRequest(prompt="rain", dst=d / "b1.ambience.wav", duration=4.0),
            ("sfx", "sfx", ("rain", d / "b1.ambience.wav"), {"duration": 4.0}),
            "3987127153557658010f4a5d57f29f46d7dcd47ce4d0e79e557e58a772cd1587",
        ),
        (
            "lipsync",
            LipsyncRequest(video=f["clip"], audio=f["wav"], dst=d / "b1.synced.mp4"),
            ("lipsync", "lipsync", (f["clip"], f["wav"], d / "b1.synced.mp4"), {}),
            "e7db32d806b0eefb1a8d57a1340bc300f348d59ccd7c18071849b19d6d2bc03e",
        ),
        (
            "separate",
            SeparateRequest(src=f["wav"], vocals=d / "vocals.wav", rest=d / "rest.wav"),
            ("separate", "separate", (f["wav"], d / "vocals.wav", d / "rest.wav"), {}),
            None,
        ),  # the rest's path is in the key, and a test's folder differs each run
        (
            "graphics",
            GraphicsRequest(folder=d / "comp", dst=d / "c.mp4", fps=30.0),
            ("graphics", "graphics", (d / "comp", d / "c.mp4"), {"fps": 30.0}),
            None,
        ),
        (
            "motion",
            MotionRequest(character=f["still"], driving=f["clip"], dst=d / "m.mp4"),
            ("motion", "motion", (f["still"], f["clip"], d / "m.mp4"), {}),
            "6660eb87d2845767868875e334755cdb461794dbc3c2f4a6de06c152b4bd97a0",
        ),
    ]


def test_a_typed_request_keeps_the_key_its_file_was_paid_under(files):
    for name, request, old, recorded in _cases(files):
        assert request.key() == v1(*old), f"{name}: the key changed, so a paid file is paid again"
        if recorded:
            assert request.key() == recorded, f"{name}: not the key written before ADR 0023"


def test_a_call_that_writes_no_file_has_no_key():
    assert TextRequest(prompt="hello").key() == ""


def test_a_pin_is_part_of_the_key(files):
    plain = ImageRequest(prompt="p", dst=files["dir"] / "a.png", width=8, height=8)
    pinned = ImageRequest(prompt="p", dst=files["dir"] / "a.png", width=8, height=8,
                          pin=Pin(provider="fal", model="m"))  # fmt: skip
    assert plain.key() != pinned.key()
