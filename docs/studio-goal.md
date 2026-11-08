---
kind: plan
status: active
last_reviewed: 2026-11-07
---

# The studio goal

**One engine that takes a brief to a finished piece a viewer or listener could not tell from good human work: film, short, reel, explainer, comic, book, narration, song, or a researched mix of them.** A person accepts every piece on first review, and the record shows how it was made.

The studio bar in `docs/studio-bar.md` measures defects. This page says what the engine has to be able to do. Taste stays with a human.

## What counts as done

A capability has three states, and only the last one is a claim about quality.

| State | Meaning |
|---|---|
| **Built** | The code exists and its tests pass with faked models |
| **Run** | It has made a real file on real models |
| **Accepted** | A person reviewed that file and said yes |

Nothing here moves past **Run** without a real file, and nothing moves past **Accepted** without a person.

## The line, and where each part came from

| Capability | What it does | Idea from |
|---|---|---|
| Takes | Several seeds per shot, a reading picks, a human overrides | ViMax's candidate selection, extended to video |
| Motion promise | A shot that asked to move fails instead of becoming a still | Reasoned out from review; OpenMontage has the same rule |
| Shot language | First frame, last frame, and motion written apart | ViMax's shot decomposition; LTX's and Runway's prompting guides |
| Continuity | People, places, and props described once and reused word for word | ViMax's character features; the lab's own fix |
| Plan review | Slideshow risk and missing motion, caught before any spend | OpenMontage's plan scoring, rewritten |
| Reserve and settle | A reservation on the ledger, settled at the real cost | OpenMontage's cost tracker, rewritten |
| Provenance | Seed, weights revision, licence, and hash for every asset | genblaze's manifests |
| Songs | Lyrics to takes, readings, a master, lyric files, and a lyric video | HeartMuLa, ACE-Step, YuE2 as engines |
| Research | Sources, private snapshots, and quotes checked against them | OpenMontage's research brief, with verification added |
| Sound layers | Ambience, stems, and a music-and-effects mix | Sound design practice |
| Cut review | A filmstrip with a waveform, and a check at every cut | video-use |
| Timeline export | A cut an editor can open | auto-editor |
| Clips | A long source to short pieces, at word boundaries | video-use, AI Youtube Shorts Generator |
| Dubbing | A piece in another language over its own music and effects | ShortGPT's translation flow |
| Lip sync | A speaker's mouth matched to their line | Rented models |
| Graphics | A rendered composition as a shot | HyperFrames |
| Verdicts and signals | Human verdicts, and which readings predict them | ADR 0011's own rule |
| Render cache | Change one shot and re-encode only what it touches | Standard build practice |

`docs/decisions/0012-build-or-adopt.md` records the rule for what gets built and what gets adopted. `NOTICE.md` credits what was taken.

## What only a real run can answer

The hold on generating content, and the budget, are the operator's. These stay open until a real file exists:

1. Does a motion-first prompt stop generated clips freezing? The readings exist to test it.
2. Which song model holds up on this machine, and at what length?
3. Which readings predict a human verdict? `kalainova signals` reports it once enough pieces have verdicts.
4. Do the vendor adapters match the live APIs? Slugs marked `VERIFY` in `config/studio.yaml` are unconfirmed.
