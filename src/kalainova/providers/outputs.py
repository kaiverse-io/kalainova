"""Whether a file a provider returned is what was asked for: readable, the shape and size asked,
with a picture where one was asked and a sound where one was. The router refuses one that is not,
before it is kept or recorded."""

from __future__ import annotations

from pathlib import Path

from .. import media
from .contract import ImageRequest, Request

PICTURE_OUTPUTS = ("image", "video", "motion", "lipsync", "graphics")
SOUND_OUTPUTS = ("song", "music")
ASPECT_TOLERANCE = 0.03
MIN_SCALE = 0.5  # the editor can upscale a large image, not rescue a thumbnail


def check(request: Request, path: Path) -> None:
    """Refuse a file that is unreadable or not what was asked for. Raises ValueError or OSError."""
    capability = request.capability
    if isinstance(request, ImageRequest):
        from PIL import Image

        with Image.open(path) as im:
            width, height = im.size
            im.verify()
        want_w, want_h = request.width, request.height
        if want_w and want_h:
            if abs(width / height - want_w / want_h) > ASPECT_TOLERANCE * (want_w / want_h):
                raise ValueError(f"image is {width}x{height}, wrong shape for {want_w}x{want_h}")
            if width < want_w * MIN_SCALE:
                raise ValueError(f"image is {width}x{height}, too small for {want_w}x{want_h}")
    elif media.duration(path) <= 0:
        raise ValueError("file has no duration")
    if capability in PICTURE_OUTPUTS and not media.has_picture(path):
        raise ValueError("no picture: one flat tone throughout, the model's decode failed")
    if capability in SOUND_OUTPUTS and not media.has_sound(path):
        raise ValueError("no sound: the file is silent, the model's decode failed")
