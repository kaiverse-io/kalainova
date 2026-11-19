"""What a song on fal is sent, from its row in audio_models: the style and the words under each
model's own fields, and, for a model that follows a track (ADR 0028), how the track goes up.

A model whose row has a `guide` takes the track by an id from an upload of its own; the adapter
makes that upload and puts the id under the row's `field`. A use with `style: false` sends no style
text, because the vendor takes the sound from the track alone. A row with `needs_guide` only works
from a track. A guide a model cannot follow is refused here, before anything is sent.

A row that `edits` sings one span of a take again with new words (`edit_payload`): a generate
row names its edit route under `edit_with`, and a repair is pinned to that route, so the package,
the ledger and the price all name the edit model. The take goes by the vendor's own id when it
made it, else as an upload.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import media
from ..config import audio_spec, price_for
from .contract import SongRequest

Fields = dict[str, Any]


def payload(model: str, req: SongRequest) -> tuple[Fields, Fields | None]:
    """The payload without the guide's id, and how the guide goes up (None with no guide)."""
    if req.repaint is not None:
        raise ValueError("fal's song models cannot repaint a span of a take")
    spec = audio_spec("fal", model)
    how = (spec.get("guide") or {}).get(req.guide.use) if req.guide else None
    if req.guide and not how:
        raise ValueError(f"{model} takes no {req.guide.use} track")
    if spec.get("needs_guide") and not req.guide:
        raise ValueError(
            f"{model} makes a song again from a {spec['needs_guide']} track; give it one"
        )
    style_field = spec.get("style_field", "prompt")
    lyrics = req.lyrics
    if req.instrumental and spec.get("instrumental_lyrics"):
        lyrics = spec["instrumental_lyrics"]
    if spec.get("lyrics_in_prompt"):  # one text field carries the sound and the words to sing
        sent: Fields = {style_field: f"{req.style}\n\nLyrics:\n{lyrics}".strip()}
    else:
        sent = {style_field: req.style, "lyrics": lyrics}
    most = spec.get("style_max_chars")
    if most and len(req.style) > int(most):
        raise ValueError(f"{model} takes at most {most} style characters, not {len(req.style)}")
    if req.duration and spec.get("takes_duration", True):
        sent["duration"] = int(req.duration)
    if req.vocal_gender and spec.get("gender_field") and not req.instrumental:
        sent[str(spec["gender_field"])] = req.vocal_gender
    if how is not None and how.get("style") is False:  # the track carries the sound instead
        sent.pop(style_field, None)
    return sent, how


def edit_payload(model: str, req: SongRequest) -> tuple[Fields, Fields | None]:
    """A span of a take sung again with its words, for a model row that `edits`: by the vendor's
    own id of the take when it has one, else the take goes up first (the second value says how)."""
    spec = audio_spec("fal", model)
    span = req.repaint
    if span is None or not spec.get("edits"):
        raise ValueError(f"{model} does not edit a span of a take")
    least = float(spec.get("min_region_sec") or 0)
    if span.end_sec - span.start_sec < least:
        raise ValueError(f"{model} edits a span of at least {least:g} s")
    if not span.lyrics.strip():
        raise ValueError(f"{model} sings new words over the span: name the section to edit")
    sent: Fields = {
        "lyrics": span.lyrics,
        "edit_start": int(round(span.start_sec * 1000)),
        "edit_end": int(round(span.end_sec * 1000)),
    }
    if span.vendor_id:
        sent["song_id"] = span.vendor_id
        return sent, None
    return sent, {"upload": spec["upload"], "purpose": spec["purpose"], "field": "upload_audio_id"}


def upload_copy(source: Path) -> Path:
    """The take as the vendor's upload takes it (AAC in M4A), beside it and encoded bit-exact, so
    a rehearsal and the paid run send the same bytes."""
    copy = source.with_suffix(".upload.m4a")
    if not copy.exists():
        media.run(["-i", str(source), "-map_metadata", "-1", "-ac", "2", "-ar", "48000",
                   "-c:a", "aac", "-b:a", "256k", "-fflags", "+bitexact", "-flags:a", "+bitexact",
                   str(copy)])  # fmt: skip
    return copy


def upload_cost(upload: str) -> float:
    return float(price_for("fal", "upload", upload).get("per_call", 0))


def guide_cost(model: str) -> float:
    """What taking in a guide costs before the song itself: one upload."""
    hows = list((audio_spec("fal", model).get("guide") or {}).values())
    return upload_cost(str(hows[0]["upload"])) if hows else 0.0


def cost(model: str, req: SongRequest) -> float:
    """The song itself, without the guide's upload."""
    row = price_for("fal", "song", model)
    return float(row.get("per_track", 0)) + (req.duration or 0) * float(row.get("per_sec", 0))
