"""A stream's fixed sound identity: the song-side equivalent of a face kit.

Keeps many tracks sounding like one act — drum kit, tempo range, keys, and a mastering
target held fixed across a stream's songs, the same way a face kit holds a character fixed
across its shots. `check_track` reads a rendered track's metadata against that identity and
never reaches a model or a provider.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SoundIdentity:
    name: str
    tempo_range: tuple[float, float] = (80.0, 140.0)
    keys: list[str] = field(default_factory=list)
    drum_kit: str = ""
    target_lufs: float = -14.0
    true_peak_dbtp_max: float = -1.0


def load_sound_identity(data: dict[str, Any] | str | Path) -> SoundIdentity:
    """Load a sound identity from a dict, a JSON string, or a path to a JSON file."""
    if isinstance(data, dict):
        payload = data
    else:
        path = Path(data)
        payload = json.loads(path.read_text()) if path.exists() else json.loads(str(data))

    tempo_range = payload.get("tempo_range")
    kwargs: dict[str, Any] = {"name": payload["name"]}
    if tempo_range is not None:
        low, high = tempo_range
        kwargs["tempo_range"] = (float(low), float(high))
    if "keys" in payload:
        kwargs["keys"] = list(payload["keys"])
    if "drum_kit" in payload:
        kwargs["drum_kit"] = str(payload["drum_kit"])
    if "target_lufs" in payload:
        kwargs["target_lufs"] = float(payload["target_lufs"])
    if "true_peak_dbtp_max" in payload:
        kwargs["true_peak_dbtp_max"] = float(payload["true_peak_dbtp_max"])
    return SoundIdentity(**kwargs)


def check_track(metadata: dict[str, Any], identity: SoundIdentity) -> list[dict[str, str]]:
    """Check a track's metadata against a stream's sound identity: tempo, key, loudness."""
    checks = []

    bpm = metadata.get("bpm")
    low, high = identity.tempo_range
    if bpm is not None and not (low <= float(bpm) <= high):
        checks.append(
            {
                "id": "sound.tempo",
                "status": "warn",
                "detail": f"tempo {bpm} outside {identity.tempo_range}",
            }
        )
    else:
        checks.append({"id": "sound.tempo", "status": "pass", "detail": f"tempo {bpm} held"})

    key = metadata.get("key")
    if identity.keys and key not in identity.keys:
        checks.append(
            {
                "id": "sound.key",
                "status": "warn",
                "detail": f"key {key!r} not in {identity.keys}",
            }
        )
    else:
        checks.append({"id": "sound.key", "status": "pass", "detail": f"key {key!r} held"})

    lufs = metadata.get("lufs")
    if lufs is not None and abs(float(lufs) - identity.target_lufs) > 2.0:
        checks.append(
            {
                "id": "sound.loudness",
                "status": "warn",
                "detail": f"loudness {lufs} LUFS deviates from target {identity.target_lufs}",
            }
        )
    else:
        checks.append(
            {"id": "sound.loudness", "status": "pass", "detail": f"loudness {lufs} LUFS held"}
        )

    return checks
