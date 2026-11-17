# 0023. The engine speaks to models in its own terms

Status: accepted · 2026-11-16. Builds on 0019 (self-hosted models). 0022 (signed packages) is built on it.

## Context

A vendor can change its fields, prices or terms, or close. The engine must survive that by changing one adapter and its config rows, and nothing else.

Before this decision, the shape was right: one router, one adapter per vendor, and model ids and field names in `config/studio.yaml`. What crossed the boundary was not.

- **Requests were loose.** Every call was positional arguments plus a `**kw` bag (`references`, `image`, `end_image`, `seed`, `model`, `task_type`). An adapter read the keys it knew and dropped the rest without a word. The router found the output file by its position in the arguments.
- **Results were a bag.** The engine read adapter-chosen keys out of `Result.meta` (`start_frame_sent`, `seed_sent`, `hits`, `seed`). An adapter that left one out made the review page drop its warning.
- **Call details travelled on the adapter object.** The router wrote `tags` onto the provider instance and read `request_id`, `charged` and `billed_units` back after the call. An adapter that forgot them lost the vendor's id and the bill check, and nothing said so.
- **The safety work lived in one adapter.** Rehearsal, schema checks, list prices, billed units, labels and uploads were coded into `fal.py`, and `rehearsal.py` read fal's payload fields. ElevenLabs and Anthropic could not rehearse and returned no request id.
- **Engine code reached into adapters.** `rehearse.py` imported `fal`, and `research.py` imported a constant from the search adapter.
- **The engine chose vendor model ids.** QA and the still check read the first listed provider's judge model from the config and handed it to every provider, so a fallback vendor could receive another vendor's model id. A stream's pinned model went to every listed provider the same way.
- **Vendor errors were not sorted.** A 422 (our payload was wrong), a 429, a 5xx and a refusal all moved on to the next paid provider.

## Decision

Ports and adapters, with an anti-corruption layer on both sides of each vendor.

1. **One typed request per capability** (`providers/contract.py`): `TextRequest`, `JudgeRequest`, `VoiceRequest`, `ImageRequest`, `VideoRequest`, `MotionRequest`, `MusicRequest`, `SfxRequest`, `SongRequest`, `TranscribeRequest`, `LipsyncRequest`, `SeparateRequest`, `GraphicsRequest` and `SearchRequest`.
   - They are frozen dataclasses with named fields. A field an adapter does not know is a type error.
   - Each names its capability and its output files, and says what it is priced on (`Billable`). Callers no longer pass a separate estimate.
   - Each computes its content key. The key keeps the form it has had since keys were first written, so a file paid for before this change is still reused (`tests/test_request_keys.py` pins it).
   - A model choice is a `Pin` (provider and model). The router hands the pinned model to the provider it names and to no other, so a fallback uses its own default.
2. **One typed result.**
   - `Result` carries the engine's facts as fields: `seed`, `sent` (start frame, end frame, seeded), `billed_seconds`, `hits`, `words` and `version`.
   - The router writes them into a file's record under the engine's own names (`contract.RECORDED`).
   - `meta` is provenance only. An adapter cannot write the engine's names there: the router strips them.
3. **A context per attempt.** The router hands each call a `Context`: the job, the attempt id, the labels, the pinned model and the deadline. Its `Receipt` is filled by whoever learns its parts (request id, billed units, vendor cost), so a failed call keeps them.
4. **Capabilities in the engine's terms.**
   - `Provider.inputs(capability, model)` returns `Inputs`: references, characters, the start frame apart from references, the end frame, seed, the longest output and repaint. It replaces `reference_support` (a vendor spec dict), `takes_end_image`, `supports_song_repaint` and the router reading `audio_spec`.
   - `Provider.models(capability)` lists what a provider offers. `Provider.default_model` names its default.
   - Only `providers/` reads the config's vendor field names.
5. **A transport per vendor platform** (`providers/transport.py`). `send`, `upload` and `fetch` belong to the transport, so every adapter that uses one gets the following:
   - rehearsal, paired with the router's call by attempt id;
   - the receipt;
   - labels where the vendor takes them;
   - an HTTP failure as `InvalidRequestError`, `UnauthorizedError`, `RateLimitedError` or `UnavailableError`, keeping what the vendor said;
   - `BilledError` for a file that never arrived after the vendor finished;
   - the vendor's schema check (`problems`) and list price (`list_price`).

   `FalQueue` is fal's transport. `Https` serves Anthropic, ElevenLabs, Exa and the OpenAI-compatible vendors, so all of them now rehearse and return a request id. A stand-in's shape comes from the engine's request, never from a vendor's fields.
6. **A malformed request stops the walk.** On `InvalidRequestError` the router releases the reservation and stops, naming the vendor's words. It does not spend on the next provider, because the engine's mapping is at fault.
7. **Enforced, not hoped for.**
   - An import-linter contract (`vendors-stay-behind-the-port`) lets only `providers/` import an adapter or the transport.
   - `tests/boundary/test_provider_contract.py` is the suite every registered adapter must pass. Each capability it declares is the engine's and takes a request and a context. It prices and describes each in the engine's terms. A paid one reaches its vendor only through a transport. Rehearsing each paid capability sends nothing, writes the vendor request under the router's attempt, makes the file the engine asked for, and leaves the engine's record names alone.

## Consequences

- **Swapping a vendor** means a new adapter (a transport for its platform, and a mapping per model family) plus config rows. The contract suite says when it is complete. Neither the engine's stages nor its records change.
- **Every rented vendor rehearses.** A rehearsal's quote now includes the judge and check calls that the real run pays for, which it used to leave out.
- **Price corrections** apply to each provider's default model too, not only to pinned ones.
- **A stream's pinned model, or a kit's voice model,** reaches only the provider it names.
- **Keys are unchanged** for every production call shape. The dub flow's voice and lip-sync keys change once, because its arguments were not shaped like the rest. Those calls have no paid files on record.
- **Two modules leave the debt lists:** `providers/base.py` and `providers/router.py` now pass strict typing and every lint rule.
- **The signed packages of 0022 can be built on this.** A package signs the typed request (what a person approves) and the vendor payload's digest (what the transport sends).

## Alternatives considered

- **A shared SDK such as LiteLLM.** It covers language models only. Media generation has no common SDK, and fal is itself the aggregator. A transport per platform keeps a move from fal to another aggregator to one module.
- **Pydantic models for requests.** Validation at the boundary is welcome, but frozen dataclasses with `mypy --strict` give the same safety with no new dependency.
- **Keeping `**kw` with a list of allowed keys per adapter.** That checks spelling and leaves the coupling in place.
