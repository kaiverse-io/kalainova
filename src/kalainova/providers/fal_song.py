"""What a song on fal is sent, from its row in audio_models: the style and the words under each
model's own fields, and, for a model that follows a track (ADR 0028), how the track goes up.

A model whose row has a `guide` takes the track by an id from an upload of its own; the adapter
makes that upload and puts the id under the row's `field`. A use with `style: false` sends no style
text, because the vendor takes the sound from the track alone. A row with `needs_guide` only works
from a track. A guide a model cannot follow is refused here, before anything is sent.

A row with `composition_plan` takes the song as a plan of chunks instead, one per section, each
with its own length (from its bars at the song's tempo), words and direction (song_text.plan).

A row with `section_notes: tags` reads each section's note on its lyric tag, one with
`timestamps` each section under a timed marker; any other row reads the notes after the style
(song_text). A row's `languages` are the ones its model sings; a song in another is refused.
`lyrics_max_chars`, `style_max_chars` and `prompt_max_chars` (the style and the words in one
field) are the vendor's limits, refused here rather than cut upstream.

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
from . import song_text
from .contract import SongRequest

Fields = dict[str, Any]


def payload(model: str, req: SongRequest, host: str = "fal") -> tuple[Fields, Fields | None]:
    """The payload without the guide's id, and how the guide goes up (None with no guide). A
    model's own host (Mureka's API) sends the same request as fal does, from its own row."""
    if req.repaint is not None:
        raise ValueError(f"{host}'s song models cannot repaint a span of a take")
    spec = audio_spec(host, model)
    if spec.get("composition_plan"):  # one chunk per section, each its own length and direction
        return _plan_payload(model, req), None
    how = (spec.get("guide") or {}).get(req.guide.use) if req.guide else None
    if req.guide and not how:
        raise ValueError(f"{model} takes no {req.guide.use} track")
    if spec.get("needs_guide") and not req.guide:
        raise ValueError(
            f"{model} makes a song again from a {spec['needs_guide']} track; give it one"
        )
    _sings(model, spec, req.language)
    style_field = spec.get("style_field", "prompt")
    sent = _words(model, spec, req)
    if req.duration and spec.get("takes_duration", True):
        least = float(spec.get("min_sec") or 0)
        if req.duration < least:
            raise ValueError(f"{model} makes at least {least:g} s, not {req.duration:g}")
        sent["duration"] = int(req.duration)
    if req.vocal_gender and spec.get("gender_field") and not req.instrumental:
        sent[str(spec["gender_field"])] = req.vocal_gender
    if how is not None and how.get("style") is False:  # the track carries the sound instead
        sent.pop(style_field, None)
    return sent, how


def _sings(model: str, spec: Fields, language: str | None) -> None:
    """Refuse a song in a language the model's row does not list; a row with none lists all."""
    langs = [str(x) for x in spec.get("languages") or []]
    if langs and language and str(language).split("-")[0].lower() not in langs:
        raise ValueError(f"{model} sings {', '.join(langs)}, not {language}; choose another")


def _words(model: str, spec: Fields, req: SongRequest) -> Fields:
    """The style and the words under the model's own fields: one field for both, or two."""
    style_field = spec.get("style_field", "prompt")
    lyrics, style = _texts(model, spec, req)
    if not spec.get("lyrics_in_prompt"):
        return {style_field: style, "lyrics": lyrics}
    prompt = f"{style}\n\nLyrics:\n{lyrics}".strip()  # one field: the sound, then the words
    most = spec.get("prompt_max_chars")
    if most and len(prompt) > int(most):
        raise ValueError(
            f"{model} takes at most {most} characters of style and words together, "
            f"not {len(prompt)}"
        )
    return {style_field: prompt}


def _plan_payload(model: str, req: SongRequest) -> Fields:
    if req.guide:
        raise ValueError(f"{model} takes no guide track here")
    chunks = song_text.plan(
        req.sections, req.style, req.avoid, req.bpm, req.duration or 120, req.pronounce
    )
    sent: Fields = {"composition_plan": {"chunks": chunks}, "output_format": "mp3_48000_320"}
    if req.seed is not None:
        sent["seed"] = int(req.seed)
    if req.instrumental:
        sent["force_instrumental"] = True
    return sent


def _seconds(model: str, req: SongRequest, host: str = "fal") -> float:
    """How long the song asked for runs: a plan's chunks added up, else its length."""
    if audio_spec(host, model).get("composition_plan") and req.sections:
        return sum(song_text.section_ms(req.sections, req.bpm, req.duration or 120)) / 1000
    return float(req.duration or 0)


def _texts(model: str, spec: Fields, req: SongRequest) -> tuple[str, str]:
    """The words and the style as this model reads them, each section's note where it reads it,
    refused past the vendor's limits."""
    lyrics, style = req.lyrics, req.style
    if spec.get("section_notes") == "timestamps" and req.sections:  # timed, with notes or none
        lyrics = song_text.timestamped(req.sections, req.bpm, req.duration or 120)
    elif song_text.has_notes(req.sections):
        if spec.get("section_notes") == "tags":
            lyrics = song_text.tagged(req.sections, notes=True)
        else:
            style = song_text.styled(style, req.sections)
    if req.instrumental and spec.get("instrumental_lyrics"):
        lyrics = spec["instrumental_lyrics"]
    for text, limit, what in ((style, "style_max_chars", "style"),
                              (lyrics, "lyrics_max_chars", "lyrics")):  # fmt: skip
        most = spec.get(limit)
        if most and len(text) > int(most):
            raise ValueError(f"{model} takes at most {most} {what} characters, not {len(text)}")
    return lyrics, style


def edit_payload(model: str, req: SongRequest, host: str = "fal") -> tuple[Fields, Fields | None]:
    """A span of a take sung again with its words, for a model row that `edits`: by the vendor's
    own id of the take when it has one, else the take goes up first (the second value says how)."""
    spec = audio_spec(host, model)
    span = req.repaint
    if span is None or not spec.get("edits"):
        raise ValueError(f"{model} does not edit a span of a take")
    least, most = float(spec.get("min_region_sec") or 0), spec.get("max_region_sec")
    if span.end_sec - span.start_sec < least:
        raise ValueError(f"{model} edits a span of at least {least:g} s")
    if most and span.end_sec - span.start_sec > float(most):
        raise ValueError(f"{model} edits a span of at most {float(most):g} s; repair a shorter one")
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


def cost(model: str, req: SongRequest, host: str = "fal") -> float:
    """The song itself, without the guide's upload."""
    row = price_for(host, "song", model)
    return float(row.get("per_track", 0)) + _seconds(model, req, host) * float(
        row.get("per_sec", 0)
    )
