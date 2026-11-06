# Run models on a Mac

Make pieces with open models on a Mac's GPU, at no cost per call. A human still reads each model's licence before anything is released.

## Set up

The models need Apple silicon and a lot of unified memory. These figures come from a machine with 64 GB. Models and engine live in separate environments, because the models' packages are heavy and they change often.

```bash
uv venv --python 3.12 ~/mlx-models
uv pip install --python ~/mlx-models/bin/python \
  mlx==0.32.4 mlx-audio==0.6.4 mflux==0.24.0 mlx-video-with-audio==0.1.37
export KALAINOVA_MLX_PYTHON=~/mlx-models/bin/python
```

The first call to each model downloads its weights. Motion needs about 70 GB of them, and music about 14 GB.

Then name the provider in a job, or in `preference` in `config/studio.yaml`:

```json
"providers": {"voice": ["mac"], "image": ["mac"], "video": ["mac"], "music": ["mac"], "transcribe": ["mac"]}
```

Model ids are under `models.mac` in `config/studio.yaml`. A job asks for moving shots with `brief.max_video_beats`, which defaults to 3.

## What to expect

| Work | Measured | Peak memory |
|---|---|---|
| A still, about 1080p | 1.5 min | Small |
| A voice line, with timing | Under 30 s | Small |
| Music | About 4 min | About 14 GB |
| A 6.4 s moving shot at 1472x832 | 14 min | 48 GB |

- **One model at a time.** Each call takes a lock on the GPU, so jobs queue instead of fighting for memory. Keep other large programs closed during motion.
- **The machine stays awake** for each call. Run it on mains power.
- **Quality gates can run alongside,** at low priority, because they use the CPU cores and the models use the GPU.

## Licences

Read these before releasing anything. This table is a summary, and it can go out of date.

| Use | Model | Terms in brief |
|---|---|---|
| Stills | Z-Image-Turbo | Apache 2.0 |
| Voice | Kokoro-82M | Apache 2.0 |
| Timing | Whisper large-v3-turbo | MIT |
| Motion | LTX-2 | Community licence: free for an entity under $10M annual revenue, and a paid licence above that. It claims no rights in outputs, and has use restrictions |
| Music | MiniMax-Music3 | Community licence: a commercial product must display "MiniMax-Music3" prominently, needs written authorisation above $20M yearly revenue, and has an acceptable use policy |

## When it goes wrong

- **A clip comes back black.** The router refuses it. `providers/runners/ltx.py` carries the fix for the cause, so run clips through it rather than the package's own command.
- **Soft motion.** The package's own writer compresses frames to about 1.3 Mbps. The runner writes them losslessly.
- **Very heavy swap.** Another large program is running, or two jobs bypassed the lock. Stop one.
