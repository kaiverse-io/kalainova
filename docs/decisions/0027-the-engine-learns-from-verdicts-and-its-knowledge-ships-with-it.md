# 0027. The engine learns from verdicts, and its knowledge ships with it

Status: accepted · 2026-11-18, revised the same day after two outside reviews. Slices 1 to 4 are built; 5 and 6 are not yet. Builds on 0017 (an autonomy level per review gate), 0022 (no paid call until a ready package is signed off), 0024 (learned judges rank takes and never block), 0026 (a bench ranks within itself and is held to preferences).

## Context

The engine is a product. Other operators install it and run it on their own machines, on agent VMs, and for many studios at once, so nothing it knows may depend on one machine, one repo checkout, or one agent's memory.

One session of singing takes showed how far it is from that:

- **A person's correction became prose.** A take's eyes were lifeless because the shot's own cue said "eyes half closed". After the correction, the next direction was written by hand into one job. When the reviewer then found the mouth "too big and wide", the agent hand-wrote a third direction, with mouth wording that the model's prompt guides advise against. The lessons went into `AGENTS.md`, a skill and memory files. Only an agent working in this repo reads those, and none of them ship.
- **A model's limit was missed.** OmniHuman takes at most 300 characters of prompt. Its host's schema does not say so; several reseller API references do. The hand-written prompt was 470 characters.
- **Verdicts are recorded and not used to direct.** `verdicts.jsonl` holds preferences by aspect, and `kalainova agreement` measures judges against them (0026). Nothing uses them to choose how the next take is directed.
- **An installed copy cannot run.** The engine reads `prompts/`, `config/studio.yaml`, `schemas/`, `fonts/` and `jobs/_template` from the folder above its own source (`jobfs.REPO`, `config.REPO`, `fingerprint.ROOT`, `captions`, `providers/local`). The default studio folder is that same checkout when `KALAINOVA_HOME` is unset. The wheel ships only `src/kalainova`. Judge commands in a studio's config name scripts by absolute path in a checkout.

Two outside reviews agreed on the direction. They found the first draft too broad for a dependable first version: it changed a studio's defaults automatically, proposed checks, and set up a commons of lessons before installed operation and provenance existed. This revision takes their order.

## Decision

### 1. An installed copy is the product, and CI proves it

- **Package data.** Prompts, the default config, schemas, fonts, the job template, the judge runners and the operator skills become package data, read with `importlib.resources`. A checkout and an installed wheel run the same code path.
- **A per-user studio folder.** An unset `KALAINOVA_HOME` means a per-user data directory (`platformdirs`), never the repo.
- **Judges as named runners.** A judge is a runner in the package (`python -m kalainova.runners.<name>`). It declares its own environment and weights, which live outside the package and are named in the studio's config. `kalainova judges` says which judges are ready on this machine, and why the others are not.
- **CI tests the wheel.** CI builds the wheel, installs it in a clean directory with no checkout, and checks that it loads its prompts, config and directions, and refuses a 301-character prompt to a model capped at 300.

### 2. Three layers of knowledge, overlaid like config

| Layer | Holds | Lives in | Changes by |
|---|---|---|---|
| Engine | model capabilities, directions, checks, neutral defaults | the package, versioned with it | a release |
| Studio | its verdicts, its overrides (a look, a model, a direction), each accepted by a person | `$KALAINOVA_HOME` | its operator |
| Job | the brief | the job folder | its operator |

A lower layer overrides a higher one field by field, and the merged result is recorded with every take.

**Engine defaults are neutral.** Taste belongs to a studio: a photographed look is one studio's bar, not every studio's. It becomes an engine default only after it holds across subjects and models.

**One machine first.** The studio folder is a directory tree on one machine. Several agents or machines writing one studio at once need transactional storage, and that is a later decision. A shared or synced filesystem is not assumed to behave like a local disk.

### 3. Knowledge is data with ids, versions and sources

- **A capability record per model.** It holds the fields the model takes and their limits: prompt length, image size, audio length, output size. Each claim carries:
  - its source;
  - the date it was observed;
  - its class: vendor-published, reseller-published, independently tested, or seen in our own takes;
  - whether it is provisional.

  `kalainova models refresh` reads the vendor's schema and pricing and reports any difference from the stored claims. It never overwrites a reviewed claim silently. A limit nobody has stated is shown as unknown, not as safe. A request that breaks a known limit is refused before it is sent, and a vendor's validation refusal is mapped back onto the record.
- **A direction per kind of shot,** with an id and a version: `perform.sing@1` for a person singing on camera. A model family that needs different wording gets a variant. A direction describes the performance and never mouth shapes, because the voice moves the mouth. `kalainova guide <model|kind>` prints the merged directions and limits.
- **Checks** in `shots.review` and `readiness`. Each names the lesson it enforces. A wording check such as `performance_words` is a warning, never a proof that a cue is safe.

### 4. Every take and verdict records what made it

Each take names:
- the provider and model, with the provider's version where it gives one;
- the capability record version, and the direction id and version;
- the resolved prompt and the inputs' hashes;
- the engine version and the merged knowledge's fingerprint;
- each judge's name and environment.

Every verdict is tied to that record. A fingerprint names a version. It does not make a result repeatable when a vendor changes a model behind the same name, so a change in a provider's reported version is recorded, not hidden.

### 5. Learning starts as a report and a proposal a person accepts

- **The report.** `kalainova learn` ranks the directions and models tried on each kind of shot, aspect by aspect, from the pairwise preferences already recorded (0026). It fits a Bradley-Terry model with `choix` (offline), and shows:
  - the counts and the uncertainty;
  - whether the comparisons are connected;
  - what has too little evidence to say anything.
- **The proposal.** Where a studio variant beats the current default by the bar set in config, the report proposes a studio override with its evidence. Only a person accepts one into the studio layer. Nothing changes a default by itself.
- **A comparison is never a retake.** A new direction is tried only as a row inside a package a person signs (0022), beside the current default, with the same still and line.
- **Deferred:**
  - bandits;
  - automatic prompt optimisation;
  - proposed checks;
  - gate autonomy over proposals (0017);
  - any export of lessons.

  Each is revisited when the volume of verdicts justifies it. If lessons are ever exported, the export is opt-in, previewable and content-free. It never carries media, prompts, scripts, notes, names, paths, references, verdict identities, keys, or per-job ids and times.

### 6. Agents get the knowledge through the tool and shipped skills

- **Skills ship in the package** as Agent Skills folders (`SKILL.md` plus resources). `kalainova skills export` writes them where an agent harness reads skills.
- **A skill is guidance, never enforcement.** Limits, packages and readiness are enforced in the engine.
- **An MCP server, if one comes,** wraps the same commands. It is not a second store of knowledge.
- **`AGENTS.md` stays the guide for developing this repo.** Its learning loop tells a developer where a lesson goes in the engine.

### 7. Secrets never travel with the product

A key is never in the wheel, a job, a prompt, a trace, a skill or a knowledge file. On an agent VM, credentials are injected at run time, scoped to the work and short-lived, by the platform's secret store or workload identity. The engine reads them from the environment as it does today.

## Consequences

- An installed copy on a fresh machine or an agent VM knows everything a checkout knows, and CI proves it on a built wheel.
- A first take follows every lesson in the engine layer and its studio's accepted overrides, with no agent remembering anything.
- Directions improve per studio from that studio's verdicts, with the evidence shown and a person accepting each change. Taste stays with the studio.
- Capability records and their sources become data to keep correct. A refresh reports drift; it does not hide it.

## Alternatives

- **Keep lessons as prose for agents.** Rejected as the store of product knowledge: none of it ships, and nothing enforces it.
- **Have a language model write each shot's prompt, or optimise prompts automatically (DSPy).** Rejected for now: it is not deterministic, it optimises the metric it is given rather than a person's taste, and it spends on every shot.
- **Change a studio's defaults automatically from tallies.** Rejected for the first version: sparse, uneven and correlated comparisons can promote one bench's quirk.
- **Adopt an experiment platform (MLflow, Langfuse).** Rejected: heavier than a handful of versioned directions and a local preference fit. `choix` and, for prompt regression suites, Promptfoo run locally and offline, and are adopted where they fit.
- **Upload telemetry by default.** Rejected: studios' content and taste are private.

## Slices

1. Installed operation: package data, a per-user studio folder, judges as runners plus `kalainova judges`, and the clean wheel test in CI.
2. Provenance on every take and verdict.
3. Capability records with sources and `models refresh`. Today's prompt limits become the first claims, marked provisional where only resellers state them.
4. Directions as versioned data (`perform.sing@1`) and `kalainova guide`.
5. Skills export.
6. `kalainova learn`: the report and the proposal.
