"""Remote providers over plain HTTPS (requests). Keys come from the environment.

Model ids and unit prices live in config/studio.yaml so swapping a model is a
config change, not a code change. Prices are estimates used for the cost cap;
the vendor invoice is the truth.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

import requests

from ..config import model_for, price_for
from .base import Provider, Result, register

TIMEOUT = 120
LOSSY_AUDIO = "mp3_44100_128"  # what every ElevenLabs plan allows
SONG_MOST_CHUNKS = 30
SONG_LEAST_CHUNK_MS = 3000


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
    """Voice with character-level timestamps, plus music, songs, and sound effects."""

    name = "elevenlabs"
    capabilities = ("voice", "music", "song", "sfx")
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
