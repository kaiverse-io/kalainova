"""What vocal and speech audio can tell: pitch snapping, clipping, and vocal dynamics."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from .. import media
from .readings import Reading, at_most, summarise
from .sound import clipped_share, dc_offset, pitch_snapping


def speech_readings(path: Path) -> list[Reading]:
    """Measure speech or vocal characteristics on an isolated voice track or sample."""
    left, right, sr = media.decode_stereo(path)
    mono = (left + right) / 2
    return [
        at_most("audio.clipping", clipped_share(mono), "clipped_share_max", blocks=True),
        at_most("audio.dc_offset", dc_offset(mono), "dc_offset_max"),
        at_most("audio.pitch_snapping", pitch_snapping(mono, sr), "audio_pitch_snapping_max"),
    ]


def measure_speech(path: Path) -> dict[str, Any]:
    """Full studio bar measurement report for a speech or voice track."""
    return summarise([asdict(r) for r in speech_readings(path)])
