---
name: a-host-must-not-change-the-request
description: Two hosts of one song model built different requests, a pronunciation hint rode only on the first chunk, and a retired route was found only by a paid submit; build each request once per model family, put a hint where its word is sung, and refuse a 410 route before spend
metadata:
  type: feedback
---
Three faults showed up in one day of song work.

1. **The host changed the request.** ElevenLabs' own adapter built its composition plan by line counts, with the whole style on every chunk. fal's route to the same model used `song_text.plan`. Moving a model to another host would have changed what it was asked.
2. **A pronunciation hint reached the wrong chunk.** `pronounce` rode inside the style, and a plan sends the style on its first chunk. A second-language word in the pre-chorus was sung as an English one.
3. **A dead route looked alive.** A vendor's catalog listed a song route that answered 410 to a paid submit. The submit billed nothing, but it was found only by spending a sign-off on it.

**Root cause:** each adapter wrote its own request, and nothing held one model family's request to one builder. A per-section direction travelled at song level. A 410 was an ordinary "unavailable" error and was forgotten after it happened.

**Fix (ADR 0035):**
- every host of a model family builds the request in one place: `song_text.plan` for composition plans, and `fal_song` by host for Mureka's form;
- `pronounce` goes on the chunk whose lines sing the word (`song_text.sung_here`);
- an HTTP 410 is `RetiredError`, written once to the studio's `retired.json` and refused before pricing or sign-off (`providers/retired.py`). A config row can say `retired` and `instead`.
- Tests: `tests/test_elevenlabs.py`, `tests/test_song_file_to_release.py`, `tests/test_retired.py`, `tests/test_mureka.py`.

**How to apply:** when adding a host for a model, reuse that model family's builder, and test that both hosts send the same payload. A direction that belongs to one section travels with that section. After a vendor's 410, check `retired.json` rather than retrying.

**Status:** the code is proved by tests. Whether the per-chunk hint changes how the word is sung is unproved; the next paid comparison settles it.
