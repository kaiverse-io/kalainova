"""What a song model reads of a song file: its words under section tags, and how each section moves.

A section's `style` is a short note on what changes there ("restrained and intimate"). A model
whose row in `audio_models` has `section_notes: tags` reads each note on its section's lyric tag,
as its vendor's own prompt guide shows ("[Verse] restrained and intimate"). Any other model reads
the notes after the style, in order. Either way, every section of a song file reaches the model
that sings it (ADR 0029).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

Section = Mapping[str, Any]
NAMES = {"pre-chorus": "Pre-Chorus"}


def name(section: Section) -> str:
    kind = str(section.get("kind", "verse"))
    return NAMES.get(kind, kind.title())


def note(section: Section) -> str:
    return str(section.get("style") or "").strip().rstrip(".,; ")


def tagged(sections: Sequence[Section], notes: bool = False) -> str:
    """The words under their section tags, with each section's note on its tag when asked."""
    out = []
    for section in sections:
        said = note(section) if notes else ""
        out.append(f"[{name(section)}] {said}" if said else f"[{name(section)}]")
        out += [str(line) for line in section.get("lines") or []]
    return "\n".join(out) + "\n"


def has_notes(sections: Sequence[Section]) -> bool:
    return any(note(s) for s in sections)


def moves(sections: Sequence[Section]) -> str:
    """The section notes as one passage in song order, for a model that reads no notes on tags."""
    return " ".join(f"{name(s)}: {note(s)}." for s in sections if note(s))


def styled(style: str, sections: Sequence[Section]) -> str:
    """The style with how the song moves after it."""
    said = moves(sections)
    if not said:
        return style
    return f"{style.strip().rstrip('.,; ')}. {said}" if style.strip() else said


CHUNK_MS = (3000, 120000)  # a plan's chunk, as ElevenLabs takes it
CHUNKS_MOST = 30
CHUNK_LINES_MOST, LINE_CHARS_MOST = 30, 200


def section_ms(sections: Sequence[Section], bpm: float | None, seconds: float) -> list[int]:
    """How long each section runs: its bars at the song's tempo when every section names them,
    else the song's length shared in proportion to its lines."""
    if bpm and sections and all(s.get("bars") for s in sections):
        return [round(float(s["bars"]) * 4 * 60000 / float(bpm)) for s in sections]
    weights = [max(len(s.get("lines") or []), 2) for s in sections]
    return [round(seconds * 1000 * w / sum(weights)) for w in weights]


def plan(sections: Sequence[Section], style: str, avoid: str, bpm: float | None,
         seconds: float) -> list[dict[str, Any]]:  # fmt: skip
    """A composition plan, one chunk per section: its words under its tag, its length, and its
    note as the direction for it, first. The first chunk sets the whole song's tone, so it carries
    the style too, after its own note: a style put first there made a take's quiet intro its
    loudest section (2026-11-20). What to keep out is held on every chunk, with what each section
    keeps out of itself (`avoid` on a section). Refused where a chunk cannot be made."""
    if not sections or len(sections) > CHUNKS_MOST:
        raise ValueError(f"a composition plan takes 1 to {CHUNKS_MOST} sections")

    def keep_out(section: Section) -> list[str] | None:
        said = f"{section.get('avoid') or ''},{avoid}"
        return list(dict.fromkeys(w.strip() for w in said.split(",") if w.strip())) or None

    chunks = []
    for n, (section, ms) in enumerate(
        zip(sections, section_ms(sections, bpm, seconds), strict=True)
    ):
        lines = [str(line) for line in section.get("lines") or []]
        if not CHUNK_MS[0] <= ms <= CHUNK_MS[1]:
            raise ValueError(f"{name(section)} runs {ms / 1000:g} s; a chunk is 3 to 120 s")
        if len(lines) > CHUNK_LINES_MOST or any(len(line) > LINE_CHARS_MOST for line in lines):
            raise ValueError(f"{name(section)} has more lines, or longer ones, than a chunk takes")
        styles = [s for s in (note(section), (style if n == 0 else "")) if s] or [style]
        chunks.append({"text": "\n".join([f"[{name(section)}]", *lines]), "duration_ms": ms,
                       "positive_styles": styles, "negative_styles": keep_out(section),
                       "context_adherence": "high"})  # fmt: skip
    return chunks
