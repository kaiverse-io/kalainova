---
name: rehearse-before-the-first-paid-run
description: Tests with faked vendors passed while a real job's dry run found ten defects in the quote, the gate and the payloads; rehearse a new route before its first paid call
metadata:
  type: feedback
---
Every adapter had tests against a faked vendor, and they all passed. Then `kalainova rehearse` ran one real song-video job through its paid stage with nothing sent, and found ten defects that no test had reached. Some of them:
- the visual cues were the genre text;
- the shot-length ceiling skipped lyric cuts;
- with no key set, the quote read $0.00 and the animatic gate turned itself off, because both asked which provider was *available*, not which one was *listed*;
- one model was priced at the capability's rate instead of its own;
- a `seed` field went to four models whose schema has none;
- the animatic and the song-video quotes disagreed, and both left out the stills.

A fake only answers the questions its author thought to ask. A rehearsal answers what the job actually builds: every field of every request, checked against the vendor's live schema with `scripts/check_fal_schemas.py --rehearsal`.

**Why:** a paid call can't be taken back, and a wrong quote or an inactive gate costs money before anyone looks.

**How to apply:** before the first paid run of a new stream, route or model, run `kalainova rehearse <job>` with no key in the environment, then the schema check on its `rehearsal.json`. Read every line it prints: the estimate per call, whether each take was given its start frame, and the gate. Any quote or check that has to know the price must use `router.price` or `router.first_listed` (the provider the job lists), never the provider that happens to have a key. See [[drive-a-command-before-calling-it-done]].
