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
from pathlib import Path
from typing import Any

import requests

from .. import media
from ..config import model_for, price_for, reference_spec, sing_spec, video_spec
from . import fal_sing, fal_song, payloads
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
    SingRequest,
    SongRequest,
    TranscribeRequest,
    VideoRequest,
    Word,
)
from .fal_catalog import list_price, schema_problems, unit_price
from .fal_sing import set_length as _billed_length
from .transport import TIMEOUT, Reply, Transport, raise_for, request_id

QUEUE = "https://queue.fal.run/"
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
        "sing",
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
        if billable.capability == "sing" and billable.duration:
            spec = sing_spec("fal", model or model_for("fal", "sing"))
            return float(fal_sing.sung_length(spec, billable.duration)[0])
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
        if billable.capability in ("video", "sing") and billable.duration:
            billable = Billable(
                capability=billable.capability,
                duration=self.billed_seconds(billable, model),
                image=billable.image,
                references=billable.references,
            )
        if billable.capability in ("song", "separate", "sing") and not model:
            model = model_for("fal", billable.capability)
        found = super().estimate(billable, model)
        if found is not None and billable.capability == "song" and billable.guided and model:
            found += fal_song.guide_cost(model)
        return found

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
        made = min(media.duration(req.video), media.duration(req.audio))  # cut_off: the shorter
        cost = made / 60 * float(price_for("fal", "lipsync", model).get("per_min", 0))
        self.transport.fetch(reply, req.dst, at=("video.url",), billed=cost)
        return Result(path=req.dst, cost=cost, model=model)

    def sing(self, req: SingRequest, ctx: Context) -> Result:
        """A shot sung in one call, sent as fal_sing says for the model's row."""
        model = ctx.model or model_for("fal", "sing")
        spec = sing_spec("fal", model)
        if not spec:
            raise ValueError(f"{model} is not listed under sing_models")
        up = self.transport.upload
        most = int(spec.get("max_image_bytes") or 0)
        still = media.within_bytes(req.still, most) if most else req.still
        line = media.duration(req.audio)
        billed, length = fal_sing.sung_length(spec, line)
        refs = [up(r.path) for r in fal_sing.references(spec, req)]
        sent = up(fal_sing.line_for(spec, req.audio))
        payload = fal_sing.payload(spec, req, up(still), sent, refs, length)
        reply = self._send(model, payload, ctx, wait=1800)
        cost = billed * float(price_for("fal", "sing", model).get("per_sec", 0))
        self.transport.fetch(reply, req.dst, at=("video.url",), billed=cost)
        if fal_sing.shortest(spec) > line and req.dst.is_file():
            fal_sing.cut_to_line(req.dst, line)
        seeded = "seed" in payload
        return Result(
            path=req.dst,
            cost=cost,
            model=model,
            seed=_seed(reply, req.seed) if seeded else None,
            sent=Sent(start_frame=True, end_frame=False, seeded=seeded),
            billed_seconds=float(billed),
        )

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

    def _vendor_file(self, path: Path, how: Fields, ctx: Context) -> tuple[str, float]:
        """A file the vendor keeps on its side, for a model that takes an id instead of a URL, and
        what keeping it cost. The id is sealed as the file's bytes, so a signed payload binds the
        file and not an id that only the paid run can know."""
        upload = str(how["upload"])
        reply = self._send(
            upload, {"file_url": self.transport.upload(path), "purpose": how["purpose"]}, ctx
        )
        cost = fal_song.upload_cost(upload)
        ctx.receipt.step(upload, cost)  # billed now, whatever becomes of the song
        found = reply.rehearsed or reply.get("id")
        if not found:
            raise BilledError(cost, f"fal {upload} finished but returned no file id")
        payloads.remember(str(found), path)
        return str(found), cost

    def song(self, req: SongRequest, ctx: Context) -> Result:
        """A song sent as fal_song says for the model's row; a guide goes up first, for its id."""
        model = ctx.model or model_for("fal", "song")
        taken = 0.0
        if req.repaint is not None:  # one span sung again, on a row that edits
            payload, how = fal_song.edit_payload(model, req)
            if how:
                upload = fal_song.upload_copy(req.repaint.source)
                payload[str(how["field"])], taken = self._vendor_file(upload, how, ctx)
        else:
            payload, how = fal_song.payload(model, req)
            if req.guide and how:
                payload[str(how["field"])], taken = self._vendor_file(req.guide.source, how, ctx)
        reply = self._send(model, payload, ctx)
        cost = taken + fal_song.cost(model, req)
        self._fetch_audio(reply, req.dst, cost)
        # the vendor's own id for the take, so a later edit of it needs no upload
        kept = {"song_id": str(reply.get("song_id"))} if reply.get("song_id") else {}
        return Result(path=req.dst, cost=cost, model=model, seed=_seed(reply, req.seed), meta=kept)

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
