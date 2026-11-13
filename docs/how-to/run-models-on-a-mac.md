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

Model ids are under `models.mac` in `config/studio.yaml`. A job asks for moving shots with `brief.max_video_beats`, which defaults to every shot on a moving-picture profile and to 3 on an audio-only one.

## Songs

Song engines need their own environment, because they pull in PyTorch. Set `models.mac.song` in `config/studio.yaml` to `heartmula` or `ace-step`, then:

```bash
export KALAINOVA_SONG_PYTHON=~/song-env/bin/python
export KALAINOVA_SONG_CHECKPOINT=~/song-models/heartmula   # or the ACE-Step project folder
```

ACE-Step's project ships an MLX backend for Apple silicon, so set `ACESTEP_LM_BACKEND=mlx` too. HeartMuLa runs on PyTorch's Metal backend. To split stems, install `audio-separator` in the model environment and list `mac` under `separate`.

### ACE-Step, as it ran

ACE-Step 1.5 ran through this path on an M-series Mac with 64 GB. The project needs Python 3.11 or 3.12, so make the environment with that, not the system Python:

```bash
uv venv --python 3.12 ~/song-env
uv pip install -p ~/song-env/bin/python /path/to/ACE-Step-1.5      # a clone of the project; about 1.4 GB
mkdir -p ~/song-models/ace-step                                    # models download here on the first run
export KALAINOVA_SONG_PYTHON=~/song-env/bin/python
export KALAINOVA_SONG_CHECKPOINT=~/song-models/ace-step
export ACESTEP_LM_BACKEND=mlx
```

Pin `{"song": ["mac"]}` in the job's `providers`, and set `song: ace-step` under `models.mac` in the config.

- **The first run downloads the models**, about 9.4 GB for the fast setting. The download counts against `deadlines_sec.song`, so raise it for that run (a run of three 100 s takes took 14 minutes with the download, and 83 s without it).
- **The fast setting** is the turbo model at 8 steps with no language model. For quality, set `ACESTEP_DIT=acestep-v15-sft`, `ACESTEP_STEPS=32` and `ACESTEP_LM_MODEL=acestep-5Hz-lm-1.7B` in the model environment. It downloads about 4.5 GB more and is slower.
- **`kalainova providers` says `mac` is ready for songs whether or not this environment exists.** A missing environment shows up when the job runs.
- A song with no lyrics must set `"instrumental": true`, and a section's `kind` must be one of the kinds in `schemas/song.schema.json`.

## What to expect

| Work | Measured |
|---|---|
| A still, about 1080p | 1.5 min |
| A voice line, with timing | 6 s |
| Music | About 2 min, for about 25 s of music |
| A moving shot at 1472x832 | About 6 s per frame, so 14 min for 6.4 s of picture, with a 48 GB memory peak |

Measured on an M-series Mac with 64 GB, later:

| Work | Measured |
|---|---|
| A 720x1280 still, Z-Image-Turbo, 9 steps | 33 s including the load, 25.8 GB peak |
| The same with `-q 8` | 44 s and the same peak, so leave it unquantized |
| A 100 s song with lyrics, ACE-Step turbo at 8 steps | About 28 s a take, and about 5 s of that is loading the model on each take |

ACE-Step's own MLX path is already on by default: the diffusion model and the VAE run natively on MLX, with no quantization and no CPU offload. Check the startup log for `[MLX-DiT] Native MLX DiT decoder initialized` and `[MLX-VAE]`, because a missing line means it fell back to the slower PyTorch path.

The music model can stop before the length it was asked for, usually after 20 to 30 seconds. The engine loops a short bed with crossfades, so listen for the repeat on anything longer.

- **One model at a time.** Each call takes a lock on the GPU, so jobs queue instead of fighting for memory. A deadline starts once a call holds the GPU, so time in the queue never counts against it, and a call that runs out is really stopped. Keep other large programs closed during motion.
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
| Songs | HeartMuLa | Apache 2.0, code and weights |
| Songs | ACE-Step 1.5 | MIT |

## When it goes wrong

- **A clip comes back black.** The router refuses it. `providers/runners/ltx.py` carries the fix for the cause, so run clips through it rather than the package's own command.
- **Soft motion.** The package's own writer compresses frames to about 1.3 Mbps. The runner writes them losslessly.
- **Very heavy swap.** Another large program is running, or two jobs bypassed the lock. Stop one.
