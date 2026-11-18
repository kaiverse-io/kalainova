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
5. It writes the bench report beside it (see below): `bench/<shot>.mp4`, every take side by side under a strip naming each panel's take and model, and `bench/<shot>.report.md`, a table of every reading with the engine's pick and the reason for it.

A row already made, the same model with the same prompt, is refused before any call, because it would buy the same test twice. Ask for another take of it with `--again`.

Each take is a normal take in `takes.json` with its model, seed, and cost. It is marked `bench`, so it never replaces the take a piece uses and does not count against the shot's take limits. `kalainova takes <job>` lists them.

## What the engine reads, and what it picks

Every take is read by the judges set in config. A sung take is judged on how its lips follow its line (`judges.lipsync`). A take with a character in it is judged on how the person moves (`judges.performance`): how far the head turns, nods, and tilts, how much the eyes travel and how open they are, and how much the person moves once the camera's movement is taken out, apart from the rest of the frame. A whole-frame motion number cannot tell a still person in a moving crowd from a moving person in a still room, so it is not used to judge a performance.

The readings named under `rank` in config, by capability, order the takes. Each is scaled within the takes compared, so the rule says only which of these takes reads best, never whether a take passes a fixed mark, and it carries from a quiet close-up to a loud wide shot. The report names the pick and its place on each ranking reading. It does not pick:

- a take that missed its floor, or that a ranking judge did not read (it is listed with the reason);
- a character take made under the profile's `character_source_min_px` (it is ranked, and the pick is the best take made at size);
- between two takes closer than `rank.close`: it says a person decides.

A repainted row also reads how much of the mouth's movement the repaint kept (`repaint_mouth_kept`), the redrawn mouth's spread over the clip it redrew. A model known to make a character shot under the size floor, from `short_side` on its `sing_models` row or from a take it made before, is said before any spend.

To read a bench again at no cost, with judges added since, or to show some takes in a chosen order:

```bash
kalainova bench-report <job> <shot> [--only 5,7,10] [--again]
```

`--again` runs every judge afresh; without it, only what a take was not yet read by.

## Judge each model

Look at the report and the clips, then give each take its own verdict, or say which you prefer and on what:

```bash
kalainova verdict <job> accept|fix|reject --reviewer NAME --shot <shot> --take <n>
kalainova verdict <job> accept --reviewer NAME --shot <shot> --best <n> --among 5,7,10 --aspect lips
```

`--best` records a preference of that take over each of the others. `--aspect` says what it is about (`review_aspects` in config: overall, lips, head, eyes, body, picture, sound), so each judge is held to what was said of its own aspect. `kalainova signals` reads each take's readings against its verdict; `kalainova agreement` reads them against the preferences, aspect by aspect, with the engine's own picks among them. A reading joins `rank` only once it follows the preferences on enough varied shots. To use a take in the piece, `kalainova take <job> <shot> <n>`.

## Limits

The motion reading says whether the clip moves, not whether it is good. Running the assets stage again with `--force` starts `takes.json` over, so judge and choose first. The sheet and clips stay on disk, and the ledger keeps every charge.

A shot that sings (`Sings:` in a song video's shot list) is benched on the models under `sing_models`: each gets the shot's still and the same line of the vocal stem, and with `judges.lipsync` set each take is also scored on how its lips follow that line (ADR 0025).

To see every request and its price first, with nothing sent: `kalainova rehearse <job> --bench <shot> --models model-a,model-b [--again]`. It rehearses the stills first only when the shot has no still or no length yet, and checks each request against the model's published schema. A bench can run as soon as the shot's still exists, from the stills package alone; the shot's length then comes from its plan.

One model is enough to add a row to a bench already run: the sheet shows every bench take of the shot so far. A picture over a model's file limit (`max_image_bytes` in its `sing_models` row) is sent as a high-quality JPEG of the same size. A model that wants its prompt under another name, or takes none, says so with `prompt_param` (an empty value sends no prompt). A line shorter than the shortest a model takes (`min_audio_sec`) is padded with silence at its end, billed at the padded length, and the clip that comes back is cut to the line again. A sung shot can also be benched as two models joined by `+`, such as `--models <video model>+<lipsync model>`: the first makes the shot as a plain clip from the still and the kit, and the second redraws its mouth to the line. The take carries both calls' cost and is judged against the same line, so a picture model that cannot hear the song is compared fairly with the ones that sing in one call. It is a comparison only: a piece's singing shots are still sung in one call (ADR 0025). To compare lips and motion before paying for resolution, lay a lower `resolution` over a row's `extra`, and its price, in the private config for the bench, then remove it.
