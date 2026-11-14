# 0016. A free draft is accepted before anything is paid for, and checks run cheapest first

Status: accepted · 2026-11-13.

## Context

Each kind of piece grew its own way to get better. Video has an animatic and a gate on it, songs have takes, kits freeze a face, and a comic is only a deliverable. Nothing said that a cheap draft must be accepted before a dear step is paid for, and a reading that missed could ask a paid model for another take with no person involved. QA had the same shape: a contract, readings, a model judge and a human verdict existed, but they were not ordered by cost, and several ran only after the money was spent.

The purpose of this decision is narrow. **A paid call is made once, on inputs that were already accepted, so that as little as possible is left for it to get wrong.** Everything below serves that: it lowers spend, it keeps bad results from being paid for, and it makes the paid step predictable.

## Terms

- **Free:** costs nothing to run again. A local model within the machine's limits, a drawn graphic, a deterministic edit, a render.
- **Cheap:** a rented call priced in cents, made a fixed number of times.
- **Paid:** any other rented call.
- **Stage:** one step of a piece that produces files.
- **Lock:** a stage's files, hashed and recorded in the job, and accepted. Later stages read them by hash and never change them.
- **Candidate:** one of a small, fixed number of attempts at a stage.
- **Repair:** a deterministic change to a file. No model.
- **Polish:** a model's change to an accepted file, kept as a new take beside it.

## Decision: how a piece is made

1. **Stages run in order of cost.** A stage is cheaper to redo than the one after it.
2. **A stage ends in a lock.** A named person accepts it, or a gate that has earned that right (see "Who decides").
3. **A paid step reads only locked inputs**, runs under the job's cap, and runs the number of times the brief planned. It never runs again because a check failed. Another paid attempt is a person's decision (ADR 0013, amended 2026-11-13).
4. **Free steps may loop**, up to a limit.
5. **Candidates are few and fixed in advance**: two or three per stage, set in the brief. A larger pool ranked by a score drifts toward what the score likes.
6. **When a check fails, the cheapest fix comes first:** repair the file; then polish the one unit that failed; then regenerate that one unit. A failure never sends the piece back past a lock above it.
7. **Polish never replaces a lock.** It makes a take beside it, and the lock stays on disk.
8. **Pieces that can ship apart are separate jobs**, linked one way by hash. A track and a video cut to it are two jobs. So are a score, a dialogue track and the film that uses them. The later job never changes the earlier one, and one accepted asset can feed many later pieces.
9. **Each stage says what it settles for the paid step.** A stage that settles nothing is ceremony, and is removed.
10. **A draft may be made with a model whose output cannot be released.** If such a draft becomes an input to a released piece, a person decides and is recorded, as in the rights rule of the contract.

## The ladder, by kind of piece

"Lock" marks where acceptance happens. The last column is what the paid call no longer has to guess.

| Kind | Free stages | Cheap stage | Paid step, once | Settled before paying |
|---|---|---|---|---|
| Song or music | Words, tempo, structure. A few local takes. **Lock: the take.** Repair: a clean end on a bar line. | None | Optional polish of one section, or a rented render of the same song file | Lyrics, sections, tempo, length |
| Short or reel | Shot plan against the locked audio. **Lock: the animatic** (stills cut to the beat). | Two or three stills per shot. **Lock: one still per shot.** | Motion for each accepted still | Timing, order, first frame, end frame, identity, which shots exist at all |
| Film or episode | Logline, outline, scene list, script. **Lock: the script.** A scratch read with a local voice. **Lock: an animatic per scene.** | Stills per shot, as for a short | Motion, the final voice for each line, lip sync | Story, dialogue timing, every frame, which shots depend on which |
| Narration or dubbing | Script, or transcript and translation. **Lock: the text**, by a speaker of the language. A scratch read and a draft mix. **Lock: the timing.** | None | The final voice, once per line | Words, timing, mix |
| Comic or book | Script and panel breakdown. **Lock.** Layout with rough panels and lettering. **Lock: the pages.** | A character sheet. **Lock.** | Final art for each panel, from the references | Composition, text, balloons, page count, identity |
| Ad and its variants | The body goes through the short's ladder. **Lock: the body.** Each differing opening as an animatic. **Lock.** | Stills for each opening | Motion for the openings only | Everything the variants share |
| Edit of supplied footage | Ingest, shot scoring, a rough cut. **Lock: the cut.** Patches change one cut and no other. | None | Optional: an enhancement, or a generated insert | The cut |
| Kit | Candidate looks on a sheet | Reference images | None | A person freezes a kit. No gate takes this over. |

Where the free model is also the one that makes the release, as with a local song model, there is no paid step and the ladder ends at the lock.

Video is never drafted by generating video locally. Its draft is the animatic: accepted stills, cut to accepted audio.

## Decision: how a piece is checked

Checks follow the same order as stages: free first, a model next, a person last.

| Layer | What it is | Cost | May it block? |
|---|---|---|---|
| 0. Contract | Schemas, rights, hard rules | Free | Yes |
| 1. Measured | Numbers computed from the file, with limits in config | Free | Yes, for objective faults only |
| 2. Identity and lock | Made from the locked inputs, with the pinned model; a character within a measured distance of the kit's references | Free | Yes |
| 3. Model check | Yes-or-no questions about visible or audible defects. Every answer cites a time or a region; one that cites none is dropped. It may answer "unsure". | Cheap | No, it advises, until its record against a person's verdicts earns more |
| 4. Decision | Accept, fix or reject | A person's time | Decides |

Rules:

1. **A check runs at the earliest stage where what it checks exists.** Text is checked on the script. Identity is checked on the still. Timing is checked on the animatic. None of these waits for the paid result.
2. **A layer runs only on what passed the layer below.** A model is never asked about a file that failed a free check.
3. **A failed check below blocks every stage above, and any paid step.**
4. **After a paid step the same layers run.** A failure stops and reports. It lists what a person can do: accept as it is, repair, or ask for another paid attempt. It spends nothing.
5. **A model check is not repeated to get a different answer.**
6. **Every layer says what it could not check**, so a check that did not run shows as a gap and never as a pass.
7. **A person's decision is recorded with its reason**, and a choice between two candidates is recorded as a preference. These are the labels everything else is measured against.
8. **A reading or a model check is trusted only as far as it has agreed with those labels.** One that has not been measured warns and does not block. A number that improves is not a piece that improves.

What is checked where:

| Kind | Free, on the draft | Identity and lock | Model check | A person sees |
|---|---|---|---|---|
| Song or music | Level, peak, clipping, silence, the ending, length, words heard | The chosen take's hash; the model that made it | None trusted today for musical quality | The top two or three takes |
| Short or reel | Cuts on the beat, pacing, length, caption safe zone, on the animatic | Each still against the kit; sampled frames of each clip | Defects in stills, then in clips: anatomy, warping, flicker, an action that did not happen | The animatic, then the final |
| Film or episode | Script against the canon and the persona; then as a short, per scene | As a short, plus the same place, clothes and props across shots that depend on each other | As a short, judged with the shots either side | The script, each scene's animatic, flagged shots, the final |
| Narration or dubbing | Level, pauses, hard cuts, voice against music | The voice against the kit's reference | Mispronounced or dropped words | The text, then the final |
| Comic or book | Lettering size, text overflow, page count, file validity | Each panel's character against the sheet | Defects per panel | Every page |
| Ad and its variants | As a short; the shared body is byte-identical across variants | As a short | As a short, on the openings only | The body once, then each opening |
| Edit of supplied footage | Repeated shots, cuts per minute, clicks and flashes at cuts | The sources are covered by rights | None needed | The cut |

No check here judges whether a story works or a track is good. That stays with a person, and later with what the audience does.

## Who decides

A lock is accepted by a person today. Each gate is built so that a check can take it over once it has earned it: first the check shadows the person, then it passes clear cases and the person sees only flagged and unsure ones, then the person audits a sample. Movement is by measured agreement, and a drop moves a gate back. Freezing a kit stays a person's act. Publishing is the last gate to move and needs its own decision replacing ADR 0004 and 0007. At every level, paid spend stays within what the brief planned.

## Consequences

- A paid result can still be wrong. What is left to it is small, mostly what happens between two accepted frames or inside one accepted line, and the cost of a miss is one clip and one decision, never a loop.
- A piece takes more steps before it costs anything. The gates must be quick to pass, or the saving in money is spent in a person's time.
- The ladder does not raise a model's ceiling. It stops money being spent on top of a weak draft.
- Whether an accepted draft predicts an accepted final is not yet known for any kind. The first pieces through each ladder answer it, and a stage that does not predict is removed under rule 9.
- A model check still varies between runs. This decision does not make taste a number.

Building it is slices, each with its own tests:

1. A paid model makes only the planned takes (pull request 91).
2. A clean end, the bar's readings in song QA, and saying when no take passed (issue 93).
3. Decisions recorded with a reason and a preference (issue 94).
4. A trace of every call, so cost and time per stage are known (issue 87).
5. A measured identity check on stills and frames (issue 99).
6. Polish of one section of a chosen take (issue 98).
7. An autonomy level per gate (issue 97).
8. A paid step refuses to run without the accepted draft below it, starting with video and its animatic (issue 106). Each other kind adds its gate when it makes its first piece.
9. The model check asks yes-or-no questions, runs on stills before video, and uses a cheaper model (issue 105).
10. A video cut to a song is opened on a stream, so it carries the stream's kits (issue 104).

Nothing here names a genre, a brand, or a person. Limits and targets are numbers in config.
