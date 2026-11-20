"""Remote providers over plain HTTPS, through providers/transport.py. Keys come from the environment.

Model ids and unit prices live in config/studio.yaml so swapping a model is a
config change, not a code change. Prices are estimates used for the cost cap;
the vendor invoice is the truth.
"""

from __future__ import annotations

import base64
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..config import model_for, price_for
from . import song_text
from .base import Provider, register
from .contract import (
    Context,
    InvalidRequestError,
    MusicRequest,
    Result,
    SfxRequest,
    SongRequest,
    TextRequest,
    UnauthorizedError,
    VoiceRequest,
)
from .transport import TIMEOUT, Https, Reply, Transport

LOSSY_AUDIO = "mp3_44100_128"  # what every ElevenLabs plan allows


# ---------------------------------------------------------------- Anthropic
def _anthropic_headers() -> dict[str, str]:
    return {
        "x-api-key": os.environ["ANTHROPIC_API_KEY"],
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }


@register
class Anthropic(Provider):
    """Planner, editor and QA judge. Text and vision."""

    name = "anthropic"
    capabilities = ("llm", "judge")
    env_key = "ANTHROPIC_API_KEY"
    synthetic = False
    rehearses = True
    transport: Transport = Https("anthropic", "https://api.anthropic.com/v1", _anthropic_headers)

    def llm(self, req: TextRequest, ctx: Context) -> Result:
        capability = "judge" if req.judging else "llm"
        model = ctx.model or model_for("anthropic", capability) or model_for("anthropic", "llm")
        content: list[dict[str, Any]] = []
        for img in req.images:
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
        content.append({"type": "text", "text": req.prompt})
        body: dict[str, Any] = {
            "model": model,
            "max_tokens": req.max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        if req.system:
            body["system"] = req.system
        reply = self.transport.send("messages", body, ctx, model=model, wait=600)
        text = "".join(
            b.get("text", "") for b in reply.get("content", []) if b.get("type") == "text"
        )
        u = reply.get("usage", {})
        # settled at the model that answered: a judge on a small model is not charged as a planner
        p = price_for("anthropic", capability, model)
        cost = u.get("input_tokens", 0) / 1e6 * p.get("input_per_mtok", 0) + u.get(
            "output_tokens", 0
        ) / 1e6 * p.get("output_per_mtok", 0)
        return Result(text=text, cost=cost, model=model, meta={"usage": u})

    def judge(self, req: TextRequest, ctx: Context) -> Result:
        """The model check: the same call, on the judge model, priced as the judge."""
        return self.llm(replace(req, judging=True), ctx)


# ---------------------------------------------------------------- ElevenLabs
def _elevenlabs_headers() -> dict[str, str]:
    return {"xi-api-key": os.environ["ELEVENLABS_API_KEY"], "content-type": "application/json"}


@register
class ElevenLabs(Provider):
    """Voice with character-level timestamps, plus music, songs, and sound effects."""

    name = "elevenlabs"
    capabilities = ("voice", "music", "song", "sfx")
    env_key = "ELEVENLABS_API_KEY"
    rehearses = True
    transport: Transport = Https("elevenlabs", "https://api.elevenlabs.io/v1", _elevenlabs_headers)

    def _post(
        self, path: str, body: dict[str, Any], ctx: Context, *, timeout: float = TIMEOUT
    ) -> tuple[Reply, str]:
        """Ask for the configured audio format, and fall back if this plan does not include it.

        A premium master built on 128 kbps MP3 stems is lossless in name only, so the format used is
        kept with the asset for QA to read.
        """
        wanted = model_for("elevenlabs", "output_format") or LOSSY_AUDIO
        model = str(body.get("model_id") or path)
        try:
            reply = self.transport.send(
                path, body, ctx, model=model, wait=timeout, params={"output_format": wanted}
            )
        except (InvalidRequestError, UnauthorizedError) as exc:
            if wanted == LOSSY_AUDIO or "output_format" not in str(exc):
                raise
            wanted = LOSSY_AUDIO
            reply = self.transport.send(
                path, body, ctx, model=model, wait=timeout, params={"output_format": wanted}
            )
        return reply, wanted

    @staticmethod
    def _audio_to_wav(source: Path, dst: Path, fmt: str, channels: int, raw: bool) -> None:
        from .. import media

        pcm = ["-f", "s16le", "-ar", fmt.split("_")[1], "-ac", "1"] if raw else []
        media.run([*pcm, "-i", str(source), "-ar", "48000", "-ac", str(channels), str(dst)])
        source.unlink(missing_ok=True)

    def _save(
        self, reply: Reply, dst: Path, fmt: str, channels: int, cost: float, encoded: str = ""
    ) -> None:
        """The vendor's audio as a 48 kHz file. A stand-in in a rehearsal is already a WAV."""
        source = dst.with_suffix(".src")
        self.transport.fetch(reply, source, encoded=encoded, billed=cost)
        raw = fmt.startswith("pcm_") and not reply.rehearsed
        self._audio_to_wav(source, dst, fmt, channels, raw)

    def voice(self, req: VoiceRequest, ctx: Context) -> Result:
        model = ctx.model or model_for("elevenlabs", "voice")
        voice_id = (
            req.voice
            or os.environ.get("ELEVENLABS_VOICE_ID")
            or model_for("elevenlabs", "voice_id")
        )
        body: dict[str, Any] = {
            "text": req.text,
            "model_id": model,
            "voice_settings": dict(req.settings or {})
            or {
                "stability": 0.45,
                "similarity_boost": 0.8,
                "style": 0.35,
                "use_speaker_boost": True,
            },
        }
        if req.previous_text:
            body["previous_text"] = req.previous_text
        if req.next_text:
            body["next_text"] = req.next_text
        reply, fmt = self._post(f"text-to-speech/{voice_id}/with-timestamps", body, ctx)
        cost = len(req.text) / 1000 * price_for("elevenlabs", "voice").get("per_kchar", 0)
        self._save(reply, req.dst, fmt, 1, cost, encoded="audio_base64")
        alignment = reply.get("alignment") or reply.get("normalized_alignment") or {}
        return Result(
            path=req.dst,
            cost=cost,
            model=model,
            words=chars_to_words(alignment),  # type: ignore[arg-type]  # reason: same keys
            meta={"voice_id": voice_id, "audio_format": fmt},
        )

    def music(self, req: MusicRequest, ctx: Context) -> Result:
        body = {
            "prompt": req.prompt,
            "music_length_ms": int(max(req.duration, 10.0) * 1000),  # API minimum is 10 s
            "model_id": model_for("elevenlabs", "music"),
        }
        reply, fmt = self._post("music", body, ctx, timeout=600)
        return self._track(reply, req.dst, req.duration, "music", fmt)

    def song(self, req: SongRequest, ctx: Context) -> Result:
        """A song from a composition plan, built as every host of this model builds it
        (song_text.plan): one chunk per section, its length from its bars at the song's tempo, its
        own note first, and how its uncommon words are said. With no sections, a prompt."""
        if req.repaint is not None:
            raise ValueError("ElevenLabs cannot repaint a span of a take")
        seconds = float(req.duration or 120)
        body: dict[str, Any] = {
            "model_id": model_for("elevenlabs", "song") or model_for("elevenlabs", "music")
        }
        if req.sections:
            body["composition_plan"] = {
                "chunks": song_text.plan(
                    req.sections, req.style, req.avoid, req.bpm, seconds, req.pronounce
                )
            }
            seconds = sum(song_text.section_ms(req.sections, req.bpm, seconds)) / 1000
        else:
            body["prompt"] = f"{req.style}\n{req.lyrics}"
        if req.seed is not None:
            body["seed"] = int(req.seed)
        if req.instrumental:
            body["force_instrumental"] = True
        reply, fmt = self._post("music", body, ctx, timeout=900)
        return self._track(reply, req.dst, seconds, "song", fmt)

    def sfx(self, req: SfxRequest, ctx: Context) -> Result:
        body = {
            "text": req.prompt,
            "duration_seconds": max(0.5, min(req.duration, 22)),
            "prompt_influence": 0.5,
            "model_id": model_for("elevenlabs", "sfx"),
        }
        reply, fmt = self._post("sound-generation", body, ctx)
        return self._track(reply, req.dst, req.duration, "sfx", fmt)

    def _track(self, reply: Reply, dst: Path, duration: float, cap: str, fmt: str) -> Result:
        cost = duration / 60 * price_for("elevenlabs", cap).get("per_min", 0)
        self._save(reply, dst, fmt, 2, cost)
        return Result(
            path=dst, cost=cost, model=model_for("elevenlabs", cap), meta={"audio_format": fmt}
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
