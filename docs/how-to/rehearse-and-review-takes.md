# How to rehearse a paid run, and review its takes

Two steps sit either side of the money. A rehearsal shows every request a rented model would be sent, and its price, before anything is spent. The review page shows every take that came back, side by side, so you judge it by eye before it goes into the cut.

## Rehearse

```bash
uv run kalainova rehearse <job>
```

The job is copied to a throwaway folder that sees the same kits and streams, and its stills and moving shots run there. Each rented model's adapter writes down what it would send instead of sending it. Files it would upload are named by their hash, not sent. A stand-in file of the shape it asked for comes back, so the rest of the line runs. Nothing reaches a vendor, nothing is charged, and no key is needed.

It prints one line per paid request: the model, the estimate, and the fields it would send. For each moving shot, it says whether the start frame and the end frame went with the request. Then it prints the total against what is left under the job's cap. The full record is `rehearsal.json` in the job's work folder. Check its fields against each model's live schema, which is free and needs no key:

```bash
uv run python scripts/check_fal_schemas.py --rehearsal <work>/<job>/rehearsal.json
```

It names any field a model's schema does not list, and any field the schema requires that the request leaves out.

What it cannot tell you:

- How a model will read the request. Stand-ins are test patterns.
- What a vendor charges beyond its listed price. The estimate is the price table's.
- Anything about a provider that cannot rehearse. Only `fal` can today. Any other paid provider stops the rehearsal before it is called, and the report says where.

The animatic gate is passed in the copy only, so the rehearsal can reach the moving shots. The real run still makes no video until you accept the animatic (see [How to watch a rough cut](watch-a-rough-cut.md)).

## Review the takes

```bash
uv run kalainova review <job>
```

This writes `review.html` next to the takes in the job's work folder. Open it in a browser. It shows:

- the kit's faces;
- each moving shot's start frame;
- every take of that shot, with its model, seed, cost, the size the model made it, and what its readings flag.

A reading can flag four things:

- A clip that could not be read.
- A character shot made smaller than the profile's `character_source_min_px`.
- A clip that missed its motion reading.
- A take that was not given its start frame.

Under each shot is the list of what only a person can see: hands, objects that melt or multiply, morphing, warped text, light that doesn't match, and, for a shot with a character, a face that drifts from the kit.

Each take shows the command that records your verdict on it, and the command that puts it in the cut:

```bash
uv run kalainova verdict <job> accept --reviewer <your name> --shot <shot> --take <n>
uv run kalainova take <job> <shot> <n>
```

A take you choose stands, even one a reading flagged. The page changes nothing and spends nothing.
