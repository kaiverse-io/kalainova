"""Remote providers over plain HTTPS (requests). Keys come from the environment.

Model ids and unit prices live in config/studio.yaml so swapping a model is a
config change, not a code change. Prices are estimates used for the cost cap;
the vendor invoice is the truth.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import time
from pathlib import Path

import requests

from ..config import model_for, price_for, reference_spec, video_spec
from .base import BilledError, Provider, Result, register

TIMEOUT = 120
INLINE_MOST_BYTES = 64 * 1024  # fal advises against data URIs past a few KB; larger files upload
FAL_UPLOAD = "https://rest.alpha.fal.ai/storage/upload/initiate"  # VERIFY against fal's docs
LOSSY_AUDIO = "mp3_44100_128"  # what every ElevenLabs plan allows
SONG_MOST_CHUNKS = 30
SONG_LEAST_CHUNK_MS = 3000


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

    def llm(
        self,
        prompt: str,
        *,
        system: str = "",
        max_tokens: int = 4000,
        images: list[Path] | None = None,
        **kw,
    ) -> Result:
        model = kw.get("model") or model_for("anthropic", "llm")
        content: list[dict] = []
        for img in images or []:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg"
                        if img.suffix in (".jpg", ".jpeg")
                        else "image/png",
                        "data": base64.b64encode(img.read_bytes()).decode(),
                    },
                }
            )
        content.append({"type": "text", "text": prompt})
        body = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        if system:
            body["system"] = system
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": os.environ[self.env_key],
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=body,
            timeout=600,
        )
        r.raise_for_status()
        data = r.json()
        text = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )
        u = data.get("usage", {})
        p = price_for("anthropic", "llm")
        cost = u.get("input_tokens", 0) / 1e6 * p.get("input_per_mtok", 0) + u.get(
            "output_tokens", 0
        ) / 1e6 * p.get("output_per_mtok", 0)
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

    def _post(
        self, path: str, body: dict, *, timeout: float = TIMEOUT
    ) -> tuple[requests.Response, str]:
        """Ask for the configured audio format, and fall back if this plan does not include it.

        A premium master built on 128 kbps MP3 stems is lossless in name only, so the format used is
        kept with the asset for QA to read.
        """
        wanted = model_for("elevenlabs", "output_format") or LOSSY_AUDIO
        r = requests.post(
            f"{self.base}/{path}?output_format={wanted}",
            headers=self._h(),
            json=body,
            timeout=timeout,
        )
        if wanted != LOSSY_AUDIO and r.status_code in (400, 403, 422) and "output_format" in r.text:
            wanted = LOSSY_AUDIO
            r = requests.post(
                f"{self.base}/{path}?output_format={wanted}",
                headers=self._h(),
                json=body,
                timeout=timeout,
            )
        r.raise_for_status()
        return r, wanted

    @staticmethod
    def _audio_to_wav(blob: bytes, dst: Path, fmt: str, channels: int) -> None:
        from .. import media

        source = dst.with_suffix(".src")
        source.write_bytes(blob)
        raw = (
            ["-f", "s16le", "-ar", fmt.split("_")[1], "-ac", "1"] if fmt.startswith("pcm_") else []
        )
        media.run([*raw, "-i", str(source), "-ar", "48000", "-ac", str(channels), str(dst)])
        source.unlink(missing_ok=True)

    def voice(self, text: str, dst: Path, *, voice: str | None = None, **kw) -> Result:
        model = kw.get("model") or model_for("elevenlabs", "voice")
        voice_id = (
            voice or os.environ.get("ELEVENLABS_VOICE_ID") or model_for("elevenlabs", "voice_id")
        )
        r, fmt = self._post(
            f"text-to-speech/{voice_id}/with-timestamps",
            {
                "text": text,
                "model_id": model,
                "voice_settings": kw.get("settings")
                or {
                    "stability": 0.45,
                    "similarity_boost": 0.8,
                    "style": 0.35,
                    "use_speaker_boost": True,
                },
                **{k: kw[k] for k in ("previous_text", "next_text") if kw.get(k)},
            },
        )
        data = r.json()
        self._audio_to_wav(base64.b64decode(data["audio_base64"]), dst, fmt, 1)
        words = chars_to_words(data.get("alignment") or data.get("normalized_alignment") or {})
        cost = len(text) / 1000 * price_for("elevenlabs", "voice").get("per_kchar", 0)
        return Result(
            path=dst,
            cost=cost,
            model=model,
            words=words,
            meta={"voice_id": voice_id, "audio_format": fmt},
        )

    def music(self, prompt: str, dst: Path, *, duration: float, **kw) -> Result:
        r, fmt = self._post(
            "music",
            {
                "prompt": prompt,
                "music_length_ms": int(max(duration, 10.0) * 1000),  # API minimum is 10 s
                "model_id": model_for("elevenlabs", "music"),
            },
            timeout=600,
        )
        return self._to_wav(r.content, dst, duration, "music", fmt)

    def song(
        self,
        lyrics: str,
        dst: Path,
        *,
        style: str = "",
        duration: float | None = None,
        **kw,
    ) -> Result:
        """A song from a composition plan: one chunk per section, each with its own lines and styles."""
        seconds = float(duration or 120)
        plan = song_chunks(kw.get("sections") or [], style, seconds, kw.get("avoid") or "")
        body: dict = {
            "model_id": model_for("elevenlabs", "song") or model_for("elevenlabs", "music")
        }
        body.update(
            {"composition_plan": {"chunks": plan}} if plan else {"prompt": f"{style}\n{lyrics}"}
        )
        r, fmt = self._post("music", body, timeout=900)
        return self._to_wav(r.content, dst, seconds, "song", fmt)

    def sfx(self, prompt: str, dst: Path, *, duration: float = 1.0, **kw) -> Result:
        r, fmt = self._post(
            "sound-generation",
            {
                "text": prompt,
                "duration_seconds": max(0.5, min(duration, 22)),
                "prompt_influence": 0.5,
                "model_id": model_for("elevenlabs", "sfx"),
            },
        )
        return self._to_wav(r.content, dst, duration, "sfx", fmt)

    def _to_wav(self, blob: bytes, dst: Path, duration: float, cap: str, fmt: str) -> Result:
        self._audio_to_wav(blob, dst, fmt, 2)
        cost = duration / 60 * price_for("elevenlabs", cap).get("per_min", 0)
        return Result(
            path=dst, cost=cost, model=model_for("elevenlabs", cap), meta={"audio_format": fmt}
        )


def song_chunks(sections: list[dict], style: str, seconds: float, avoid: str = "") -> list[dict]:
    """A composition plan: each section's time in proportion to its lines, inside the API's limits."""
    parts = sections[:SONG_MOST_CHUNKS]
    if not parts:
        return []
    weights = [max(len(s.get("lines") or []), 2) for s in parts]
    total_ms = int(seconds * 1000)
    chunks = []
    for part, weight in zip(parts, weights):
        lines = part.get("lines") or []
        tag = f"[{str(part.get('kind', 'verse')).title()}]"
        styles = [s for s in (style, part.get("style")) if s]
        chunks.append(
            {
                "text": "\n".join([tag, *lines]),
                "duration_ms": max(SONG_LEAST_CHUNK_MS, total_ms * weight // sum(weights)),
                "positive_styles": styles,
                "negative_styles": [avoid] if avoid else [],
                "context_adherence": "high",
            }
        )
    return chunks


def aspect_for(width: int, height: int) -> str:
    r = width / height
    return min(
        ("9:16", "4:5", "1:1", "16:9", "3:4", "4:3"),
        key=lambda a: abs(r - int(a.split(":")[0]) / int(a.split(":")[1])),
    )


def chars_to_words(al: dict) -> list[dict]:
    chars = al.get("characters") or []
    starts = al.get("character_start_times_seconds") or []
    ends = al.get("character_end_times_seconds") or []
    words, cur, t0, t1 = [], "", None, None
    for c, s, e in zip(chars, starts, ends):
        if c.isspace():
            if cur:
                words.append(
                    {
                        "start_sec": round(t0, 3),
                        "end_sec": round(t1, 3),
                        "text": cur,
                        "confidence": 0.98,
                    }
                )
            cur, t0 = "", None
            continue
        if t0 is None:
            t0 = s
        cur += c
        t1 = e
    if cur:
        words.append(
            {"start_sec": round(t0, 3), "end_sec": round(t1, 3), "text": cur, "confidence": 0.98}
        )
    return words


# ---------------------------------------------------------------- fal.ai
@register
class Fal(Provider):
    """Aggregator for image and video models via the fal queue API."""

    name = "fal"
    capabilities = ("image", "video", "music", "song", "transcribe", "lipsync")
    env_key = "FAL_KEY"

    def price_key(self, capability: str, request: dict) -> str:
        if capability == "video" and request.get("references"):
            return "reference_to_video"
        return "image_to_video" if capability == "video" and request.get("image") else capability

    def reference_support(self, capability: str, model: str) -> dict:
        return reference_spec("fal", capability, model)

    def _with_references(
        self, capability: str, model: str, prompt: str, refs: list[dict]
    ) -> tuple[str, dict, dict]:
        """(prompt naming each reference, payload fields, the model's spec). Refuses an unknown model."""
        spec = reference_spec("fal", capability, model)
        if not spec:
            raise ValueError(f"{model} is not listed under reference_models for {capability}")
        if spec.get("elements"):
            return self._as_elements(spec, prompt, refs)
        guide = [
            f"{spec['tag'].format(n=i)} is {ref['label']}" for i, ref in enumerate(refs, start=1)
        ]
        urls = [self._upload(ref["path"]) for ref in refs]
        return f"{prompt}. References: {'; '.join(guide)}.", {spec["images_param"]: urls}, spec

    def _as_elements(self, spec: dict, prompt: str, refs: list[dict]) -> tuple[str, dict, dict]:
        """Kling-style: each character is one element, with a front image and other angles."""
        groups: dict[str, list[dict]] = {}
        loose = []
        for ref in refs:
            if ref.get("group"):
                groups.setdefault(ref["group"], []).append(ref)
            else:
                loose.append(ref)
        elements = [
            {
                "frontal_image_url": self._upload(group[0]["path"]),
                "reference_image_urls": [self._upload(r["path"]) for r in group[1:]],
            }
            for group in groups.values()
        ]
        guide = [f"@Element{i} is {name}" for i, name in enumerate(groups, start=1)]
        guide += [f"@Image{i} is {r['label']}" for i, r in enumerate(loose, start=1)]
        payload = {"elements": elements, "image_urls": [self._upload(r["path"]) for r in loose]}
        return f"{prompt}. References: {'; '.join(guide)}.", payload, spec

    def _run(self, model: str, payload: dict, timeout: float = 900) -> dict:
        h = {"Authorization": f"Key {os.environ[self.env_key]}", "content-type": "application/json"}
        r = requests.post(
            f"https://queue.fal.run/{model}", headers=h, json=payload, timeout=TIMEOUT
        )
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
        cancel = sub.get("cancel_url")
        if cancel:  # stop paying for a request nobody is waiting on
            requests.put(cancel, headers=h, timeout=TIMEOUT)
        raise TimeoutError(f"fal {model} timed out")

    def _upload(self, path: Path) -> str:
        """A URL for an input file. Small files travel inline; the rest go through fal's storage."""
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.stat().st_size <= INLINE_MOST_BYTES:
            return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
        init = requests.post(
            FAL_UPLOAD,
            headers={"Authorization": f"Key {os.environ[self.env_key]}"},
            json={"content_type": mime, "file_name": path.name},
            timeout=TIMEOUT,
        )
        init.raise_for_status()
        spot = init.json()
        put = requests.put(
            spot["upload_url"], headers={"Content-Type": mime}, data=path.read_bytes(), timeout=600
        )
        put.raise_for_status()
        return spot["file_url"]

    @staticmethod
    def _fetch(url: str, dst: Path, billed: float) -> None:
        """Bring a finished file down. The vendor has already charged, so a failure here is billed."""
        try:
            _download(url, dst)
        except OSError as exc:
            raise BilledError(billed, f"fal finished but the file did not arrive: {exc}") from exc

    def image(self, prompt: str, dst: Path, *, width: int, height: int, **kw) -> Result:
        model = kw.get("model") or model_for("fal", "image")
        payload = {"prompt": prompt, "num_images": 1, "output_format": "png"}
        if kw.get("size_mode") == "pixels":
            payload["image_size"] = {"width": width, "height": height}
        else:  # Nano Banana-family models take an aspect ratio, not pixel sizes
            payload["aspect_ratio"] = aspect_for(width, height)
            if model_for("fal", "image_resolution"):
                payload["resolution"] = model_for("fal", "image_resolution")
        refs = kw.get("references")
        if refs:
            payload["prompt"], fields, spec = self._with_references("image", model, prompt, refs)
            payload.update(fields, **spec.get("extra", {}))
        if kw.get("seed") is not None:
            payload["seed"] = kw["seed"]
        data = self._run(model, payload)
        cost = price_for("fal", "image").get("per_image", 0)
        self._fetch(data["images"][0]["url"], dst, cost)
        return Result(path=dst, cost=cost, model=model, meta=self._seed_of(data, kw))

    @staticmethod
    def _seed_of(data: dict, kw: dict) -> dict:
        seed = data.get("seed", kw.get("seed"))
        return {"seed": seed} if seed is not None else {}

    def video(
        self,
        prompt: str,
        dst: Path,
        *,
        duration: float,
        aspect: str,
        image: Path | None = None,
        **kw,
    ) -> Result:
        refs = kw.get("references")
        if refs:
            return self._reference_video(
                prompt, dst, duration, aspect, kw.get("model"), refs, seed=kw.get("seed")
            )
        key = "image_to_video" if image else "video"
        model = kw.get("model") or model_for("fal", key)
        spec = video_spec("fal", model)
        allowed = [int(x) for x in str(spec.get("durations") or "5,10").split(",")]
        billed = min((d for d in allowed if d >= duration), default=max(allowed))
        length = billed if spec.get("duration_type") == "int" else str(billed)
        payload = {"prompt": prompt, "aspect_ratio": aspect, "duration": length}
        payload.update(spec.get("extra", {}))
        if image:
            payload[spec.get("image_param", "image_url")] = self._upload(image)
        if kw.get("seed") is not None:
            payload["seed"] = kw["seed"]
        data = self._run(model, payload, timeout=1800)
        cost = billed * price_for("fal", key).get("per_sec", 0)
        self._fetch(data["video"]["url"], dst, cost)
        return Result(
            path=dst, cost=cost, model=model, meta={"billed_sec": billed, **self._seed_of(data, kw)}
        )

    def _reference_video(
        self,
        prompt: str,
        dst: Path,
        duration: float,
        aspect: str,
        model: str | None,
        refs: list[dict],
        seed: int | None = None,
    ) -> Result:
        """A clip conditioned on the locked references, with the model's own audio left off."""
        model = model or model_for("fal", "reference_to_video")
        text, fields, spec = self._with_references("video", model, prompt, refs)
        allowed = [int(x) for x in str(spec.get("durations") or "5,10").split(",")]
        billed = min((d for d in allowed if d >= duration), default=max(allowed))
        length = billed if spec.get("duration_type") == "int" else str(billed)
        payload = {"prompt": text, "aspect_ratio": aspect, "duration": length, **fields}
        payload.update(spec.get("extra", {}))
        if seed is not None:
            payload["seed"] = seed
        data = self._run(model, payload, timeout=1800)
        cost = billed * price_for("fal", "reference_to_video").get("per_sec", 0)
        self._fetch(data["video"]["url"], dst, cost)
        return Result(
            path=dst,
            cost=cost,
            model=model,
            meta={"billed_sec": billed, **self._seed_of(data, {"seed": seed})},
        )

    def lipsync(self, video: Path, audio: Path, dst: Path, **kw) -> Result:
        """The clip with its mouth matched to the line. The shorter of the two sets the length."""
        model = kw.get("model") or model_for("fal", "lipsync")
        payload = {
            "video_url": self._upload(video),
            "audio_url": self._upload(audio),
            "sync_mode": "cut_off",
        }
        data = self._run(model, payload, timeout=1800)
        from .. import media

        cost = media.duration(video) / 60 * price_for("fal", "lipsync").get("per_min", 0)
        self._fetch(data["video"]["url"], dst, cost)
        return Result(path=dst, cost=cost, model=model)

    def song(
        self,
        lyrics: str,
        dst: Path,
        *,
        style: str = "",
        duration: float | None = None,
        **kw,
    ) -> Result:
        model = kw.get("model") or model_for("fal", "song")
        payload = {"prompt": style, "lyrics": lyrics}
        if duration:
            payload["duration"] = int(duration)
        data = self._run(model, payload, timeout=900)
        url = (data.get("audio") or data.get("audio_file") or {}).get("url")
        cost = price_for("fal", "song").get("per_track", 0)
        raw = dst.with_suffix(".src")
        self._fetch(url, raw, cost)
        from .. import media

        media.run(["-i", str(raw), "-ar", "48000", "-ac", "2", str(dst)])
        raw.unlink(missing_ok=True)
        return Result(path=dst, cost=cost, model=model, meta=self._seed_of(data, kw))

    def music(self, prompt: str, dst: Path, *, duration: float, **kw) -> Result:
        model = kw.get("model") or model_for("fal", "music")
        data = self._run(model, {"prompt": prompt})
        url = (data.get("audio_file") or data.get("audio") or {}).get("url")
        raw = dst.with_suffix(".src")
        cost = price_for("fal", "music").get("per_track", 0)
        self._fetch(url, raw, cost)
        from .. import media

        media.run(["-i", str(raw), "-ar", "48000", "-ac", "2", str(dst)])
        raw.unlink(missing_ok=True)
        return Result(path=dst, cost=cost, model=model)

    def transcribe(self, src: Path, **kw) -> Result:
        model = kw.get("model") or model_for("fal", "transcribe")
        data = self._run(
            model,
            {
                "audio_url": self._upload(src),
                "chunk_level": "word",
            },
        )
        words = [
            {
                "start_sec": c["timestamp"][0],
                "end_sec": c["timestamp"][1],
                "text": c["text"].strip(),
                "confidence": 0.9,
            }
            for c in data.get("chunks", [])
            if c.get("timestamp")
        ]
        from .. import media

        minutes = media.duration(src) / 60
        return Result(
            words=words,
            text=data.get("text", ""),
            model=model,
            cost=price_for("fal", "transcribe").get("per_min", 0) * minutes,
        )
