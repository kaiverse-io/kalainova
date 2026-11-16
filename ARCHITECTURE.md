# Kalainova Architecture

Kalainova is one engine and many jobs. A job declares a **strategy** and one or more **media** kinds. It does not declare a segment. The engine owns the job record, the gates, and the measure of acceptance. It rents the models, and it can run outside production tools behind one contract.

In the diagrams, green is built, amber is partly built, and grey is planned. A planned part is a decision, not a claim that it exists.

## Executive Summary

One public engine and many private jobs. Rented models make the bytes; the engine owns the record, the gates, and the compile path. Two decisions shape the rest: a human approves every piece against its exact bytes (ADR 0007), and anything that must stay the same lives in a frozen kit that every model call must carry (ADR 0009).

## System Overview

The system context below is the runtime view.

## System context

Who and what the engine touches.

```
 Operator: brief, review, approve ──brief, approval─────────▶ ┌────────────────────┐
 Operator ◀───────────────────────file, contact sheet──────── │                    │
 Coding agent: builds and runs jobs ──plans, stages─────────▶ │                    │
 Free-license stock sources ──licensed footage──────────────▶ │  Kalainova engine  │
 Rented model providers ◀─────────requests within budget───── │                    │
   image, video, voice, music, LLM ──files, cost────────────▶ │  job record,       │
 Outside production tools ◀ ─ ─ ─ ─job bundle─ ─ ─ ─ ─ ─ ─ ─  │  gates, render     │
   planned, run in containers ─ ─ files, record ─ ─ ─ ─ ─ ─ ▶ │                    │
 Publishing platforms ◀───────────approved bytes only──────── │                    │
   official APIs or an aggregator ──48 h metrics────────────▶ └────────────────────┘

 ── built    ─ ─ planned
```

An agent never writes an approval (ADR 0007). A human approves every piece.

## Layer view

Dependencies point down. A lower layer never imports an upper one, and a producer or model can be replaced without changing the control layer.

```
 ┌─ Control layer: owned ─────────────────────────────────────────────────────────┐
 │ Job contract: brief, rights, budget   [built]                                  │
 │   ▶ Producer selection                [planned]                                │
 │   ▶ Intake of outside files           [built]                                  │
 │   ▶ QA                                [partial]                                │
 │   ▶ Human gate: hash-bound approval   [partial]                                │
 │   ▶ Publish                           [built]                                  │
 │   ▶ Acceptance and measure            [partial]                                │
 └────────────────────────────────────────────────────────────────────────────────┘
                                          │
                                          ▼
 ┌─ Producers: swappable ─────────────────────────────────────────────────────────┐
 │ Generated video [partial] · Footage edit [partial] · Explainers [planned]      │
 │ Songs [partial] · Comics and books [partial]                                   │
 └────────────────────────────────────────────────────────────────────────────────┘
                     │                                         │
                     ▼                                         ▼
 ┌─ Shared media tools: owned ──────────┐  ┌─ Model access: rented ───────────────┐
 │ ffmpeg compile and render    [built] │  │ Router: budget, deadline,            │
 │ Word timing and captions   [partial] │  │ next listed provider, reuse  [built] │
 │ Audio mix and loudness       [built] │  │ Provider adapters            [built] │
 └──────────────────────────────────────┘  └──────────────────────────────────────┘

 The control layer, the producers and model access all read and write the job folder:
 its record, ledger and stamps [built].
```

## Component view: the engine today

The modules in `src/kalainova/`, and the two paths that make a piece. Every model call goes through `providers/router.py`.

```
 __main__.py, the CLI
   │
   ├─▶ Generated path
   │     plan.py, research.py ─▶ assets.py ─▶ shotmake.py, takes.py, shots.py ─▶ edit.py ───┐
   ├─▶ Footage path                                                                         │
   │     stock.py ─▶ editor/analyze.py (shots, scores) ─▶ editor/direct.py (choose, patch) ─┤
   │     editor/notes.py, beats.py, speech.py, clips.py, auto_editor.py ─▶ editor/direct.py │
   ├─▶ Songs and documents                                                                  │
   │     writers.py ─▶ songs.py ────────────────────────────────────────────────────────────┤
   │     writers.py ─▶ comic.py · writers.py ─▶ story.py, bookpdf.py                        │
   ├─▶ Before and after a spend                                                             │
   │     rehearse.py: a dry run of the paid stage · reviewpage.py: every take on one page   │
   │                                                                                        ▼
   └─▶ Shared finish
         render/ (closed op list, step cache) ─▶ captions.py
         render/ ─▶ qa.py, qachecks.py, kitchecks.py ─▶ publish/ (approve, publish, measure)
         qa ─▶ timeline.py (shot sheet, cut check) · qa ─▶ provenance.py, verdicts.py
         After the cut: render/ ─▶ nle.py ─▶ nle_otio.py ─▶ opentools.py · render/ ─▶ dub.py

 Model access (ADR 0023)
   plan, assets, shotmake, direct, qa, songs, dub ─▶ providers/router.py, with a request from
     providers/contract.py (typed requests, Result, Context, Receipt, Inputs, the errors)
   providers/base.py: the port and the registry, which every adapter implements:
     remote.py, fal.py, search.py, spaces.py, compat.py (rented, each through a transport) ·
     mac.py (open models on this machine) · local.py (placeholders)
   providers/transport.py: send, upload, fetch, receipt, labels, errors, for every rented vendor ·
     rehearsal.py (requests written down under the router's attempt, none sent)

 Foundation
   router, render, publish ─▶ jobfs.py (job folder and ledger) ─▶ schemas/
   router ─▶ config.py (config/studio.yaml) · render ─▶ media.py, mediascan.py (ffmpeg,
   ffprobe) · render ─▶ bar/
```

## Component view: model access

What happens on one model call. The engine depends on the contract, never on a vendor: it asks with
a typed request (`providers/contract.py`), and only `providers/` imports an adapter or a transport
(the `vendors-stay-behind-the-port` import contract).

```
 Engine stage
   ▼
 Listed providers: the job's list, else the studio's
   ▼
 Same paid file already saved? ──yes──▶ reuse it with no charge
   │ no
   ▼
 Rehearsal open, and the first listed provider, key or not, costs money and cannot rehearse? ──yes──▶ stop
   │ no
   ▼
 Paid, and spend is stopped in this studio (gates)? ──yes──▶ refuse, nothing reserved
   │ no
   ▼
 Priced, or the job has no cap? ──no──▶ next listed provider
   │ yes
   ▼
 Reserve the estimate on the ledger ──over the cap──▶ stop the job
   │ within the cap
   ▼
 Call with a deadline, to a temporary path, with this attempt's Context and Receipt
   │   (in a rehearsal the transport writes the request down and fetches a stand-in file)
   ├── malformed request (422) ───────────▶ release the reservation, stop: the mapping is at fault
   ├── failed, nothing billed ────────────▶ release the reservation ─────────────▶ next listed provider
   ├── timed out, or billed then failed ──▶ settle at the estimate or the billed amount ─▶ next listed
   └── file returned
         ▼
       File matches the request? ──no──▶ settle, discard ──▶ next listed provider
         │ yes
         ▼
       Move to the destination, record it, settle at the real cost

 next listed provider: another one ──▶ back to "Priced?" · none left ──▶ the job fails, naming each reason
```

A pinned model goes to the provider the pin names and to no other. A bug in an adapter is raised and does not count as a provider failure. Only listed providers are tried. `local` is listed in `config/studio.yaml`, so a run with no keys still works, and `approve` refuses what it makes.

### Where a call and its cost are written down

Every model call leaves three records in the job folder, joined by one attempt id (`providers/records.py` writes them; the router hands it each call). Each carries the
labels of where it came from, so a fault or a cost maps to one part of the line:

```
 labels, set once where the work is run
   run_id  one engine command (trace.RUN_ID)
   stage   the command, or each stage of `make` (__main__)
   shot    each beat of the assets stage, and a retake (assets, shotmake: trace.relabel)
       │
       ▼
 router.generate ── attempt id ──┬──▶ trace.jsonl       every attempt, ok or not: model asked or used,
                                 │                      outcome, estimate, settled, billed units,
                                 │                      vendor request id, vendor error text, engine
                                 ├──▶ ledger.json       every charge: cost, when, model, request id
                                 └──▶ generations.jsonl every kept file: its sha256, model, request id
       │
       ▼
 kalainova ledger <job>   money by provider, model, stage and shot; every attempt; any charge with
                          no trace row; --invoice records the vendor's figure against the estimate
 kalainova scorecards     latency, spend and failures per model, across jobs, from the same rows
```

The vendor's request id is what its bill and dashboard list, so a charge can be checked against the
vendor's own record. `engine` is the commit that ran the call, marked `+dirty` when tracked files had
changed, since a job's fingerprint is taken when it is opened and later stages can run newer code.
A failed call that nothing billed leaves no ledger entry; its trace row says so.

**What a call costs is checked, not trusted** (`providers/prices.py`).

- **The estimate.** An estimate, and so the reservation against the cap, is the price table's figure times a correction: the highest of 1, the vendor's list price over the table's rate, and the most a recent bill exceeded its table figure.
  - The list price comes from fal's pricing API, read at most once a day. It counts only when units match and the row gives no reviewed reason (`checked:`).
  - The bills come from `prices.learned.jsonl` beside the studio.
  - A correction never lowers an estimate.
- **The charge.** After the call, fal's `X-Fal-Billable-Units` times the account's unit price is the vendor's figure. The ledger settles at the higher of it and the table's (`records.settle_at_vendor`), keeps both, and learns the ratio; a drift past 10% is printed.
- **The labels.** fal gets our labels on each request (`X-Fal-Tags`: job, attempt, run, stage, shot), so its own usage report breaks down the same way.
- **The checks.** `scripts/check_fal_prices.py` compares every configured model's row with fal's list price and fails on an unexplained drift. `kalainova rehearse` checks every request against the model's live schema without being asked.

`providers/check.py` is not on that path. `kalainova providers --check --spend` calls it by hand: it sends one smallest call per capability through `router.generate` under a job's cost cap, so the ledger records it, and reports reached, schema matched, and charge against estimate. It refuses under automation and never runs in CI or the tests.

## Sequence: one piece

```
 Operator ──brief, rights, budget──▶ Engine ──▶ job folder: job.json, script_packet.json
 for each asset:
   Engine ──request──▶ Router ──check the cap and the saved files──▶ job folder
                       Router ──call with a deadline──▶ Provider ──file and cost──▶ Router
                       Router ──record the file, charge the ledger──▶ job folder
                       Router ──checked file──▶ Engine
 Engine: edit, compile, render final.mp4 ──▶ job folder: render_stamp.json
 Engine ──run the checks──▶ QA ──▶ job folder: qa.json with the file hash
 Engine ──file and contact sheet──▶ Operator
 accepted:
   Operator ──approve──▶ Engine ──check QA, placeholders and stamp──▶ job folder: approval.json
   Engine ──approved bytes, AI label on──▶ Platform ──48 h metrics──▶ Engine ──▶ measure.json
 sent back:
   Operator ──reason──▶ Engine ──regenerate what was named──▶ Router
```

## Job states

```
 draft ──make or edit──▶ rendered ──human approve──▶ approved ──publish──▶ published
   │                      │    ▲                       │                     │
   │                      └────┘ re-render             │                48 h metrics
   │                      │                            │                     ▼
   └──────────────────────┴───────▶ killed ◀───────────┘                 measured
```

`scripts/check.py` also allows `rented` and `accepted`, for work finished in a rented tool.

## Deployment view

The engine runs on one machine. Anything from a third party runs in a container that sees only the folders mounted into it.

```
 ┌─ Operator machine ───────────────────────────────────────────────────────────────┐
 │ Repo and job folders ──mounted──▶ Engine container      (container runtime)      │
 │ Engine container ──▶ media output, outside git                                   │
 │ Media output ─ ─mounted read-only─ ─▶ third-party producer, one container        │
 │                                       each, in the runtime   [planned]           │
 └──────────────────────────────────────────────────────────────────────────────────┘
 Repo ──push──▶ GitHub Actions: check, eval, lint, test
 Engine container ──HTTPS──▶ hosted model APIs
 Engine container ─ ─▶ a rented GPU endpoint                         [planned]
 Engine container ─ ─job bundle─ ─▶ a rented GPU running a whole producer [planned]
```

## Adding a rented GPU

Three different shapes, with different costs. None of them changes a stage of the engine.

```
 Rented GPU
   ├─▶ serves one model over HTTP ──▶ a provider adapter and a config entry        [built]
   ├─▶ runs a whole production tool ──▶ a container runner and file transfer        [planned]
   └─▶ billed by the hour ──▶ measured cost per job and an infrastructure entry     [planned]
```

## The stable interfaces

These change only with a version bump. A new interface waits for a second real use, so storage and queues stay plain for now.

| Interface | In | Out | State |
|---|---|---|---|
| **Provider** | Request, deadline, and budget, through the router | File, cost, model, provenance | Built, including songs, lip sync, stem separation, graphics, and search. Each adapter is tested against a faked vendor, not a live one. Requests are not typed. |
| **Producer** | Job bundle in a mounted folder | Files and a record, through `kalainova intake` | Partial. Intake is built. Tools run by a coding agent still need a container wrapper, and their output varies between runs. |
| **QA check** | Any file and its format | Pass or fail, with evidence | Partial. Files the engine did not render get technical checks only, and checks are not plug-ins yet. |

## Standing rules

- **No implicit fallback.** Only listed providers are tried.
- **No unpriced spending.** A job with a cap refuses a call it cannot estimate.
- **Every paid result is saved at once.** A restart reuses it.
- **Approval binds four things:** the bytes QA checked, the master they came with, the asset record they were rendered from, and a human reviewer.
- **A promise of motion is kept or refused.** A shot that asked to move does not quietly become a still (ADR 0013).
- **A fact states its source.** A finding reaches a script only when its quote is found in a saved copy of its source (ADR 0015).
- **A tool's own report is not proof.** Outside tools get their own API keys, so their costs can be checked against vendor invoices.
- **A model library is an implementation, not the interface.** It stays behind the provider contract with its own retries off or counted.

## Known gaps

| Gap | Effect |
|---|---|
| No publisher takes audio-only files | A song can be approved but not posted |
| No content review on files from outside tools | A human is the only check on their content |
| Nothing added since ADR 0012 has run on a real model | Every line of `docs/studio-goal.md` is Built, none is Run or Accepted. Faked models prove the wiring, not the result |
| Vendor slugs marked `VERIFY` in `config/studio.yaml` are unconfirmed | An adapter may need its model name or a field changed on its first real call |
| No container runner for outside tools | The contract exists, and nothing uses it in production yet |
| The ledger's lock holds on one machine | Parallel calls cannot overshoot here, but two machines could, until Postgres holds the ledger (ADR 0010) |
| Files from outside tools carry no enforced references | A human compares them against the kit |
| A kit cannot prove a face is not a real person's | A human attests at freeze and approves each piece; the vision judge is one more signal |
| Rendered files and job records are on one machine | Only kit files can reach object storage today (ADR 0010) |
| QA does not predict the operator's verdict | A file can pass QA and the bar and still be rejected on review. The bar measures craft defects, not taste |
| A printed book has no ligatures | Reading is unaffected, and the page images and the PDF measure the same widths. "fi" and "Th" print as separate letters |
| No publisher takes a comic or a book | They can be approved but not posted |
| Stereo only | No 5.1 or 7.1 mix, and an upmix from stereo is not an honest substitute |
| SDR only | No HDR master |

## Kits, streams, and jobs

Three objects carry continuity. The kit says what is fixed, and the stream says where it goes. The job locks exact versions, so a later kit change never moves a piece already made.

```
 Kit, frozen version: face, voice, persona, style [built] ──▶ Stream: identity, generators, limits [built]
 Canon, append-only [built] ─────────────────────────────────▶ Stream
 Operator ──stream + brief──▶ request ◀── Stream
 request ──▶ Can the pinned tools hold the kits? ──no──▶ stop before spending
               │ yes
               ▼
             Job + kit.lock.json [built]
               ├─▶ plan: persona and canon ──▶ assets
               └─▶ assets: references, voice, music ◀── blob store, content-addressed [built]
                     ▼
                   QA: the record, then the frames ──▶ human gate
```

## Cloud path

Today one machine runs the engine, with kit files optionally in private object storage. Phases 2 and 3 are proposed in ADR 0010, and none of it is built.

```
 ┌─ Private data plane ───────────────────────────────────────────┐
 │ Postgres: queue, ledger, index                 [planned]       │
 │ Object storage, SSE-KMS: kit files, renders    [partial]       │
 │ Secret manager                                 [planned]       │
 └────────────────────────────────────────────────────────────────┘
 ┌─ Stateless compute ────────────────────────────────────────────┐
 │ Review API, authenticated                      [planned]       │
 │ Worker: one job, one container, ffmpeg, CPU    [planned]       │
 └────────────────────────────────────────────────────────────────┘
 Review API ──▶ Postgres
 Worker ──claim with SKIP LOCKED──▶ Postgres
 Worker ◀──bundles, bytes──▶ object storage
 Worker ──▶ secret manager
 Worker ──▶ rented models over HTTPS
```

## Component Diagram

Static view of top-level modules, an arrow wherever one imports another. `just ci-arch` checks that every component has a box here.

```
 __main__ ──▶ studio_cli ──▶ streams ──▶ consistency ──▶ kits ──▶ blobstore
    │            └─▶ lookdev ─▶ kits, kitrules, timeline, providers
    │                                       │  │          │
    │                                       │  └─▶ kitrules ◀── scripts/check.py
    │                                       └─▶ providers
    ├─▶ trace: labels each command's stage (and each stage of make)
    ├─▶ production_cli ──▶ dub, nle, provenance, qa, research, shotmake, shots,
    │                      songs, takes, timeline, verdicts, editor, config, bench,
    │                      assets, preproduction
    ├─▶ plan ──────▶ consistency, prompts, providers, shots
    ├─▶ research ──▶ plan, prompts, providers, config
    ├─▶ writers ───▶ consistency, plan, prompts, providers
    ├─▶ songs ─────▶ bar, captions, config, editor, media, providers, render, takes, writers
    ├─▶ assets ────▶ consistency, media, preproduction, shotmake, shots, soundbed, takes,
    │                trace, config, providers
    ├─▶ preproduction ▶ media, motion, shotmake, takes, timeline, providers
    ├─▶ soundbed ──▶ blobstore, kits, media, shotmake
    ├─▶ shotmake ──▶ blobstore, consistency, media, shots, takes, trace, config, providers
    ├─▶ takes ─────▶ bar, blobstore, media, config
    ├─▶ bench ─────▶ consistency, shotmake, shots, takes, timeline, config, providers
    ├─▶ rehearse ──▶ assets, preproduction, takes, providers
    ├─▶ reviewpage ▶ consistency, kits, takes
    ├─▶ gates ─────▶ jobfs: what must be true before a paid call (router asks it first)
    ├─▶ shots ─────▶ config
    ├─▶ edit ──────▶ config
    ├─▶ render ────▶ bar, captions, look, motion, media, mediascan
    ├─▶ qa ────────▶ bar, comic, story, songs, research, timeline, qachecks, plan, prompts,
    │                media, stock, config, providers, publish
    ├─▶ qachecks ──▶ bar, consistency, kitchecks, plan, prompts, shots, timeline, config,
    │                providers, publish
    ├─▶ kitchecks ─▶ consistency, kits
    ├─▶ timeline ──▶ bar, captions, media
    ├─▶ bar ───────▶ media, mediascan, editor, config
    ├─▶ mediascan ─▶ media
    ├─▶ comic ─────▶ captions, consistency, render, shotmake, providers
    ├─▶ story ─────▶ bookpdf, comic, captions, render, providers
    ├─▶ bookpdf: fonts and PDF drawing, no engine imports
    ├─▶ dub ───────▶ captions, media, plan, prompts, render, config, providers
    ├─▶ nle ───────▶ nle_otio, config
    ├─▶ nle_otio ──▶ opentools, config
    ├─▶ opentools ─▶ jobfs: runs an open tool as a command, imported by each adapter
    ├─▶ provenance ▶ blobstore, takes, trace, verdicts, config
    ├─▶ verdicts ──▶ bar, media, jobfs
    ├─▶ publish ───▶ blobstore, consistency, preproduction, streams, stock
    ├─▶ editor ────▶ edit, media, plan, prompts, stock, config, providers
    ├─▶ song_repair ─▶ config, media, jobfs, takes, bar, providers, songs
    ├─▶ intake ────▶ media, render
    ├─▶ variants ──▶ jobfs
    ├─▶ templates ─▶ jobfs
    ├─▶ stock
    ├─▶ router ─────▶ gates, trace ─▶ fingerprint: gates first; every call's labels, attempt, commit
    ├─▶ fingerprint ─▶ jobfs
    ├─▶ host ────────▶ config
    ├─▶ scorecard ───▶ jobfs
    ├─▶ audit ───────▶ config
    ├─▶ calibration
    ├─▶ sound_identity
    ├─▶ prompts, captions, look, motion, media: imported throughout, and import no stage
    └─▶ jobfs, config: the foundation, imported throughout
```

## Components

### __main__
The command line. Parses arguments and calls a stage. Holds no rules.

### studio_cli
Commands for kits, streams, canon, schedules, requests, and the look sheet.

### production_cli
Commands for making and judging a piece shot by shot, songs, research, and everything after a cut: takes, retakes, the shot sheet, timeline export, clips, dubbing, verdicts, provenance, and the ledger.

### kitrules
What makes a kit legal. Stdlib only, shared by the engine and `scripts/check.py`.

### kits
Kit lifecycle: draft, add a file, freeze, bump, load, and verify stored bytes.

### blobstore
Local cache plus optional S3-compatible durable copy, addressed by hash.

### variants
Opening variants clone a parent's edit and asset manifests into a child job, share its source files,
and change only the opening shot or hook card.

### templates
`fill_template` turns a template (brief, claims, cards, each with `{field}` placeholders) and a
data file into a new job: refuses stale data, hydrates every placeholder, and writes `job.json`
and `script_packet.json` with each claim's source carried through.

## Trace
Best-effort per-provider-call telemetry in each job's `trace.jsonl`, including timing, outcome,
provider/model identity, and estimated and settled cost. The provider router writes rows without
letting telemetry failures interrupt generation. Each row carries the attempt id that its ledger
entry and generation record also carry, the vendor's request id and error text, the billed units,
the engine commit, and the labels of where it ran: run, stage and shot (`labelled`, `relabel`,
`scoped`). See "Where a call and its cost are written down" above.

### streams
Stream records, canon, the schedule packet, and `request`, which turns a stream and a brief into a locked job.

### consistency
Resolves a stream's kits, builds and verifies the lock, applies the fixed things to each shot and script, and holds `RULES`, the table of how each is enforced.

### prompts
Loads versioned prompts from `prompts/`.

### plan
Intent to script. Loads the kits' persona and canon for a stream job, and only verified findings for a job with research.

### research
Sources, a private saved copy of each, and findings whose quotes are checked against those copies. A model can suggest a fact, and only a found quote lets it into a script (ADR 0015).

### writers
A brief to the script a song, a comic, or a book is made from, each held to its own schema.

### shots
What a shot says, kept apart: the still prompt, the motion prompt, continuity shared across shots, and a review of the plan before any money is spent.

### takes
Attempts at one shot, each with its own seed and readings. Passing is a floor, not a ranking: among takes that pass, the first is kept; a clip that cannot be read is unmeasurable, never a pass; each reading records the size the model made. `held_to` adds a profile's `character_source_min_px`, so a character shot made smaller does not pass. A person's choice stands (ADR 0013).

### bench
A camera test: one shot made on several models from the same start frame, prompt, and seeds. It prints each model's estimate, refuses before any call when the total passes the job's cap, and makes takes marked `bench` through the router and the take store, so each carries its model, seed, and cost. It writes one sheet with a row per take. Depends on `consistency`, `shotmake`, `shots`, `takes`, `timeline`, `config`, and `providers`.

```
 shot + models --> estimate per model --> over the cap? --> refuse, no call
                                              | no
                                              v
        router --> takes.attempt (bench) --> takes.json --> timeline.bench_sheet
```

### rehearse
A dry run of a job's paid stage. The job is copied to a throwaway folder that sees the same kits and streams through links, and its stills and moving shots run there with a rehearsal open (`providers/rehearsal.py`). Each request a rented model would be sent is written down with its fields, the files it would upload named by hash, the engine's own request, its content key, its stage (`stills` or `motion`), the router's estimate and the adapter's price; stand-in files of the shape the engine asked for let the line go on. Each request is checked against its vendor's published schema through its own adapter (`Provider.problems`). The first listed provider for each request must be able to rehearse, key or not: a paid one that cannot stops it, because the real run would call it once its key is set. A request is paired with the router's call by the attempt id, so a download under another suffix (fal's audio) and a call that returns only text are both accounted for. The animatic gate is passed in the copy only, and the report says the real run still waits there. Nothing is sent, nothing is spent, and no key is needed; the real job gets only `rehearsal.json` in its work folder, which `scripts/check_fal_schemas.py --rehearsal` checks against each model's live schema. Depends on `assets`, `preproduction`, `takes`, and `providers`.

```
 job ──copy──▶ throwaway job (kits, streams linked read only)
                   │  rehearsal open: each transport writes requests down, paid others refuse
                   ▼
   assets (animatic stills) ──▶ assets (moving shots) ──▶ stand-in files
                   │
                   ▼
   rehearsal.json in the real job's work: requests, fields, estimates, gate, where it stopped
```

### gates
What must be true before money leaves (ADR 0022, proposed). The router asks it before reserving any paid call, and a gate that fails or cannot be read refuses; it never lets the call through. Free providers and rehearsals pass. Built so far: the kill switch. While `<studio>/STOP` exists, every paid call refuses; `kalainova stop --by NAME` and `kalainova resume --by NAME` write and remove it, and log it in `<studio>/gates.log.jsonl`. To come: studio-wide limits, signed packages, and a spend broker that alone holds the vendor key. Depends on `jobfs`.

### reviewpage
One local page to judge a piece's takes by eye: the kit's faces, each moving shot's start frame, and every take side by side with its model, seed, cost, size and what its readings flag (unread, under the source size, missed motion, no start frame). Under each shot it lists the faults only a person can see (hands, melting objects, morphing, warped text, face drift) and the `verdict` and `take` commands to record a decision. It writes `review.html` next to the takes and changes nothing else. Depends on `consistency`, `kits`, and `takes`.

### shotmake
One shot from start to finish: where it starts, its takes, a retake, its lip sync, and the sound of its place. A first run and a retake share this code, so they keep the same promise and the same record. A retake is refused past the take limits (`takes.check_retake`), and with no note it reads that shot's finding from `findings.json`.

### preproduction
The rough cut before the money, and the gate on it. The assets stage, run with `animatic`, makes the voice and one still per shot and asks for no video. This module prices each moving shot (`moving_quotes`, per shot, at the length asked for), draws the stills under a camera move with the words and the voice into `animatic.mp4` stamped ANIMATIC, and writes `animatic.json`. `require_review` is the gate: with `brief.animatic_gate` set, or by default for a capped job whose video is paid for, the assets stage refuses before any spend unless the job's `animatic_reviewed` is an `accept` for the cut that exists now. Accepting records each still's hash, and a shot whose still changed after that refuses. The model check (`still_judge_refusal`, `prompts/qa_still.md`, the `judge` model) looks at each moving shot's still while the animatic is made and advises the person through `findings.json` and the animatic's printout (`judge_lines`); it blocks nothing there. In the paid run a still the person accepted is not judged again (`still_was_accepted`); with no accepted animatic, a still the check flags is not sent for motion. `publish` refuses an animatic by name and by hash. Depends on `config`, `media`, `motion`, `prompts`, `shotmake`, `takes`, `timeline`, and `providers`.

```
 assets(animatic) ─▶ voice + stills ─▶ made{timeline, shots, quotes}
                                           │
        preproduction.render ──▶ animatic.mp4        preproduction.write_record ──▶ animatic.json
                                                                   │
 verdict --animatic ──▶ job.animatic_reviewed ◀── sha of the cut ──┘
                              │
 assets(full) ─▶ require_review ─▶ refuses, or goes on to pay for video
```

### lookdev
Look development: a sheet of a kit's candidate references, each at three framings (crops of what was given), and optionally one test still per look through the router, under a cap, on a model that takes references. It reads a kit's draft or latest frozen version and changes no kit. A person picks, and a person freezes. Depends on `kits`, `kitrules`, `timeline`, and `providers`.

### assets
Script to files. Every shot of a stream job carries its references and pinned model.

### soundbed
The sound under a piece: a kit's fixed file, a finished track from another job, or a bed made for it.

### edit
Assets to an edit manifest.

### render
Edit manifest to a closed op list, then to the file through ffmpeg. A plan can be written by a model, so `spec` checks every argument and path first. `cache` keeps a step whose inputs and settings have not changed, so changing one shot re-encodes only what it touches.

Kinetic captions (`brief.captions: kinetic`) take a different route inside `burn_captions`: `drawn` writes a transparent HyperFrames page from the same word timings, renders it alone to a WebM with alpha, and lays it over the graded picture with ffmpeg, so the grade path is untouched. The page keeps its type inside the profile's `safe_zone`, and the boxes it placed go to `captions.drawn.json` for the QA warning. `drawn` also writes the title, quote and stat card compositions (`kalainova card`). Film profiles never reach it: they burn nothing.

The export step picks the cover (`cover`): the sharpest clean frame across the piece, clear of the fades, or the time or file a brief names, plus a square cut around the most detailed part.

Picture steps hand each other lossless 10-bit masters, so nothing degrades between steps. The cost is hundreds of megabits a second, gigabytes for a short piece. The title pass is skipped when there is nothing to burn in, rather than writing a second copy. `cache.clean` (`kalainova clean`) deletes the picture intermediates a plan wrote, and nothing else: the final, assets, takes, and sound stems stay, and the next render remakes what was deleted.

```
edit_manifest ─▶ compile_plan ─▶ render_plan.json ─▶ execute
                                                       │  for each step:
                                                       │  spec.coerce ─▶ cache.unchanged? ─▶ keep
                                                       ▼                        │ no
             picture: still, cut, scale, concat, titles, captions ◀─────────────┤
             sound:   voice, music, places, effects, loudness     ◀─────────────┤
             export:  web file, master, thumbnail                 ◀─────────────┘
```

### songs
Lyrics to takes of a song, readings that pick among them, a master, lyric files, release files for a distributor (`render/release.py`: WAV, FLAC and MP3 with tags, cover and lyrics), optional stems through a `separate` provider, a refusal before spending when a song asks for more than the model states it can make (`router.refuse_too_long`), and a job that cuts a video to the finished track (ADR 0014).

### song_repair
Repaints a single section of a chosen song take into a new take beside it, without re-rolling the whole track. The first ready song provider that can repaint does it (on the Mac, ACE-Step's `repaint` task); when none can, the repair is refused before any work, and nothing is copied or recorded. The new take is measured with the same readings as any take. Depends on `config`, `media`, `jobfs`, `takes`, `bar.song`, `providers`, and `songs`.

### dub
A piece in another language as a job of its own: its music and effects stem under new voices, and captions in the new language, with its own human gate.

### nle
The cut as files an editing system opens: FCPXML, OpenTimelineIO, and EDL. `adapters.timeline` in `config/studio.yaml` picks who writes them: this module (default), or `otio`, where `nle_otio` has OpenTimelineIO's `otioconvert` write the FCPXML and EDL from the cut's OTIO file. `read_back` reads a timeline an editor saved (FCPXML, EDL, or OTIO) into a summary, through the same adapter; it changes no cut and no approval.

### nle_otio
The second adapter behind `adapters.timeline`: `otioconvert` called as a command, from the `opentimelineio` package and the `otio-fcpx-xml-adapter` and `otio-cmx3600-adapter` packages in an environment of their own. Public interface: `export(job, to, otio_text)` writes `timeline.<to>` in the job's work folder and checks it is the kind of file asked for (an FCPXML with clips, an EDL with events); `read_back(job, file)` writes `imports/<file>.json`, the clips in order with where each sits and what part of its source it uses. It expects OpenTimelineIO 0.18, stops before the job reaches it when that is not on PATH, and never falls back to `nle.py` by itself. A source that is not on disk has no length to carry, and the FCPXML adapter then fails on it; that failure is reported as the tool's. Depends on `opentools`, `config`, `jobfs`.

```
 nle.export(job, "fcpxml")
     │  adapters.timeline.use
     ├── inhouse ──▶ nle.fcpxml(...) ──▶ timeline.fcpxml
     └── otio ─────▶ timeline.otio (nle.otio) ──▶ otioconvert -O fcpx_xml ──▶ timeline.fcpxml
                                                    │ opentools.run: timeout, process group
                                                    ▼ checked: root, clips; hashes in tool_runs.json
 nle.read_back(job, file) ──▶ otioconvert -I <format> ──▶ imports/<file>.otio ──▶ imports/<file>.json
```

### opentools
The one place an adapter runs an open tool as a command, and the contract every such adapter keeps (ADR 0012). Public interface: `find` (the program on PATH, or a stop naming it and the config key), `require_version` (the program is the version the adapter was written for), `run` (an argument list, a timeout, the tool's own process group killed when the deadline passes), `inside` (a path in the job's folders by real directories: `..` and symlinks refused), and `record` (appends to the job's `tool_runs.json`: program, options, start and end, exit status, the last 2,000 characters of each stream, and the SHA-256 of every input and output). Five failures are told apart by class: `ToolMissingError`, `BadInputError`, `ToolTimeoutError`, `ToolFailedError`, `BadOutputError`. Depends on `jobfs`.

The contract an adapter keeps:

- names the exact program and the version it expects, and checks both before the job reaches it;
- validates inputs, builds an argument list (never a shell string), and writes only inside the job's folders;
- has a timeout, and cancels the tool when it passes;
- tells apart a missing tool, a bad input, a timeout, a tool failure, and a bad output;
- keeps a bounded copy of what the tool printed, its times, and its exit status, with the hash of every input and output;
- checks the output exists and is the kind asked for before the step counts as done;
- never falls back silently to another route: a missing tool stops the step and says how to switch back;
- for a tool that brings an edit back in: the result is a new edit revision and voids an approval of the old bytes. The timeline read-back does not do this yet, because it only summarises.

### timeline
Looking at a piece without playing it: the first and last frame of every shot, a motion strip of frames across each shot, a cut strip of frames either side of each join, a filmstrip over a waveform, and a check for a click or a flash at each cut.

### captions
Word timings to captions, title and caption layout by frame shape and real font metrics, and timed-text files. Fonts are vendored in `fonts/`.

### look
The grade as data: one 3D LUT path for stills and footage, with skin protected and blacks never crushed. Pure.

### motion
The camera on a still: sub-pixel sampling at one steady rate. Frames go to ffmpeg as 16-bit RGB.

### comic
A comic script to pages, a print PDF, a CBZ, and a phone scroll. Models never letter: art is generated with no words, and the engine lays out each page, places balloons where the art is calm, and letters them. Kit references travel with every panel.

### story
A story to a typeset book and a real EPUB with live text. Pages are laid out once, then drawn twice: as images to review, and as type to print.

### bookpdf
A book's pages as a PDF with live text in embedded fonts, at the same places as its page images. The same input gives the same bytes, because approval binds to them.

### bar
The studio bar: what "finished" means, as numbers a tool computes. Pure signals over pixels (`picture`), motion (`motion`), and samples (`sound`), plus the readers that apply them to a file, a job's sources (`sources`), a delivery master (`master`), or a song (`song`). Limits live in `config/studio.yaml`. It reports conformance and craft apart, because a single total flatters whatever the renderer makes. It informs the human gate, and only an objective defect blocks. `identity` reads whether a picture or a video shows a kit's character: a configured command (`identity.face_command`; `providers/runners/face_run.py` runs OpenCV's YuNet, embedding with SFace or ArcFace) describes every face as an embedding, and each face is compared with the kit's reference faces, so a crowd is read face by face. A video is read from one sampled frame a second, by its median closest face and the stretches where the character is lost (`clip_report`). The animatic checks each still against the characters its shot names (`check_cast`, printed by `kalainova animatic`). With no command set, identity is reported as not measured, never as a pass; it warns and does not block.

### qa
Runs the automated checks before the human gate, for a rendered piece, a document, a song, or a file from an outside tool.

### qachecks
The checks QA runs that each ask one question: a kept promise of motion, a model's licence, the layers of a mix, the plan, the cuts, what a vision judge saw (it is sent the shot sheet and the motion strip, and its faults are kept as findings), and burned text or a face outside a profile's safe zone.

### kitchecks
What QA asks of a stream job: did the record keep what the lock promised, and do the frames match the kit's references.

### verdicts
What a person said about a piece or one shot, or about the animatic as a rough cut, and which readings predict it. A verdict on the animatic sets the job's `animatic_reviewed` and is left out of the review set. `review-set` lists each verdict beside its readings, including a shot's own source clip, and says "not enough yet" below three of each side. It reads the bar's `generated_shot_motion` and cannot approve or publish anything.

### provenance
How a piece was made, for whoever answers for it: each asset's model, weights, seed, terms, and hash. Its ledger part, which `kalainova ledger` prints, sums the money by provider, model, stage and shot, lists every attempt from the trace, and names any charge with no trace row. A still reused from an accepted animatic keeps the model and kit references that made it (`shotmake.reused_origin`).

### publish
Approve, publish, and measure. Binds approval to the bytes and a stream piece to its own account. `labels` sets each platform's AI-content label from the assets' synthetic flag, using the fields the aggregator documents, and refuses a platform with none; it also holds a publish time only where the platform's own API takes one. `aggregator` is the one-upload route to several platforms.

### providers
The router and vendor adapters, as ports and adapters (ADR 0023). The engine asks with one typed request per capability (`contract.py`), and gets back a `Result` whose facts are fields; the router writes them into a file's record under the engine's own names, and an adapter cannot. Every model call goes through the router, which reserves the estimate before the call, hands the adapter a `Context` (attempt, labels, the pinned model for that provider only, deadline, and a `Receipt` the adapter fills), settles at the real cost after it, stops on a request the vendor refuses as malformed, and refuses a file that is not what was asked for or has no picture in it. What a model takes is `Provider.inputs`, in the engine's terms; only this package reads the config's vendor field names. Every rented adapter reaches its vendor through a transport (`transport.py`: `FalQueue` in `fal.py`, `Https` for the rest), which rehearses, fills the receipt, sends the labels, says an HTTP failure in the engine's terms, and bills a file that never arrived. What a call leaves behind (its trace row, its ledger detail, its generation record, and the saved-file lookup a restart uses) is `records.py`. Price corrections from the vendor's list price and this studio's own bills are `prices.py`. While a rehearsal is open (`rehearsal.py`), each transport writes its requests down under the router's attempt instead of sending them, and the router refuses any provider that costs money and cannot. `tests/boundary/test_provider_contract.py` is the suite every registered adapter passes. `fal` and `remote` rent models over HTTPS, `spaces` rents free hosted ones, `search` finds sources, and `hyperframes` renders a composition as a shot. `whispercpp` is a second `transcribe` provider that runs the `whisper-cli` command and returns real word times, where `mac` only estimates them; it needs a model file named by `KALAINOVA_WHISPER_CPP_MODEL`. `mac` runs open models on a Mac's GPU (`docs/how-to/run-models-on-a-mac.md`); `runners/` holds what runs in the models' own environment, and the engine never imports it.

### editor
The footage path: shots, scores, direction, and notes. `choose` holds the pure decisions: which take, in what order, at what length. `speech` cuts on words when a transcript exists, and `clips` finds short pieces in a long recording (starting on a sentence start, with opening fillers dropped, and optionally opening and closing on a drawn title card from the graphics provider), chooses the crop through one seam with two adapters (the in-house motion centre, and a face detector the operator names as a command in `config/studio.yaml`), refusing a job whose `brief.source` does not say where the file came from and which file in the job folder covers its use. `patch` updates one cut in an existing `edit_manifest` (source, in point, title), voids any approval, and records the change in `direction.json` when that file is present. `musiccuts` turns a beat grid into bars, phrases, sections and the biggest rise in energy, and says so when there is no steady pulse; `musicvideo` builds the job that cuts a video to a track, with an excerpt, character cutaways under the shot ceiling, and the cost said first. `beats` is a seam: `adapters.beats` in `config/studio.yaml` picks its own onset-and-comb grid (default) or `beat_this`, which `beat_this.py` runs as a command and which adds downbeats. `speech_cuts` is a second seam: `speech.keep_spans` (called by `direct` for each take with sound) follows `adapters.speech_cuts`, which picks the in-house cuts at gaps between words (a silence detector when there is no transcript, the default) or `auto_editor`, which runs the `auto-editor` command, keeps the loud spans it reports, and lays any words over them. `auto_editor.py` follows the adapter contract in `opentools`, and keeps its result by the file's bytes and options. A seam is built only with its second adapter, and a missing command stops the step with its name.

### stock
Free-license footage with credits.

### intake
Takes a finished file from an outside tool.

### media
ffmpeg and ffprobe helpers. Commands are argument lists, never shell strings.

### mediascan
Reading a whole file: where its picture sits, its frames one at a time, and how it bands.

### jobfs
The job folder, schema validation, the ledger, and the private home. A ledger entry carries when it was charged and what the router hands it to join on: the attempt, its labels, the model, the vendor's request id and the billed units.

### config
The model and price table.

### fingerprint
Engine version, git commit, prompts hash, and studio config fingerprinting. Pins jobs to exact engine releases and verifies stream compatibility during approval. `code_stamp` is the commit a running command came from, with `+dirty` for uncommitted code; every trace row carries it.

### host
Operator hardware capability and prerequisite detection. Validates Python version, ffmpeg/ffprobe binaries, GPU accelerators, and adapter presence.

### scorecard
Provider and model scorecard aggregation from operational telemetry traces. Computes empirical latency, spend, and reliability metrics per capability and model.

### audit
Provider independence audit. Analyzes preference chains and provider fallbacks in config/studio.yaml to report single-vendor lock-in risks across capabilities.

### calibration
Agreement reporting between deterministic readings, model judges, and human operator verdicts. Evaluates alignment and identifies uncalibrated checks.

### sound_identity
A stream's fixed sound identity — drum kit, tempo range, keys, and a mastering target — as the song-side equivalent of a face kit. `check_track` reads a rendered track's metadata against it and never reaches a model.

## Cockpit

```
just ci ──► ci-contract  check.py, --fixtures   no media blobs; jobs, kits, streams match the contract
        ──► ci-lint      ruff, mypy, import rules, gitleaks, opengrep
        ──► ci-test      pytest with a coverage floor, including one full render
        ──► ci-docs      lint_docs.py            engine docs grow no worked example
        ──► ci-arch      every component has a section and a box
```

| Plane | Where | Role |
|---|---|---|
| Strategies | `docs/strategies.md` | How a piece gets made and how it can get paid. Subject-agnostic. |
| Pipeline | "Sequence: one piece" above | Stages from brief to measure. Same spine for every medium. |
| Contract | `schemas/` | Job, script, assets, edit, render plan, QA, approval, publish log, measure. |
| Jobs, kits, streams | `$KALAINOVA_HOME` | Operator data, in a private directory. This repo is public (ADR 0010). |
| Gates | `scripts/check.py`, `scripts/lint_docs.py`, pre-commit, `.github/workflows/ci.yaml` | Media stays out of git. Jobs that violate the contract fail. Engine docs stay subject-free. |
| Decisions | `docs/decisions/` | One ADR per standing rule. |
| Evals | `evals/contract/` | Contract fixtures run now. The content eval waits for an accepted or measured job. |

Rent the models. Own the job folder, the gates, and the compile path (ADR 0007). A schema is not a shipped frame.
