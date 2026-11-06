"""Remote providers over plain HTTPS (requests). Keys come from the environment.

Model ids and unit prices live in config/studio.yaml so swapping a model is a
config change, not a code change. Prices are estimates used for the cost cap;
the vendor invoice is the truth.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path

import requests

from ..config import model_for, price_for
from .base import Provider, Result, register

TIMEOUT = 120


def _download(url: str, dst: Path) -> Path:
    with requests.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        with open(dst, "wb") as fh:
            for chunk in r.iter_content(1 << 16):
                fh.write(chunk)
    return dst


# ---------------------------------------------------------------- Anthropic
@register
class Anthropic(Provider):
    """Planner, editor and QA judge. Text and vision."""

    name = "anthropic"
    capabilities = ("llm",)
    env_key = "ANTHROPIC_API_KEY"
    synthetic = False

    def llm(self, prompt: str, *, system: str = "", max_tokens: int = 4000, images: list[Path] | None = None, **kw) -> Result:
        model = kw.get("model") or model_for("anthropic", "llm")
        content: list[dict] = []
        for img in images or []:
            content.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/jpeg" if img.suffix in (".jpg", ".jpeg") else "image/png",
                           "data": base64.b64encode(img.read_bytes()).decode()},
            })
        content.append({"type": "text", "text": prompt})
        body = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": content}]}
        if system:
            body["system"] = system
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": os.environ[self.env_key], "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=body,
            timeout=600,
        )
        r.raise_for_status()
        data = r.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        u = data.get("usage", {})
        p = price_for("anthropic", "llm")
        cost = u.get("input_tokens", 0) / 1e6 * p.get("input_per_mtok", 0) + u.get("output_tokens", 0) / 1e6 * p.get("output_per_mtok", 0)
        return Result(text=text, cost=cost, model=model, meta={"usage": u})


# ---------------------------------------------------------------- ElevenLabs
@register
class ElevenLabs(Provider):
    """Voice with character-level timestamps, plus music and sound effects."""

    name = "elevenlabs"
    capabilities = ("voice", "music", "sfx")
    env_key = "ELEVENLABS_API_KEY"
    base = "https://api.elevenlabs.io/v1"

    def _h(self) -> dict:
        return {"xi-api-key": os.environ[self.env_key], "content-type": "application/json"}

    def voice(self, text: str, dst: Path, *, voice: str | None = None, **kw) -> Result:
        model = kw.get("model") or model_for("elevenlabs", "voice")
        voice_id = voice or os.environ.get("ELEVENLABS_VOICE_ID") or model_for("elevenlabs", "voice_id")
        r = requests.post(
            f"{self.base}/text-to-speech/{voice_id}/with-timestamps?output_format=mp3_44100_128",
            headers=self._h(),
            json={"text": text, "model_id": model,
                  "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.35, "use_speaker_boost": True}},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        mp3 = dst.with_suffix(".mp3")
        mp3.write_bytes(base64.b64decode(data["audio_base64"]))
        from .. import media
        media.run(["-i", str(mp3), "-ar", "48000", "-ac", "1", str(dst)])
        mp3.unlink(missing_ok=True)
        words = chars_to_words(data.get("alignment") or data.get("normalized_alignment") or {})
        cost = len(text) / 1000 * price_for("elevenlabs", "voice").get("per_kchar", 0)
        return Result(path=dst, cost=cost, model=model, words=words, meta={"voice_id": voice_id})

    def music(self, prompt: str, dst: Path, *, duration: float, **kw) -> Result:
        r = requests.post(
            f"{self.base}/music?output_format=mp3_44100_128",
            headers=self._h(),
            json={"prompt": prompt, "music_length_ms": int(max(duration, 10.0) * 1000),  # API minimum is 10 s
                  "model_id": model_for("elevenlabs", "music")},
            timeout=600,
        )
        r.raise_for_status()
        return self._to_wav(r.content, dst, duration, "music")

    def sfx(self, prompt: str, dst: Path, *, duration: float = 1.0, **kw) -> Result:
        r = requests.post(
            f"{self.base}/sound-generation?output_format=mp3_44100_128",
            headers=self._h(),
            json={"text": prompt, "duration_seconds": max(0.5, min(duration, 22)), "prompt_influence": 0.5},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        return self._to_wav(r.content, dst, duration, "sfx")

    def _to_wav(self, blob: bytes, dst: Path, duration: float, cap: str) -> Result:
        from .. import media
        mp3 = dst.with_suffix(".mp3")
        mp3.write_bytes(blob)
        media.run(["-i", str(mp3), "-ar", "48000", "-ac", "2", str(dst)])
        mp3.unlink(missing_ok=True)
        cost = duration / 60 * price_for("elevenlabs", cap).get("per_min", 0)
        return Result(path=dst, cost=cost, model=model_for("elevenlabs", cap))


def aspect_for(width: int, height: int) -> str:
    r = width / height
    return min(("9:16", "4:5", "1:1", "16:9", "3:4", "4:3"), key=lambda a: abs(r - int(a.split(":")[0]) / int(a.split(":")[1])))


def chars_to_words(al: dict) -> list[dict]:
    chars = al.get("characters") or []
    starts = al.get("character_start_times_seconds") or []
    ends = al.get("character_end_times_seconds") or []
    words, cur, t0, t1 = [], "", None, None
    for c, s, e in zip(chars, starts, ends):
        if c.isspace():
            if cur:
                words.append({"start_sec": round(t0, 3), "end_sec": round(t1, 3), "text": cur, "confidence": 0.98})
            cur, t0 = "", None
            continue
        if t0 is None:
            t0 = s
        cur += c
        t1 = e
    if cur:
        words.append({"start_sec": round(t0, 3), "end_sec": round(t1, 3), "text": cur, "confidence": 0.98})
    return words


# ---------------------------------------------------------------- fal.ai
@register
class Fal(Provider):
    """Aggregator for image and video models via the fal queue API."""

    name = "fal"
    capabilities = ("image", "video", "music", "transcribe")
    env_key = "FAL_KEY"

    def price_key(self, capability: str, request: dict) -> str:
        return "image_to_video" if capability == "video" and request.get("image") else capability

    def _run(self, model: str, payload: dict, timeout: float = 900) -> dict:
        h = {"Authorization": f"Key {os.environ[self.env_key]}", "content-type": "application/json"}
        r = requests.post(f"https://queue.fal.run/{model}", headers=h, json=payload, timeout=TIMEOUT)
        r.raise_for_status()
        sub = r.json()
        status_url, response_url = sub["status_url"], sub["response_url"]
        deadline = time.time() + timeout
        while time.time() < deadline:
            resp = requests.get(status_url, headers=h, timeout=TIMEOUT)
            resp.raise_for_status()  # a 401/404 must fail now, not after the timeout
            s = resp.json()
            if s.get("status") == "COMPLETED":
                out = requests.get(response_url, headers=h, timeout=TIMEOUT)
                out.raise_for_status()
                return out.json()
            # fal statuses are IN_QUEUE / IN_PROGRESS / COMPLETED; a failed job surfaces as an error on the result fetch
            time.sleep(3)
        raise TimeoutError(f"fal {model} timed out")

    def _upload(self, path: Path) -> str:
        # Inline data URI works for fal inputs up to a few MB; enough for a keyframe still.
        mime = "image/png" if path.suffix == ".png" else "image/jpeg"
        return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()

    def image(self, prompt: str, dst: Path, *, width: int, height: int, **kw) -> Result:
        model = kw.get("model") or model_for("fal", "image")
        payload = {"prompt": prompt, "num_images": 1, "output_format": "png"}
        if kw.get("size_mode") == "pixels":
            payload["image_size"] = {"width": width, "height": height}
        else:  # Nano Banana-family models take an aspect ratio, not pixel sizes
            payload["aspect_ratio"] = aspect_for(width, height)
        data = self._run(model, payload)
        _download(data["images"][0]["url"], dst)
        return Result(path=dst, cost=price_for("fal", "image").get("per_image", 0), model=model)

    def video(self, prompt: str, dst: Path, *, duration: float, aspect: str, image: Path | None = None, **kw) -> Result:
        key = "image_to_video" if image else "video"
        model = kw.get("model") or model_for("fal", key)
        allowed = [int(x) for x in str(model_for("fal", key + "_durations") or "5,10").split(",")]
        billed = min((d for d in allowed if d >= duration), default=max(allowed))
        payload = {"prompt": prompt, "aspect_ratio": aspect, "duration": str(billed)}
        if image:
            payload["image_url"] = self._upload(image)
        data = self._run(model, payload, timeout=1800)
        _download(data["video"]["url"], dst)
        cost = billed * price_for("fal", key).get("per_sec", 0)
        return Result(path=dst, cost=cost, model=model, meta={"billed_sec": billed})

    def music(self, prompt: str, dst: Path, *, duration: float, **kw) -> Result:
        model = kw.get("model") or model_for("fal", "music")
        data = self._run(model, {"prompt": prompt, "seconds_total": int(duration)})
        url = (data.get("audio_file") or data.get("audio") or {}).get("url")
        raw = dst.with_suffix(".src")
        _download(url, raw)
        from .. import media
        media.run(["-i", str(raw), "-ar", "48000", "-ac", "2", str(dst)])
        raw.unlink(missing_ok=True)
        return Result(path=dst, cost=price_for("fal", "music").get("per_track", 0), model=model)

    def transcribe(self, src: Path, **kw) -> Result:
        model = kw.get("model") or model_for("fal", "transcribe")
        data = self._run(model, {"audio_url": "data:audio/wav;base64," + base64.b64encode(src.read_bytes()).decode(),
                                 "chunk_level": "word"})
        words = [{"start_sec": c["timestamp"][0], "end_sec": c["timestamp"][1], "text": c["text"].strip(), "confidence": 0.9}
                 for c in data.get("chunks", []) if c.get("timestamp")]
        from .. import media
        minutes = media.duration(src) / 60
        return Result(words=words, text=data.get("text", ""), model=model,
                      cost=price_for("fal", "transcribe").get("per_min", 0) * minutes)
