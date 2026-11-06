"""Looks: one grade path for stills and footage, as a 3D LUT.

A look is data, not filter text, so no value from a plan reaches a filtergraph. Each is gentle by
rule: the tone curve never crushes black or clips white, and skin moves less than everything else.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

Rgb = npt.NDArray[Any]
LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)
NEUTRAL = (0.0, 0.0, 0.0)


@dataclass(frozen=True)
class Look:
    contrast: float = 0.10
    saturation: float = 1.0
    shadows: tuple[float, float, float] = NEUTRAL
    highlights: tuple[float, float, float] = NEUTRAL
    black: float = 0.012  # lifted a touch, so shadow detail survives a phone screen
    white: float = 0.985  # rolled off, so highlights never hit a hard edge


LOOKS: dict[str, Look] = {
    "natural": Look(contrast=0.10, saturation=1.04),
    "warm": Look(
        contrast=0.12, saturation=1.06, shadows=(0.006, 0.0, -0.008), highlights=(0.02, 0.006, -0.02)
    ),
    "cool": Look(
        contrast=0.12, saturation=1.0, shadows=(-0.008, 0.0, 0.012), highlights=(-0.012, 0.0, 0.016)
    ),
    "teal_orange": Look(
        contrast=0.16, saturation=1.1, shadows=(-0.016, 0.0, 0.02), highlights=(0.024, 0.006, -0.024)
    ),
    "film": Look(contrast=0.14, saturation=0.92, black=0.03, white=0.965, shadows=(0.0, 0.0, 0.006)),
    "bw": Look(contrast=0.18, saturation=0.0),
    "vivid": Look(contrast=0.14, saturation=1.2),
}


def _skin_weight(rgb: Rgb) -> Rgb:
    """Near 1 for skin tones: red above green above blue, in a narrow ratio."""
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    spread = np.maximum(r - b, 1e-4)
    hue = (r - g) / spread
    in_order = (r > g) & (g > b)
    return np.where(in_order, np.exp(-(((hue - 0.48) / 0.22) ** 2)), 0.0)


def apply(name: str, rgb: Rgb, gamma: float = 1.0) -> Rgb:
    """Grade colours in 0..1, gamma first, then tone, colour balance, and saturation."""
    spec = LOOKS[name]
    x = np.clip(rgb.astype(np.float32), 0.0, 1.0)
    if abs(gamma - 1.0) > 1e-3:
        x = x ** (1.0 / gamma)
    toned = x - spec.contrast * np.sin(2 * np.pi * x) / (2 * np.pi)
    toned = spec.black + (spec.white - spec.black) * toned
    luma = (toned @ LUMA)[..., None]
    shadow = (1.0 - luma) ** 2
    light = luma**2
    toned = toned + shadow * np.array(spec.shadows, np.float32)
    toned = toned + light * np.array(spec.highlights, np.float32)
    weight = _skin_weight(x)[..., None]
    amount = 1.0 + (spec.saturation - 1.0) * (1.0 - 0.7 * weight) if spec.saturation else 0.0
    return np.clip(luma + amount * (toned - luma), 0.0, 1.0).astype(np.float32)


def cube_text(name: str, gamma: float = 1.0, size: int = 33) -> str:
    """The look as an Adobe .cube file. Red varies fastest, as the format requires."""
    axis = np.linspace(0.0, 1.0, size, dtype=np.float32)
    b, g, r = np.meshgrid(axis, axis, axis, indexing="ij")
    grid = np.stack([r, g, b], axis=-1).reshape(-1, 3)
    rows = "\n".join(f"{p[0]:.6f} {p[1]:.6f} {p[2]:.6f}" for p in apply(name, grid, gamma))
    return f"LUT_3D_SIZE {size}\n{rows}\n"
