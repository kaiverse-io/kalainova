# 0028. A paid song can follow a free draft

Status: built, not in use · 2026-11-19. Builds on 0016 (a free draft is accepted before anything is paid for) and 0023 (the engine speaks to models in its own terms). The code stays as a capability for a model whose guided route works. The comparison below was not met: the operator rejected both free drafts, and Mureka's guided routes on fal failed.

## Context

ADR 0016's ladder for a song settles the words, the tempo and the structure for free, and then pays for "a rented render of the same song file". The paid model got the text, never the draft's audio, so a groove or an arrangement the draft already had was thrown away.

Some rented song models take a track as an input:

- Mureka V9.5 on fal takes a `reference_id` from its own upload (`purpose: reference`; Mureka's docs: 30 s of mp3 or m4a, the rest trimmed).
- Mureka's `song/remix` takes a whole uploaded track (10 to 480 s) with complete lyrics and a style prompt.

Evidence before trying it:

- JASCO's own listening test (independent of us, by the model's makers): a reference raised melody match from 79.7 to 89.3 and drum match from 81.5 to 89.5. Overall quality barely moved, 83.3 to 84.1.
- No study tests a draft from one model guiding another.

## Decision

1. **A song brief may name a guide.** `brief.song_guide` is `{"job": <a song job of this studio>, "use": "reference" | "remix"}`. It needs `brief.song_model`, so the track goes only to the model named.
2. **The engine owns the guide; the provider only uploads it.** `song_guide.follow` opens the other job, checks it is finished and `owned` or `licensed`, and cuts the clip the model takes. A reference is cut on a bar where the most of the words are heard sung, with the chorus counting double. It is encoded bit-exact, so a rehearsal and the paid run send the same bytes.
3. **What a model takes is config.** `audio_models.<provider>.<model>.guide.<use>` names the upload model, its purpose, the payload field and the clip length. `needs_guide` marks a model that only works from a track. `Inputs.guides` reports them in the engine's terms, and a guide a model cannot follow is refused before anything is cut or sent.
4. **A signed payload binds the clip, not the vendor's id.** The id exists only once the paid run uploads, so the adapter seals it as the clip's bytes (`payloads.remember`), the same way an uploaded file is sealed.
5. **The upload is priced with the song, and is charged even when the song fails.**
   - `Billable.guided` adds the upload's price to the estimate, so an allowance's ceiling covers both calls.
   - The adapter closes the upload as a step on the call's receipt (`Receipt.step`), with its own request id and cost. The ledger row lists the steps, so each joins to its line on the vendor's bill.
   - When the call then fails without a bill of its own, the router still charges the steps, and does not hand the signed entry back. The first run found this: two uploads were billed and left no ledger row.
6. **A reference carries the sound alone on Mureka.** fal refused the first reference take with a 422, "prompt and reference_id cannot be combined in lyrics-to-song mode". Its published schema does not say so. The row's `style: false` sends the lyrics and the reference only.
7. **The record names both files by their hash.** `provenance.guide` holds the draft's final file and the clip by sha256, the draft's take, who chose it, its model, and the span.

## How it is judged

One planned comparison on one song file, against takes already made from the same `song.json`:

- 2 Mureka takes with a 30 s reference from a free ACE-Step draft;
- 2 Mureka remixes of that whole draft;
- the existing 2 Mureka, 2 MiniMax and 2 Lyria takes.

All are scored with the same readings and judges (`kalainova review <jobs> --judge`), and the operator listens. If guided takes do not score or sound better than unguided ones, this stays proposed and is not part of the default line.

## First runs, 2026-11-18

- **Reference, run 1:** refused with a 422 for sending a style with the reference. That is fixed by decision 6.
- **Reference, run 2, and remix, runs 1 and 2:** fal answered 500, "Downstream service error", from Mureka's side.
  - Each upload had returned an id, and fal billed it ($0.01, 1 billed unit).
  - Each clip was AAC at 48 kHz, of 30.0 s and 178.8 s, inside Mureka's limits.
  - Mureka's plain lyrics-to-song call, with no guide, made takes the day before.
  - No cause is published. The paid tries stopped there.
- 2026-11-19: the operator rejected both free drafts (ACE-Step 1.5 turbo), so no draft was left to follow. Nothing guided is planned until a vendor's guided route answers and a draft is accepted.

## Consequences

- A draft that cost nothing can carry its groove and arrangement into the paid take.
- The draft must be the studio's to use, and its model's terms must allow its output to feed a released piece. ACE-Step 1.5 is MIT, and its model card allows commercial use of output.
- A guide costs one more paid call, an upload priced in cents.
