# How to compare models on one shot

A studio tests its cameras before a shoot. `kalainova bench` makes the same shot on each model you name, from the same start frame, prompt, and seeds, and lays the results side by side.

## Before you start

The shot needs a still to start from, so run the assets stage with moving shots switched off. That makes every still and no clip:

```json
"brief": {"max_video_beats": 0, "allow_stills": true}
```

The job needs a `cost_cap`. Each model must be listed under `video_models` in `config/studio.yaml`; a model that is not listed is refused, because the engine cannot tell how it takes its inputs.

## Run it

```bash
kalainova bench <job> <shot> --models model-a,model-b [--takes 2]
```

1. It prints the estimate for each model and the total. A model with no price row of its own is marked, because it is estimated at the generic video rate. A clip is estimated at the length the model bills, which is never shorter than the shot.
2. It refuses, before any call, when the total passes what is left under the cap.
3. It makes the takes. A failure on one model is reported and the others still run.
4. It writes `bench/<shot>.jpg` in the job's work folder, a row per take with frames across its length, and prints each take's motion reading, cost, and seed.

Each take is a normal take in `takes.json` with its model, seed, and cost. It is marked `bench`, so it never replaces the take a piece uses and does not count against the shot's take limits. `kalainova takes <job>` lists them.

## Judge each model

Look at the sheet and the clips, then give each take its own verdict:

```bash
kalainova verdict <job> accept|fix|reject --reviewer NAME --shot <shot> --take <n>
```

`kalainova signals` then reads each take's own readings against its verdict. To use a take in the piece, `kalainova take <job> <shot> <n>`.

## Limits

The motion reading says whether the clip moves, not whether it is good. Running the assets stage again with `--force` starts `takes.json` over, so judge and choose first. The sheet and clips stay on disk, and the ledger keeps every charge.

A shot that sings (`Sings:` in a song video's shot list) is benched on the models under `sing_models`: each gets the shot's still and the same line of the vocal stem, and with `judges.lipsync` set each take is also scored on how its lips follow that line (ADR 0025).

To see every request and its price first, with nothing sent: `kalainova rehearse <job> --bench <shot> --models model-a,model-b`. It rehearses the stills too, and checks each request against the model's published schema. A bench can run as soon as the shot's still exists, from the stills package alone; the shot's length then comes from its plan.

One model is enough to add a row to a bench already run: the sheet shows every bench take of the shot so far. A picture over a model's file limit (`max_image_bytes` in its `sing_models` row) is sent as a high-quality JPEG of the same size. A model that wants its prompt under another name, or takes none, says so with `prompt_param` (an empty value sends no prompt). A line shorter than the shortest a model takes (`min_audio_sec`) is padded with silence at its end, billed at the padded length, and the clip that comes back is cut to the line again. To compare lips and motion before paying for resolution, lay a lower `resolution` over a row's `extra`, and its price, in the private config for the bench, then remove it.
