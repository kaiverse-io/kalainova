---
name: render-measured-on-apple-silicon
description: Hardware encoders and decoders lost to software when measured on an M5 Pro, so rendering stays on the CPU and only model inference uses the GPU
metadata:
  type: project
---
Measured 2026-11-07 on 20 s of 1080p: ProRes `prores_ks` 55.6 dB against `prores_videotoolbox` 41.7 dB. H.264 `libx264 -preset slow -crf 16` 56 dB at 4.5 Mbps against `h264_videotoolbox` 59 dB at 13 Mbps, at similar speed. Software H.264 decode took 0.31 s against 1.66 s with `-hwaccel videotoolbox`.

**Why:** "use the GPU" sounds right for everything, and here it costs fidelity or bitrate for no real speed.

**How to apply:** Models run on Metal through MLX. Rendering uses the CPU cores. Re-measure before changing this, on the same footage. Only one large model should load at a time, because they share unified memory.
