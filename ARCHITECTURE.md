# Kalainova Architecture

Kalainova is one engine and many jobs. A job declares a **strategy** and one or more **media** kinds. It does not declare a segment. The engine owns the job record, the gates, and the measure of acceptance. It rents the models, and it can run outside production tools behind one contract.

In the diagrams, green is built, amber is partly built, and grey is planned. A planned part is a decision, not a claim that it exists.

## Executive Summary

One public engine and many private jobs. Rented models make the bytes; the engine owns the record, the gates, and the compile path. Two decisions shape the rest: a human approves every piece against its exact bytes (ADR 0007), and anything that must stay the same lives in a frozen kit that every model call must carry (ADR 0009).

## System Overview

The system context below is the runtime view.

## System context

Who and what the engine touches.

```mermaid
flowchart LR
    operator["Operator<br/>brief, review, approve"]
    agent["Coding agent<br/>builds and runs jobs"]
    engine["Kalainova engine<br/>job record, gates, render"]
    models["Rented model providers<br/>image, video, voice, music, LLM"]
    tools["Outside production tools<br/>planned, run in containers"]
    platforms["Publishing platforms<br/>official APIs or an aggregator"]
    stock["Free-license stock sources"]

    operator -->|"brief, approval"| engine
    agent -->|"plans, stages"| engine
    engine -->|"file, contact sheet"| operator
    engine -->|"requests within budget"| models
    models -->|"files, cost"| engine
    engine -.->|"job bundle"| tools
    tools -.->|"files, record"| engine
    stock -->|"licensed footage"| engine
    engine -->|"approved bytes only"| platforms
    platforms -->|"48 h metrics"| engine
```

An agent never writes an approval (ADR 0007). A human approves every piece.

## Layer view

Dependencies point down. A lower layer never imports an upper one, and a producer or model can be replaced without changing the control layer.

```mermaid
flowchart TB
    subgraph control["Control layer: owned"]
        direction LR
        contract["Job contract<br/>brief, rights, budget"]:::built
        selector["Producer selection"]:::planned
        intake["Intake of outside files"]:::built
        qa["QA"]:::partial
        gate["Human gate<br/>hash-bound approval"]:::partial
        publish["Publish"]:::built
        measure["Acceptance and measure"]:::partial
        contract --> selector --> intake --> qa --> gate --> publish --> measure
    end

    subgraph producers["Producers: swappable"]
        direction LR
        pgen["Generated video"]:::partial
        pedit["Footage edit"]:::partial
        pexplain["Explainers"]:::planned
        psong["Songs"]:::planned
    end

    subgraph shared["Shared media tools: owned"]
        direction LR
        compile["ffmpeg compile and render"]:::built
        timing["Word timing and captions"]:::partial
        mix["Audio mix and loudness"]:::built
    end

    subgraph access["Model access: rented"]
        direction LR
        router["Router<br/>budget, deadline, failover, reuse"]:::built
        adapters["Provider adapters"]:::built
    end

    records[("Job folder<br/>record, ledger, stamps")]:::built

    control --> producers
    producers --> shared
    producers --> access
    control --- records
    producers --- records
    access --- records

    classDef built fill:#d3f0d8,stroke:#2e7d32,color:#10321a
    classDef partial fill:#fdeec8,stroke:#b7791f,color:#3d2a07
    classDef planned fill:#e8e8e8,stroke:#777777,color:#333333,stroke-dasharray: 4 3
```

## Component view: the engine today

The modules in `src/kalainova/`, and the two paths that make a piece. Every model call goes through `providers/router.py`.

```mermaid
flowchart TB
    cli["__main__.py<br/>CLI"]

    subgraph generated["Generated path"]
        plan["plan.py"]
        assets["assets.py"]
        edit["edit.py"]
    end

    subgraph footage["Footage path"]
        stockmod["stock.py"]
        analyze["editor/analyze.py<br/>shots and scores"]
        direct["editor/direct.py"]
        notes["editor/notes.py"]
        beats["editor/beats.py"]
    end

    subgraph finish["Shared finish"]
        render["render.py<br/>closed op list"]
        captions["captions.py"]
        qa["qa.py"]
        publish["publish/<br/>approve, publish, measure"]
    end

    subgraph access["Model access"]
        router["providers/router.py"]
        base["providers/base.py<br/>contract and registry"]
        remote["providers/remote.py"]
        local["providers/local.py<br/>placeholders"]
    end

    subgraph foundation["Foundation"]
        jobfs["jobfs.py<br/>job folder and ledger"]
        config["config.py<br/>config/studio.yaml"]
        media["media.py<br/>ffmpeg and ffprobe"]
        schemas["schemas/"]
    end

    cli --> plan --> assets --> edit --> render
    cli --> stockmod --> analyze --> direct --> render
    notes --> direct
    beats --> direct
    render --> captions
    render --> qa --> publish

    plan --> router
    assets --> router
    direct --> router
    qa --> router
    router --> base
    remote --> base
    local --> base

    router --> jobfs
    render --> jobfs
    publish --> jobfs
    jobfs --> schemas
    router --> config
    render --> media
```

## Component view: model access

What happens on one model call. The engine depends on the contract, never on a vendor.

```mermaid
flowchart LR
    caller["Engine stage"] --> list["Listed providers<br/>job list, else studio list"]
    list --> saved{"Same paid file<br/>already saved?"}
    saved -->|"yes"| reuse["Reuse with no charge"]
    saved -->|"no"| priced{"Priced, or job<br/>has no cap?"}
    priced -->|"no"| next["Next listed provider"]
    priced -->|"yes"| reserve["Check the cost cap"]
    reserve -->|"over cap"| stop["Stop the job"]
    reserve -->|"within cap"| invoke["Call with a deadline<br/>to a temporary path"]
    invoke -->|"failed"| next
    invoke -->|"timed out"| charged["Charge the estimate"]
    charged --> next
    invoke -->|"file returned"| check{"File matches<br/>the request?"}
    check -->|"no"| rejected["Charge, discard"]
    rejected --> next
    check -->|"yes"| move["Move to destination<br/>record, charge"]
    next -->|"none left"| fail["Job fails and<br/>names each reason"]
    next -->|"another"| priced
```

A bug in an adapter is raised and does not count as a provider failure. Only listed providers are tried. `local` is listed in `config/studio.yaml`, so a run with no keys still works, and `approve` refuses what it makes.

## Sequence: one piece

```mermaid
sequenceDiagram
    actor Operator
    participant Engine
    participant Router
    participant Provider
    participant Record as Job folder
    participant QA
    participant Platform

    Operator->>Engine: Brief, rights, budget
    Engine->>Record: job.json, script_packet.json
    loop Each asset
        Engine->>Router: Request
        Router->>Record: Check the cap and saved files
        Router->>Provider: Call with a deadline
        Provider-->>Router: File and cost
        Router->>Record: Record the file, charge the ledger
        Router-->>Engine: Checked file
    end
    Engine->>Engine: Edit, compile, render final.mp4
    Engine->>Record: render_stamp.json
    Engine->>QA: Run the checks
    QA->>Record: qa.json with the file hash
    Engine-->>Operator: File and contact sheet
    alt Accepted
        Operator->>Engine: approve
        Engine->>Record: Check QA, placeholders, and stamp
        Engine->>Record: approval.json
        Engine->>Platform: Approved bytes, AI label on
        Platform-->>Engine: 48 h metrics
        Engine->>Record: measure.json
    else Sent back
        Operator->>Engine: Reason
        Engine->>Router: Regenerate what was named
    end
```

## Job states

```mermaid
stateDiagram-v2
    [*] --> draft
    draft --> rendered: make or edit
    rendered --> rendered: re-render
    rendered --> approved: human approve
    approved --> published: publish
    published --> measured: 48 h metrics
    draft --> killed
    rendered --> killed
    approved --> killed
    measured --> [*]
    killed --> [*]
```

`scripts/check.py` also allows `rented` and `accepted`, for work finished in a rented tool.

## Deployment view

The engine runs on one machine. Anything from a third party runs in a container that sees only the folders mounted into it.

```mermaid
flowchart TB
    subgraph host["Operator machine"]
        repo["Repo and job folders"]
        media_out["Media output<br/>outside git"]
        subgraph docker["Container runtime"]
            engine["Engine container"]
            third["Third-party producer<br/>one container each"]:::planned
        end
    end

    subgraph ci["GitHub Actions"]
        checks["check, eval, lint, test"]
    end

    subgraph rented["Rented over HTTPS"]
        api["Hosted model APIs"]
        gpu["Rented GPU endpoint"]:::planned
        gpuproducer["Rented GPU running<br/>a whole producer"]:::planned
    end

    repo -->|"mounted"| engine
    engine --> media_out
    media_out -.->|"mounted read-only"| third
    engine --> api
    engine -.-> gpu
    engine -.->|"job bundle"| gpuproducer
    repo -->|"push"| checks

    classDef planned fill:#e8e8e8,stroke:#777777,color:#333333,stroke-dasharray: 4 3
```

## Adding a rented GPU

Three different shapes, with different costs. None of them changes a stage of the engine.

```mermaid
flowchart LR
    need["Rented GPU"] --> endpoint["Serves one model<br/>over HTTP"]
    need --> whole["Runs a whole<br/>production tool"]
    need --> hourly["Billed by the hour"]
    endpoint --> adapter["Add a provider adapter<br/>and a config entry"]:::built
    whole --> runner["Container runner<br/>and file transfer"]:::planned
    hourly --> ledger["Measured cost per job<br/>and an infrastructure entry"]:::planned

    classDef built fill:#d3f0d8,stroke:#2e7d32,color:#10321a
    classDef planned fill:#e8e8e8,stroke:#777777,color:#333333,stroke-dasharray: 4 3
```

## The stable interfaces

These change only with a version bump. A new interface waits for a second real use, so storage and queues stay plain for now.

| Interface | In | Out | State |
|---|---|---|---|
| **Provider** | Request, deadline, and budget, through the router | File, cost, model, provenance | Built, including song requests. No song adapter exists yet, and requests are not typed. |
| **Producer** | Job bundle in a mounted folder | Files and a record, through `kalainova intake` | Partial. Intake is built. Tools run by a coding agent still need a container wrapper, and their output varies between runs. |
| **QA check** | Any file and its format | Pass or fail, with evidence | Partial. Files the engine did not render get technical checks only, and checks are not plug-ins yet. |

## Standing rules

- **No implicit fallback.** Only listed providers are tried.
- **No unpriced spending.** A job with a cap refuses a call it cannot estimate.
- **Every paid result is saved at once.** A restart reuses it.
- **Approval binds three things:** the bytes QA checked, the asset record they were rendered from, and a human reviewer.
- **A tool's own report is not proof.** Outside tools get their own API keys, so their costs can be checked against vendor invoices.
- **A model library is an implementation, not the interface.** It stays behind the provider contract with its own retries off or counted.

## Known gaps

| Gap | Effect |
|---|---|
| No publisher takes audio-only files | A song can be approved but not posted |
| No content review on files from outside tools | A human is the only check on their content |
| No song adapter or container runner | The contracts exist, and nothing uses them in production yet |
| Cap checks run one call at a time | Parallel calls could overshoot the cap together, until Postgres holds the ledger (ADR 0010) |
| Files from outside tools carry no enforced references | A human compares them against the kit |
| A kit cannot prove a face is not a real person's | A human attests at freeze and approves each piece; the vision judge is one more signal |
| Rendered files and job records are on one machine | Only kit files can reach object storage today (ADR 0010) |
| QA does not predict the operator's verdict | A file can pass QA and the bar and still be rejected on review. The bar measures craft defects, not taste |
| A book PDF is page images | The EPUB holds live text; the PDF's text cannot be selected |
| No publisher takes a comic or a book | They can be approved but not posted |
| Comic and story scripts have no LLM planner yet | An agent or a person writes the script |
| Stereo only | No 5.1 or 7.1 mix, and an upmix from stereo is not an honest substitute |
| SDR only | No HDR master |

## Kits, streams, and jobs

Three objects carry continuity. The kit says what is fixed, and the stream says where it goes. The job locks exact versions, so a later kit change never moves a piece already made.

```mermaid
flowchart LR
    operator["Operator"] -->|"stream + brief"| request["request"]
    kit["Kit, frozen version<br/>face, voice, persona, style"]:::built --> stream
    stream["Stream<br/>identity, generators, limits"]:::built --> request
    canon["Canon, append-only"]:::built --> stream
    request --> preflight{"Can the pinned tools<br/>hold the kits?"}
    preflight -->|"no"| stop["Stop before spending"]
    preflight -->|"yes"| lock["Job + kit.lock.json"]:::built
    lock --> plan["plan: persona and canon"]
    lock --> assets["assets: references, voice, music"]
    assets --> qa["QA: the record, then the frames"]
    plan --> assets
    qa --> gate["Human gate"]
    store[("Blob store<br/>content-addressed")]:::built --> assets

    classDef built fill:#d3f0d8,stroke:#2e7d32,color:#10321a
```

## Cloud path

Today one machine runs the engine, with kit files optionally in private object storage. Phases 2 and 3 are proposed in ADR 0010, and none of it is built.

```mermaid
flowchart TB
    subgraph data["Private data plane"]
        pg[("Postgres<br/>queue, ledger, index")]:::planned
        s3[("Object storage, SSE-KMS<br/>kit files, renders")]:::partial
        secrets["Secret manager"]:::planned
    end
    subgraph compute["Stateless compute"]
        api["Review API<br/>authenticated"]:::planned
        worker["Worker: one job, one container<br/>ffmpeg, CPU only"]:::planned
    end
    models["Rented models over HTTPS"]
    api --> pg
    worker -->|"claim with SKIP LOCKED"| pg
    worker <-->|"bundles, bytes"| s3
    worker --> secrets
    worker --> models

    classDef partial fill:#fdeec8,stroke:#b7791f,color:#3d2a07
    classDef planned fill:#e8e8e8,stroke:#777777,color:#333333,stroke-dasharray: 4 3
```

## Component Diagram

Static view of top-level modules, an arrow wherever one imports another. `just ci-arch` checks that every component has a box here.

```
 __main__ ──▶ studio_cli ──▶ streams ──▶ consistency ──▶ kits ──▶ blobstore
    │                                       │  │          │
    │                                       │  └─▶ kitrules ◀── scripts/check.py
    │                                       └─▶ providers
    ├─▶ plan ──────▶ consistency, prompts, providers
    ├─▶ assets ────▶ consistency, kits, media, config, providers
    ├─▶ edit ──────▶ config
    ├─▶ render ────▶ captions, look, motion, media
    ├─▶ qa ────────▶ bar, comic, story, consistency, prompts, media, config, providers, publish
    ├─▶ bar ───────▶ media, config
    ├─▶ comic ─────▶ assets, captions, consistency, render, providers
    ├─▶ story ─────▶ comic, captions, render, providers
    ├─▶ publish ───▶ consistency, streams, stock
    ├─▶ editor ────▶ media, providers
    ├─▶ intake, stock ──▶ media
    └─▶ jobfs, config: the foundation, imported throughout
```

## Components

### __main__
The command line. Parses arguments and calls a stage. Holds no rules.

### studio_cli
Commands for kits, streams, canon, schedules, and requests.

### kitrules
What makes a kit legal. Stdlib only, shared by the engine and `scripts/check.py`.

### kits
Kit lifecycle: draft, add a file, freeze, bump, load, and verify stored bytes.

### blobstore
Local cache plus optional S3-compatible durable copy, addressed by hash.

### streams
Stream records, canon, the schedule packet, and `request`, which turns a stream and a brief into a locked job.

### consistency
Resolves a stream's kits, builds and verifies the lock, applies the fixed things to each shot and script, and holds `RULES`, the table of how each is enforced.

### prompts
Loads versioned prompts from `prompts/`.

### plan
Intent to script. Loads the kits' persona and canon for a stream job.

### assets
Script to files. Every shot of a stream job carries its references and pinned model.

### edit
Assets to an edit manifest.

### render
Edit manifest to a closed op list, then to the file through ffmpeg.

### captions
Word timings to captions, title and caption layout by frame shape and real font metrics, and timed-text files. Fonts are vendored in `fonts/`.

### look
The grade as data: one 3D LUT path for stills and footage, with skin protected and blacks never crushed. Pure.

### motion
The camera on a still: sub-pixel sampling at one steady rate. Frames go to ffmpeg as 16-bit RGB.

### comic
A comic script to pages, a print PDF, a CBZ, and a phone scroll. Models never letter: art is generated with no words, and the engine lays out each page, places balloons where the art is calm, and letters them. Kit references travel with every panel.

### story
A story to a typeset book and a real EPUB with live text.

### bar
The studio bar: what "finished" means, as numbers a tool computes. Pure signals over pixels and samples, plus the readers that apply them to a job, any file, or a delivery master. Limits live in `config/studio.yaml`. It informs the human gate, and only an objective defect blocks.

### qa
Automated checks before the human gate, including whether the kit lock held.

### publish
Approve, publish, and measure. Binds approval to the bytes and a stream piece to its own account.

### providers
The router and vendor adapters. Every model call goes through the router.

### editor
The footage path: shots, scores, direction, and notes.

### stock
Free-license footage with credits.

### intake
Takes a finished file from an outside tool.

### media
ffmpeg and ffprobe helpers. Commands are argument lists, never shell strings.

### jobfs
The job folder, schema validation, the ledger, and the private home.

### config
The model and price table.

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
| Pipeline | `docs/pipeline.md` | Stages from intent to measure. Same spine for every medium. |
| Contract | `schemas/` | Job, script, assets, edit, render plan, QA, approval, publish log, measure. |
| Jobs, kits, streams | `$KALAINOVA_HOME` | Operator data, in a private directory. This repo is public (ADR 0010). |
| Gates | `scripts/check.py`, `scripts/lint_docs.py`, pre-commit, `.github/workflows/ci.yaml` | Media stays out of git. Jobs that violate the contract fail. Engine docs stay subject-free. |
| Decisions | `docs/decisions/` | One ADR per standing rule. |
| Evals | `evals/contract/` | Contract fixtures run now. The content eval waits for an accepted or measured job. |

Rent the models. Own the job folder, the gates, and the compile path (ADR 0007). A schema is not a shipped frame.
