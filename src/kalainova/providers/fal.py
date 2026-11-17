"""fal.ai: an aggregator for image, video, song, and lip sync models, through its queue API.

Two parts (ADR 0023). `FalQueue` is the transport: it submits to fal's queue with the router's
labels as X-Fal-Tags, polls, cancels what nobody waits for, uploads inputs, and fills the call's
receipt from fal's request id and X-Fal-Billable-Units at this account's unit price. `Fal` maps the
engine's requests to each model's fields, which config/studio.yaml's model tables name, and maps
fal's replies back. Model ids and unit prices live in config/studio.yaml. A failure after the model
has finished is billed, because the vendor has already charged for it.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import time
from functools import cache
from pathlib import Path
from typing import Any

import requests

from .. import media
from ..config import audio_spec, model_for, price_for, reference_spec, video_spec
from . import rehearsal
from .base import Provider, register
from .contract import (
    Billable,
    BilledError,
    Context,
    ImageRequest,
    LipsyncRequest,
    MotionRequest,
    MusicRequest,
    Reference,
    Result,
    Sent,
    SeparateRequest,
    SongRequest,
    TranscribeRequest,
    VideoRequest,
    Word,
)
from .transport import TIMEOUT, Reply, Transport, raise_for, request_id

QUEUE = "https://queue.fal.run/"
SCHEMA = "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id="  # public, no key
PRICING = (
    "https://api.fal.ai/v1/models/pricing"  # this account's unit prices, read with the same key
)
INLINE_MOST_BYTES = 64 * 1024  # fal advises against data URIs past a few KB; larger files upload
FAL_UPLOAD = "https://rest.alpha.fal.ai/storage/upload/initiate"  # VERIFY against fal's docs
ASPECTS = ("9:16", "4:5", "1:1", "16:9", "3:4", "4:3")
AUDIO_AT = (
    "audio.url",
    "audio_file.url",
    "audio",
)  # where a music model puts its file; models differ
Fields = dict[str, Any]


def aspect_for(width: int, height: int) -> str:
    r = width / height
    return min(ASPECTS, key=lambda a: abs(r - int(a.split(":")[0]) / int(a.split(":")[1])))


def _billed_length(spec: Fields, duration: float) -> tuple[int, int | str]:
    """Seconds the vendor bills for this ask, and the length as this model wants it written."""
    allowed = [int(x) for x in str(spec.get("durations") or "5,10").split(",")]
    billed = min((d for d in allowed if d >= duration), default=max(allowed))
    return billed, billed if spec.get("duration_type") == "int" else str(billed)


def _seed(reply: Reply, given: int | None) -> int | None:
    used = reply.get("seed", given)
    return int(used) if isinstance(used, int | float) else None


def _tags(tags: dict[str, str] | Any) -> str:
    """The labels as fal's X-Fal-Tags header: key=value pairs, at most 10, no commas."""
    clean = []
    for key, value in list(dict(tags).items())[:10]:
        k = "".join(c for c in key if c.isalnum() or c in "._-")[:64]
        v = "".join(c for c in str(value) if c.isprintable() and c.isascii() and c != ",")[:256]
        if k and v:
            clean.append(f"{k}={v}")
    return ",".join(clean)


@cache
def list_price(model: str) -> dict[str, Any] | None:
    """This account's price per billing unit for a model and the unit, from fal's pricing API (read
    once per process). None when it cannot be read: no key, a rehearsal, or no answer."""
    key = os.environ.get("FAL_KEY")
    if not key or rehearsal.active() is not None:
        return None
    try:
        r = requests.get(
            PRICING, params={"endpoint_id": model}, headers={"Authorization": f"Key {key}"},
            timeout=TIMEOUT,
        )  # fmt: skip
        r.raise_for_status()
        rows = [p for p in r.json().get("prices", []) if p.get("endpoint_id") == model]
        return (
            {"unit_price": float(rows[0]["unit_price"]), "unit": rows[0].get("unit")}
            if rows
            else None
        )
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return None


def unit_price(model: str) -> float | None:
    found = list_price(model)
    return found["unit_price"] if found else None


@cache
def input_schema(model: str) -> tuple[frozenset[str], frozenset[str]]:
    """The request fields fal's published schema lists for a model, and the ones it requires. Free:
    fal serves every model's schema with no key. Raises when it cannot be read."""
    r = requests.get(SCHEMA + model, timeout=30)
    r.raise_for_status()
    found: set[str] = set()
    needed: set[str] = set()
    for name, body in r.json()["components"]["schemas"].items():
        if name.endswith("Input") and "properties" in body and "Element" not in name:
            found |= set(body["properties"])
            needed |= set(body.get("required") or [])
    return frozenset(found), frozenset(needed)


def schema_problems(model: str, payload: Fields) -> list[str]:
    """What fal would refuse in a request before it is sent: a field its schema does not list, or
    one it requires that is missing. A schema that cannot be read is a problem too."""
    try:
        have, need = input_schema(model)
    except (requests.RequestException, ValueError, KeyError) as exc:
        return [f"could not read {model}'s schema ({exc})"]
    sent = set(payload)
    found = [f"not in {model}'s schema: {sorted(sent - have)}"] if sent - have else []
    return found + ([f"{model} requires {sorted(need - sent)}"] if need - sent else [])


class FalQueue(Transport):
    """fal's queue: submit, poll until done, fetch the reply. A wait that runs out cancels."""

    platform = "fal"

    @staticmethod
    def _key() -> str:
        return os.environ["FAL_KEY"]

    def _send(
        self, endpoint: str, payload: Fields, ctx: Context, *, wait: float, params: dict[str, str]
    ) -> Reply:
        h = {"Authorization": f"Key {self._key()}", "content-type": "application/json"}
        tagged = {**h, **({"X-Fal-Tags": _tags(ctx.labels)} if ctx.labels else {})}
        r = requests.post(QUEUE + endpoint, headers=tagged, json=payload, timeout=TIMEOUT)
        raise_for(r, self.platform)
        sub = r.json()
        ctx.receipt.request_id = sub.get("request_id")  # what fal's bill and dashboard list
        status_url, response_url = sub["status_url"], sub["response_url"]
        deadline = time.time() + wait
        while time.time() < deadline:
            resp = requests.get(status_url, headers=h, timeout=TIMEOUT)
            raise_for(resp, self.platform)  # a 401/404 must fail now, not after the timeout
            if resp.json().get("status") == "COMPLETED":
                out = requests.get(response_url, headers=h, timeout=TIMEOUT)
                raise_for(out, self.platform)  # a failed job surfaces as an error on this fetch
                self._note_charge(endpoint, getattr(out, "headers", None) or {}, ctx)
                return Reply(data=out.json())
            time.sleep(3)
        cancel = sub.get("cancel_url")
        if cancel:  # stop paying for a request nobody is waiting on
            requests.put(cancel, headers=h, timeout=TIMEOUT)
        raise TimeoutError(f"fal {endpoint} timed out")

    @staticmethod
    def _note_charge(model: str, headers: Any, ctx: Context) -> None:
        """What fal says it billed: the units in X-Fal-Billable-Units, priced at this account's
        unit price from fal's pricing API. Either missing leaves the price table's figure."""
        found = request_id(headers)
        if found and not ctx.receipt.request_id:
            ctx.receipt.request_id = found
        units = headers.get("x-fal-billable-units") or headers.get("X-Fal-Billable-Units")
        if units in (None, ""):
            return
        ctx.receipt.billed_units = float(units)
        price = unit_price(model)
        if price is not None:
            ctx.receipt.vendor_cost = round(
                (ctx.receipt.vendor_cost or 0.0) + ctx.receipt.billed_units * price, 6
            )

    def _upload(self, path: Path) -> str:
        """A URL for an input file. Small files travel inline; the rest go through fal's storage."""
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.stat().st_size <= INLINE_MOST_BYTES:
            return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()
        init = requests.post(
            FAL_UPLOAD,
            headers={"Authorization": f"Key {self._key()}"},
            json={"content_type": mime, "file_name": path.name},
            timeout=TIMEOUT,
        )
        raise_for(init, self.platform)
        spot = init.json()
        put = requests.put(
            spot["upload_url"], headers={"Content-Type": mime}, data=path.read_bytes(), timeout=600
        )
        raise_for(put, self.platform)
        return str(spot["file_url"])

    def problems(self, model: str, payload: Fields) -> list[str]:
        return schema_problems(model, payload)

    def list_price(self, model: str) -> dict[str, Any] | None:
        return list_price(model)


@register
class Fal(Provider):
    """Aggregator for image and video models via the fal queue API."""

    name = "fal"
    capabilities = (
        "image",
        "video",
        "motion",
        "music",
        "song",
        "transcribe",
        "lipsync",
        "separate",
    )
    env_key = "FAL_KEY"
    rehearses = True  # everything goes out through its transport
    transport: Transport = FalQueue()

    def price_key(self, billable: Billable) -> str:
        if billable.capability == "video" and billable.references:
            return "reference_to_video"
        return (
            "image_to_video"
            if billable.capability == "video" and billable.image
            else billable.capability
        )

    def billed_seconds(self, billable: Billable, model: str | None = None) -> float:
        """A clip comes back at the next length the model allows, never shorter than the ask."""
        if billable.capability == "video" and billable.duration:
            name = model or model_for("fal", self.price_key(billable))
            spec = (
                reference_spec("fal", "video", name) if billable.references else {}
            ) or video_spec("fal", name)
            if spec:
                return float(_billed_length(spec, billable.duration)[0])
        return super().billed_seconds(billable, model)

    def estimate(self, billable: Billable, model: str | None = None) -> float | None:
        """A clip is billed at the length the model allows, which is never shorter than the ask."""
        if billable.capability == "video" and billable.duration:
            billable = Billable(
                capability="video",
                duration=self.billed_seconds(billable, model),
                image=billable.image,
                references=billable.references,
            )
        if billable.capability in ("song", "separate") and not model:
            model = model_for("fal", billable.capability)
        return super().estimate(billable, model)

    def _with_references(
        self, capability: str, model: str, prompt: str, refs: tuple[Reference, ...]
    ) -> tuple[str, Fields, Fields]:
        """Prompt naming each reference, payload fields, the model's spec. Refuses unknown ones."""
        spec = reference_spec("fal", capability, model)
        if not spec:
            raise ValueError(f"{model} is not listed under reference_models for {capability}")
        if spec.get("elements"):
            return self._as_elements(spec, prompt, refs)
        guide = [f"{spec['tag'].format(n=i)} is {ref.label}" for i, ref in enumerate(refs, start=1)]
        urls = [self.transport.upload(ref.path) for ref in refs]
        return f"{prompt}. References: {'; '.join(guide)}.", {spec["images_param"]: urls}, spec

    def _as_elements(
        self, spec: Fields, prompt: str, refs: tuple[Reference, ...]
    ) -> tuple[str, Fields, Fields]:
        """Kling-style: each character is one element, with a front image and other angles.

        An element needs its front and one to three more angles (fal refuses an empty list with a
        422), so a character with a single picture goes in as a plain reference image instead.
        """
        groups: dict[str, list[Reference]] = {}
        images: list[tuple[str, Reference]] = []
        for ref in refs:
            if ref.group:
                groups.setdefault(ref.group, []).append(ref)
            else:
                images.append((ref.label, ref))
        images = [(name, g[0]) for name, g in groups.items() if len(g) == 1] + images
        groups = {name: g for name, g in groups.items() if len(g) > 1}
        up = self.transport.upload
        elements = [
            {
                "frontal_image_url": up(group[0].path),
                "reference_image_urls": [up(r.path) for r in group[1:]],
            }
            for group in groups.values()
        ]
        guide = [f"@Element{i} is {name}" for i, name in enumerate(groups, start=1)]
        guide += [f"@Image{i} is {label}" for i, (label, _) in enumerate(images, start=1)]
        payload: Fields = {"image_urls": [up(r.path) for _, r in images]}
        if elements:
            payload["elements"] = elements
        return f"{prompt}. References: {'; '.join(guide)}.", payload, spec

    def _send(self, model: str, payload: Fields, ctx: Context, wait: float = 900) -> Reply:
        return self.transport.send(model, payload, ctx, model=model, wait=wait)

    def _fetch_audio(self, reply: Reply, dst: Path, billed: float) -> None:
        """Bring a finished track down as a 48 kHz stereo file."""
        raw = dst.with_suffix(".src")
        self.transport.fetch(reply, raw, at=AUDIO_AT, billed=billed)
        media.run(["-i", str(raw), "-ar", "48000", "-ac", "2", str(dst)])
        raw.unlink(missing_ok=True)

    def image(self, req: ImageRequest, ctx: Context) -> Result:
        model = ctx.model or model_for("fal", "image")
        payload: Fields = {
            "prompt": req.prompt,
            "num_images": 1,
            "output_format": "png",
            "aspect_ratio": aspect_for(req.width, req.height),  # Nano Banana-family models
        }
        if model_for("fal", "image_resolution"):
            payload["resolution"] = model_for("fal", "image_resolution")
        if req.references:
            payload["prompt"], fields, spec = self._with_references(
                "image", model, req.prompt, req.references
            )
            payload.update(fields, **spec.get("extra", {}))
        if req.seed is not None:
            payload["seed"] = req.seed
        reply = self._send(model, payload, ctx)
        cost = float(price_for("fal", "image").get("per_image", 0))
        self.transport.fetch(reply, req.dst, at=("images.0.url",), billed=cost)
        return Result(path=req.dst, cost=cost, model=model, seed=_seed(reply, req.seed))

    def video(self, req: VideoRequest, ctx: Context) -> Result:
        refs = req.references
        key = "reference_to_video" if refs else "image_to_video" if req.start else "video"
        model = ctx.model or model_for("fal", key)
        fields: Fields = {}
        text = req.prompt
        if refs:  # a clip conditioned on the locked references, with the model's own audio left off
            text, fields, spec = self._with_references("video", model, req.prompt, refs)
        else:
            spec = video_spec("fal", model)
        billed, length = _billed_length(spec, req.duration)
        payload: Fields = {"prompt": text, "duration": length, **fields}
        aspect_field = spec.get("aspect_param", "aspect_ratio")
        if aspect_field:  # a model whose schema lists none is sent none
            payload[aspect_field] = req.aspect
        payload.update(spec.get("extra", {}))
        # The locked still is the first frame wherever the model has a field for one: every plain
        # clip, and a reference clip whose model takes the first frame apart from its references.
        start_field = (
            spec.get("start_image_param") if refs else spec.get("image_param", "image_url")
        )
        start_sent = bool(req.start and start_field)
        if req.start and start_field:
            payload[start_field] = self.transport.upload(req.start)
        end_used = bool(req.end and spec.get("end_image_param"))
        if req.end is not None and end_used:
            payload[spec["end_image_param"]] = self.transport.upload(req.end)
        seeded = req.seed is not None and spec.get("takes_seed", True)
        if seeded:
            payload["seed"] = req.seed
        reply = self._send(model, payload, ctx, wait=1800)
        cost = billed * float(price_for("fal", key, model).get("per_sec", 0))
        self.transport.fetch(reply, req.dst, at=("video.url",), billed=cost)
        return Result(
            path=req.dst,
            cost=cost,
            model=model,
            # a model whose schema has no seed was sent none, so the take cannot be remade by it
            seed=_seed(reply, req.seed) if seeded else None,
            sent=Sent(start_frame=start_sent, end_frame=end_used, seeded=bool(seeded)),
            billed_seconds=float(billed),
        )

    def lipsync(self, req: LipsyncRequest, ctx: Context) -> Result:
        """The clip with its mouth matched to the line. The shorter of the two sets the length."""
        model = ctx.model or model_for("fal", "lipsync")
        payload = {
            "video_url": self.transport.upload(req.video),
            "audio_url": self.transport.upload(req.audio),
            "sync_mode": "cut_off",
        }
        reply = self._send(model, payload, ctx, wait=1800)
        cost = media.duration(req.video) / 60 * float(price_for("fal", "lipsync").get("per_min", 0))
        self.transport.fetch(reply, req.dst, at=("video.url",), billed=cost)
        return Result(path=req.dst, cost=cost, model=model)

    def motion(self, req: MotionRequest, ctx: Context) -> Result:
        """Animate the character image using the driving video."""
        model = ctx.model or model_for("fal", "motion")
        payload = {
            "image_url": self.transport.upload(req.character),
            "video_url": self.transport.upload(req.driving),
        }
        reply = self._send(model, payload, ctx, wait=1800)
        cost = float(price_for("fal", "motion", model).get("cost_usd", 0.02))
        self.transport.fetch(reply, req.dst, at=("video.url",), billed=cost)
        return Result(path=req.dst, cost=cost, model=model)

    def song(self, req: SongRequest, ctx: Context) -> Result:
        if req.repaint is not None:
            raise ValueError("fal's song models cannot repaint a span of a take")
        model = ctx.model or model_for("fal", "song")
        spec = audio_spec("fal", model)
        style_field = spec.get("style_field", "prompt")
        lyrics = req.lyrics
        if req.instrumental and spec.get("instrumental_lyrics"):
            lyrics = spec["instrumental_lyrics"]
        if spec.get("lyrics_in_prompt"):  # one text field carries the sound and the words to sing
            payload: Fields = {style_field: f"{req.style}\n\nLyrics:\n{lyrics}".strip()}
        else:
            payload = {style_field: req.style, "lyrics": lyrics}
        most = spec.get("style_max_chars")
        if most and len(req.style) > int(most):
            raise ValueError(f"{model} takes at most {most} style characters, not {len(req.style)}")
        if req.duration and spec.get("takes_duration", True):
            payload["duration"] = int(req.duration)
        reply = self._send(model, payload, ctx)
        row = price_for("fal", "song", model)
        cost = float(row.get("per_track", 0)) + (req.duration or 0) * float(row.get("per_sec", 0))
        self._fetch_audio(reply, req.dst, cost)
        return Result(path=req.dst, cost=cost, model=model, seed=_seed(reply, req.seed))

    def separate(self, req: SeparateRequest, ctx: Context) -> Result:
        """Vocals, and everything else mixed back together from the model's other stems."""
        model = ctx.model or model_for("fal", "separate")
        stems = ("drums", "bass", "other")
        payload: Fields = {
            "audio_url": self.transport.upload(req.src),
            "model": "htdemucs",  # four stems; the six-stem model splits the rest further
            "stems": ["vocals", *stems],  # named, since fal's default asks for all six
            "output_format": "wav",
        }
        reply = self._send(model, payload, ctx, wait=1800)
        cost = media.duration(req.src) * float(
            price_for("fal", "separate", model).get("per_sec", 0)
        )
        names = list(stems) if reply.rehearsed else [n for n in stems if reply.get(f"{n}.url")]
        if not (reply.rehearsed or reply.get("vocals.url")) or not names:
            raise BilledError(cost, "fal finished but returned no stems")
        self.transport.fetch(reply, req.vocals, at=("vocals.url",), billed=cost)
        parts = []
        for name in names:
            part = req.rest.with_name(f"{req.rest.stem}.{name}.wav")
            self.transport.fetch(reply, part, at=(f"{name}.url",), billed=cost)
            parts.append(part)
        args = [arg for part in parts for arg in ("-i", str(part))]
        mix = f"amix=inputs={len(parts)}:normalize=0"
        media.run([*args, "-filter_complex", mix, "-ar", "48000", "-ac", "2", str(req.rest)])
        for part in parts:
            part.unlink(missing_ok=True)
        return Result(path=req.vocals, cost=cost, model=model)

    def music(self, req: MusicRequest, ctx: Context) -> Result:
        model = ctx.model or model_for("fal", "music")
        reply = self._send(model, {"prompt": req.prompt}, ctx)
        cost = float(price_for("fal", "music").get("per_track", 0))
        self._fetch_audio(reply, req.dst, cost)
        return Result(path=req.dst, cost=cost, model=model)

    def transcribe(self, req: TranscribeRequest, ctx: Context) -> Result:
        model = ctx.model or model_for("fal", "transcribe")
        payload = {"audio_url": self.transport.upload(req.src), "chunk_level": "word"}
        reply = self._send(model, payload, ctx)
        words: list[Word] = [
            {
                "start_sec": c["timestamp"][0],
                "end_sec": c["timestamp"][1],
                "text": c["text"].strip(),
                "confidence": 0.9,
            }
            for c in reply.get("chunks", [])
            if c.get("timestamp")
        ]
        minutes = media.duration(req.src) / 60
        return Result(
            words=words,
            text=str(reply.get("text", "")),
            model=model,
            cost=float(price_for("fal", "transcribe").get("per_min", 0)) * minutes,
        )
