"""What the kit tests share: a stand-in paid model, and a character and stream to hand it."""

from __future__ import annotations

import pytest
from PIL import Image

from kalainova import kits, media, streams
from kalainova.providers import base


class Stub(base.Provider):
    """Records what it was sent. Stands in for a paid model that takes references."""

    name = "stub"
    capabilities = ("voice", "image", "video", "music", "sfx")
    env_key = None
    free = True
    calls: list[dict] = []
    support = {"image": {"max_images": 4, "max_characters": 2}, "video": {"max_images": 3}}

    def reference_support(self, capability, model):
        return self.support.get(capability, {})

    def _note(self, capability, dst, prompt, kw):
        Stub.calls.append({"capability": capability, "prompt": prompt, **kw})
        dst.write_bytes(b"x")
        return base.Result(path=dst, model=kw.get("model") or f"stub-{capability}")

    def voice(self, text, dst, *, voice=None, **kw):
        return self._note("voice", dst, text, {"voice": voice, **kw})

    def image(self, prompt, dst, *, width, height, **kw):
        Stub.calls.append({"capability": "image", "prompt": prompt, **kw})
        Image.linear_gradient("L").resize((width, height)).convert("RGB").save(dst, format="PNG")
        return base.Result(path=dst, model=kw.get("model") or "stub-plain")

    def video(self, prompt, dst, *, duration, aspect, image=None, **kw):
        Stub.calls.append({"capability": "video", "prompt": prompt, "image": image, **kw})
        media.run(
            [
                "-f",
                "lavfi",
                "-i",
                f"testsrc2=s=320x180:d={duration + 0.5:.2f}:r=24",
                "-pix_fmt",
                "yuv420p",
                str(dst),
            ]
        )
        return base.Result(path=dst, model=kw.get("model") or "stub-video")

    def music(self, prompt, dst, *, duration, **kw):
        return self._note("music", dst, prompt, kw)

    def sfx(self, prompt, dst, *, duration=1.0, **kw):
        return self._note("sfx", dst, prompt, kw)


base.register(Stub)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    monkeypatch.delenv("KALAINOVA_STORE_URI", raising=False)
    monkeypatch.delenv("KALAINOVA_STORE", raising=False)
    (tmp_path / "jobs").mkdir()
    (tmp_path / "streams").mkdir()
    Stub.calls = []
    return tmp_path


def picture(root, name, color=(10, 20, 30)):
    path = root / name
    Image.new("RGB", (32, 32), color).save(path, format="PNG")
    return path


CHARACTER = {
    "origin": {"invented": True, "real_person": False, "attested_by": "operator"},
    "person": {"fictional": True, "adult": True, "age": 31},
    "voice": {"provider": "stub", "voice_id": "voice-a", "model": "voice-model"},
    "persona": {"traits": ["dry"], "never_say": ["buy now"]},
}


def make_character(root, kit_id="lead", voice_id="voice-a", color=(10, 20, 30)):
    kits.new(root, kit_id)
    kits.merge(root, kit_id, {**CHARACTER, "voice": {**CHARACTER["voice"], "voice_id": voice_id}})
    kits.merge(root, kit_id, {"identity": {"description": "short dark hair"}})
    kits.add_file(
        root, kit_id, "identity", picture(root, f"{kit_id}-front.png", color), label="front"
    )
    kits.add_file(
        root, kit_id, "identity", picture(root, f"{kit_id}-side.png", (9, 9, 9)), label="side"
    )
    kits.add_file(root, kit_id, "looks.office", picture(root, f"{kit_id}-look.png", (7, 7, 7)))
    return kits.freeze(root, kit_id, by="operator")


def make_stream(root, stream_id="chan", *, roles=None, **over):
    data = {
        "schema_version": "0.1",
        "stream_id": stream_id,
        "strategy": "generated",
        "distribution_identity": f"{stream_id}-id",
        "rights": "owned",
        "media": ["video", "audio"],
        "max_per_day": 1,
        "cost_cap_per_job": 5,
        "kits": roles or {"lead": "lead@1"},
        "generators": {
            "image": {"provider": "stub", "model": "img-ref"},
            "video": {"provider": "stub", "model": "vid-ref"},
        },
        "accounts": {"youtube": "handle"},
        **over,
    }
    streams.create(root, data)
    return data


def packet(job_id, **beat):
    return {
        "schema_version": "0.1",
        "job_id": job_id,
        "hooks": ["one", "two", "three"],
        "chosen_hook": 0,
        "beats": [{"id": "b1", "role": "hook", "text": "line", "cast": ["lead"], **beat}],
    }
