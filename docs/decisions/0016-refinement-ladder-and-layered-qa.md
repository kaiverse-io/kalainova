# 0016. A piece rises through stages that end in locks, and QA runs in layers

Status: proposed · 2026-11-12.

## Context

Each kind of piece grew its own way to get better. Video has an animatic and a gate on it, songs have takes, kits freeze a face, and a comic is only a deliverable. Nothing says that a cheap draft must be accepted before a dear step is paid for, so spend and review drift apart. QA is the same: a contract, readings, a vision judge, an agent review, and a human verdict exist, but they are not ordered, a still has no readings at all, audio has none for a vocal or a groove, and nobody measures whether a judge agrees with the human.

## Decision

**A refinement ladder.** Every kind of piece rises through stages. A stage is cheaper to redo than the next one, and it ends in a lock: the files it made, hashed and recorded in the job, accepted by a named person. A paid step may only run after the lock below it, and only under the job's cap.

| Stage | Made by | Ends in |
|---|---|---|
| Draft | A local model, no spend | A person's choice of take or cut |
| Lock | Nothing new: the draft is accepted and hashed | An accept, naming the person |
| Polish | A rented model, capped | A new take that must pass the same layers |

A step that polishes does not replace the lock. It makes a take beside it, and the lock stays on disk.

**Layered QA.** Layers run cheapest first and stop early. A failure below a layer blocks everything above it, and any paid generation.

0. **Contract.** Schemas, rights, and the hard rules.
1. **Measurements.** Numbers a program computes from the file, with limits in config.
2. **Lock conformance.** Was each shot or track made with its kit's references, the pinned model, and the locked version.
3. **Model judges.** A judge with a fixed rubric. Every claim cites a time or a region, and a claim that cites none is dropped.
4. **Agent review.** A reading of the piece that the numbers cannot see, written to the same findings file.
5. **A person.** Accept, fix, or reject, by name.

Layers 0 to 2 may block. Layers 3 and 4 advise. Layer 5 decides. Every layer writes `findings.json`, and says what it could not check, so a missing judge shows as a gap and not as a pass.

**Calibration.** A person's verdicts are the labels. The engine reports how often each reading and each judge agrees with them, and one that does not agree is not used to block.

## Consequences

A judge model is still a model, so its verdicts vary between runs. This ADR does not make taste a number: it keeps what can be measured measured, and keeps a person at the end. Calibration needs a review set of real verdicts, and until one exists no reading or judge should be tuned or trusted to block.

Building it is slices, each with its own tests and its own `ARCHITECTURE.md` section:

1. Readings for stills, so `bar` stops refusing an image.
2. Audio readings for a vocal and a groove (issue 83).
3. A song's take and its lock, with a kit for a sung voice.
4. A storyline and scene panels as a stage before stills.
5. Providers that polish: voice conversion and section repair.
6. An agreement report between readings, judges, and verdicts.

Nothing here names a genre, a brand, or a person. Limits and targets are numbers in config.
