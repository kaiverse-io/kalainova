"""fal.ai: an aggregator for image, video, song, and lip sync models, through its queue API.

Model ids and unit prices live in config/studio.yaml. A failure after the model has finished is
billed, because the vendor has already charged for it.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import time
from pathlib import Path
from typing import Any

import requests

from .. import media
from ..config import audio_spec, model_for, price_for, reference_spec, video_spec
from .base import BilledError, Provider, Result, register

TIMEOUT = 120
INLINE_MOST_BYTES = 64 * 1024  # fal advises against data URIs past a few KB; larger files upload
FAL_UPLOAD = "https://rest.alpha.fal.ai/storage/upload/initiate"  # VERIFY against fal's docs
ASPECTS = ("9:16", "4:5", "1:1", "16:9", "3:4", "4:3")
Fields = dict[str, Any]
Ref = dict[str, Any]


def _download(url: str, dst: Path) -> Path:
    with requests.get(url, stream=True, timeout=TIMEOUT) as r:
        r.raise_for_status()
        with open(dst, "wb") as fh:
            for chunk in r.iter_content(1 << 16):
                fh.write(chunk)
    return dst


def aspect_for(width: int, height: int) -> str:
    r = width / height
    return min(ASPECTS, key=lambda a: abs(r - int(a.split(":")[0]) / int(a.split(":")[1])))


def _billed_length(spec: Fields, duration: float) -> tuple[int, int | str]:
    """Seconds the vendor bills for this ask, and the length as this model wants it written."""
    allowed = [int(x) for x in str(spec.get("durations") or "5,10").split(",")]
    billed = min((d for d in allowed if d >= duration), default=max(allowed))
    return billed, billed if spec.get("duration_type") == "int" else str(billed)


def _seed_of(data: Fields, seed: int | None) -> Fields:
    used = data.get("seed", seed)
    return {"seed": used} if used is not None else {}


def _audio_url(data: Fields) -> str:
    """Where a music model put its file. The field's name differs between models."""
    found = data.get("audio") or data.get("audio_file") or {}
    return str(found.get("url") or "")  # no URL fails at the fetch, where it is billed


@register
class Fal(Provider):
    """Aggregator for image and video models via the fal queue API."""

    name = "fal"
    capabilities = ("image", "video", "music", "song", "transcribe", "lipsync", "separate")
    env_key = "FAL_KEY"

    def price_key(self, capability: str, request: Fields) -> str:
        if capability == "video" and request.get("references"):
            return "reference_to_video"
        return "image_to_video" if capability == "video" and request.get("image") else capability

    def estimate(self, capability: str, **request: Any) -> float | None:
        """A clip is billed at the length the model allows, which is never shorter than the ask."""
        if capability == "video" and request.get("duration"):
            key = self.price_key(capability, request)
            spec = video_spec("fal", request.get("model") or model_for("fal", key))
            if spec:
                request = {
                    **request,
                    "duration": float(_billed_length(spec, request["duration"])[0]),
                }
        if capability in ("song", "separate") and not request.get("model"):
            request = {**request, "model": model_for("fal", capability)}
        return super().estimate(capability, **request)

    def reference_support(self, capability: str, model: str) -> Fields:
        return reference_spec("fal", capability, model)

    def _with_references(
        self, capability: str, model: str, prompt: str, refs: list[Ref]
    ) -> tuple[str, Fields, Fields]:
        """Prompt naming each reference, payload fields, the model's spec. Refuses unknown ones."""
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

    def _as_elements(
        self, spec: Fields, prompt: str, refs: list[Ref]
    ) -> tuple[str, Fields, Fields]:
        """Kling-style: each character is one element, with a front image and other angles."""
        groups: dict[str, list[Ref]] = {}
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

    def _run(self, model: str, payload: Fields, timeout: float = 900) -> Fields:
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
            if resp.json().get("status") == "COMPLETED":
                out = requests.get(response_url, headers=h, timeout=TIMEOUT)
                out.raise_for_status()  # a failed job surfaces as an error on this fetch
                result: Fields = out.json()
                return result
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
        return str(spot["file_url"])

    @staticmethod
    def _fetch(url: str, dst: Path, billed: float) -> None:
        """Bring a finished file down. The vendor has charged already, so a failure is billed."""
        try:
            _download(url, dst)
        except OSError as exc:
            raise BilledError(billed, f"fal finished but the file did not arrive: {exc}") from exc

    def _fetch_audio(self, url: str, dst: Path, billed: float) -> None:
        """Bring a finished track down as a 48 kHz stereo file."""
        raw = dst.with_suffix(".src")
        self._fetch(url, raw, billed)
        media.run(["-i", str(raw), "-ar", "48000", "-ac", "2", str(dst)])
        raw.unlink(missing_ok=True)

    def image(self, prompt: str, dst: Path, *, width: int, height: int, **kw: Any) -> Result:
        model = kw.get("model") or model_for("fal", "image")
        payload: Fields = {"prompt": prompt, "num_images": 1, "output_format": "png"}
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
        return Result(path=dst, cost=cost, model=model, meta=_seed_of(data, kw.get("seed")))

    def video(
        self,
        prompt: str,
        dst: Path,
        *,
        duration: float,
        aspect: str,
        image: Path | None = None,
        **kw: Any,
    ) -> Result:
        refs = kw.get("references")
        seed = kw.get("seed")
        key = "reference_to_video" if refs else "image_to_video" if image else "video"
        model = kw.get("model") or model_for("fal", key)
        fields: Fields = {}
        text = prompt
        if refs:  # a clip conditioned on the locked references, with the model's own audio left off
            text, fields, spec = self._with_references("video", model, prompt, refs)
        else:
            spec = video_spec("fal", model)
        billed, length = _billed_length(spec, duration)
        payload = {"prompt": text, "aspect_ratio": aspect, "duration": length, **fields}
        payload.update(spec.get("extra", {}))
        if image and not refs:
            payload[spec.get("image_param", "image_url")] = self._upload(image)
        if seed is not None:
            payload["seed"] = seed
        data = self._run(model, payload, timeout=1800)
        cost = billed * price_for("fal", key, model).get("per_sec", 0)
        self._fetch(data["video"]["url"], dst, cost)
        meta = {"billed_sec": billed, **_seed_of(data, seed)}
        return Result(path=dst, cost=cost, model=model, meta=meta)

    def lipsync(self, video: Path, audio: Path, dst: Path, **kw: Any) -> Result:
        """The clip with its mouth matched to the line. The shorter of the two sets the length."""
        model = kw.get("model") or model_for("fal", "lipsync")
        payload = {
            "video_url": self._upload(video),
            "audio_url": self._upload(audio),
            "sync_mode": "cut_off",
        }
        data = self._run(model, payload, timeout=1800)
        cost = media.duration(video) / 60 * price_for("fal", "lipsync").get("per_min", 0)
        self._fetch(data["video"]["url"], dst, cost)
        return Result(path=dst, cost=cost, model=model)

    def song(
        self, lyrics: str, dst: Path, *, style: str = "", duration: float | None = None, **kw: Any
    ) -> Result:
        model = kw.get("model") or model_for("fal", "song")
        spec = audio_spec("fal", model)
        payload: Fields = {spec.get("style_field", "prompt"): style, "lyrics": lyrics}
        if kw.get("instrumental") and spec.get("instrumental_lyrics"):
            payload["lyrics"] = spec["instrumental_lyrics"]
        if duration:
            payload["duration"] = int(duration)
        data = self._run(model, payload, timeout=900)
        row = price_for("fal", "song", model)
        cost = row.get("per_track", 0) + (duration or 0) * row.get("per_sec", 0)
        self._fetch_audio(_audio_url(data), dst, cost)
        return Result(path=dst, cost=cost, model=model, meta=_seed_of(data, kw.get("seed")))

    def separate(self, src: Path, vocals: Path, rest: Path, **kw: Any) -> Result:
        """Vocals, and everything else mixed back together from the model's other stems."""
        model = kw.get("model") or model_for("fal", "separate")
        payload: Fields = {
            "audio_url": self._upload(src),
            "model": "htdemucs",  # four stems; the six-stem model splits the rest further
            "output_format": "wav",
        }
        data = self._run(model, payload, timeout=1800)
        cost = media.duration(src) * price_for("fal", "separate", model).get("per_sec", 0)
        names = [n for n in ("drums", "bass", "other") if (data.get(n) or {}).get("url")]
        if not (data.get("vocals") or {}).get("url") or not names:
            raise BilledError(cost, "fal finished but returned no stems")
        self._fetch(data["vocals"]["url"], vocals, cost)
        parts = []
        for name in names:
            part = rest.with_name(f"{rest.stem}.{name}.wav")
            self._fetch(data[name]["url"], part, cost)
            parts.append(part)
        args = [arg for part in parts for arg in ("-i", str(part))]
        mix = f"amix=inputs={len(parts)}:normalize=0"
        media.run([*args, "-filter_complex", mix, "-ar", "48000", "-ac", "2", str(rest)])
        for part in parts:
            part.unlink(missing_ok=True)
        return Result(path=vocals, cost=cost, model=model)

    def music(self, prompt: str, dst: Path, *, duration: float, **kw: Any) -> Result:
        model = kw.get("model") or model_for("fal", "music")
        data = self._run(model, {"prompt": prompt})
        cost = price_for("fal", "music").get("per_track", 0)
        self._fetch_audio(_audio_url(data), dst, cost)
        return Result(path=dst, cost=cost, model=model)

    def transcribe(self, src: Path, **kw: Any) -> Result:
        model = kw.get("model") or model_for("fal", "transcribe")
        data = self._run(model, {"audio_url": self._upload(src), "chunk_level": "word"})
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
        minutes = media.duration(src) / 60
        return Result(
            words=words,
            text=data.get("text", ""),
            model=model,
            cost=price_for("fal", "transcribe").get("per_min", 0) * minutes,
        )
