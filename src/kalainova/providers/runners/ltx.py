"""LTX-2 through mlx_video, with two fixes. Runs in the model environment, not the engine's.

A padding row attends to itself. The text encoder left-pads to 1024 tokens, so each padding row has
every position masked. Its softmax returns NaN, the next layer spreads that to the real tokens as
0 x NaN, and the clip decodes to pure black with exit code 0. Real tokens never look at padding, so
this changes nothing they compute. Measured: 100% NaN embeddings before, none in 49 layers after.

Frames are written losslessly. The package's writer is cv2 at about 1.3 Mbps 4:2:0 with no colour
tags, which throws detail away before the engine sees the file. These are the same lossless 4:4:4
BT.709 intermediates the rest of the picture path uses.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Any

import cv2
import mlx.core as mx
from mlx_video import generate_av
from mlx_video.models.ltx import text_encoder

TO_BT709 = "scale=out_color_matrix=bt709:out_range=tv:flags=accurate_rnd+full_chroma_int"
_mask = text_encoder.LanguageModel._create_causal_mask_with_padding


def _self_attending(self: Any, seq_len: int, attention_mask: Any, dtype: Any) -> Any:
    mask = _mask(self, seq_len, attention_mask, dtype)
    return mx.where(mx.eye(seq_len, dtype=mx.bool_)[None, None], mx.zeros_like(mask), mask)


class _LosslessWriter:
    def __init__(self, path: Any, _fourcc: Any, fps: float, size: tuple[int, int]) -> None:
        w, h = size
        ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
        # an argument list built here, never a shell string
        self._proc = subprocess.Popen(  # noqa: S603
            [
                ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "rawvideo", "-pix_fmt", "bgr24",
                "-s", f"{w}x{h}", "-r", f"{fps:g}", "-i", "-",
                "-vf", f"{TO_BT709},format=yuv444p",
                "-c:v", "libx264", "-preset", "fast", "-qp", "0",
                "-colorspace", "bt709", "-color_primaries", "bt709",
                "-color_trc", "bt709", "-color_range", "tv",
                "-movflags", "+faststart",
                str(path),
            ],
            stdin=subprocess.PIPE,
        )  # fmt: skip

    def write(self, frame: Any) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.write(frame.tobytes())

    def release(self) -> None:
        assert self._proc.stdin is not None
        self._proc.stdin.close()
        if self._proc.wait() != 0:
            raise RuntimeError("the lossless frame writer failed")


text_encoder.LanguageModel._create_causal_mask_with_padding = _self_attending
cv2.VideoWriter = _LosslessWriter

if __name__ == "__main__":
    generate_av.main()
