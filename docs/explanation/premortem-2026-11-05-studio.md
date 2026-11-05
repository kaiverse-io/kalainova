# Adversarial premortem: studio, editing arm, stock reels (2026-11-05, evening)

The battery is the same one used in `docs/explanation/adversarial-2026-11-05.md`. The plan under test is the morning's 21-file contract after one day of growth. It now has a rented-model generation engine with local fallbacks (ADR 0007, merged to `main` in PR #2, though its text still says "proposed"), a keynote-grade theme (`41fb857`), an editing arm (`b662394`), and free stock reels (`64f00f6`, `kalainova reel <id> "<place>"`). In total that is +7,395 lines across 168 files since `8b59afe`. There are zero jobs besides `_template`, zero real renders and zero URLs. The day-14 proof is due 2026-11-19.

## 1. Premortem

It is May 2027. Kalainova made no money. How it died, ranked:

1. **The engine became the job.** Every session added a capability (theme, director, stock, long-form) because adding things was easy and shipping needed the operator's logins. 11-19 passed with no URL. The morning's kill rule ("stop writing engine docs") was read as covering docs only, and code kept merging.
2. **The stock reel was the only thing that ever ran end to end.** The output was a stock-montage channel: Pexels clips, Lyria music, Inter captions, one "travel" identity called `stock-reels`. YouTube's reused/inauthentic-content rules and Meta's unoriginal-content rules hit it at the channel level. It was never monetized and its reach was throttled. The showroom showed the very thing buyers can get for free.
3. **"Apple quality, no compromises" became an unfalsifiable gate.** No render ever met the bar, so nothing was approved and `approve` was never run. Perfection was used as a way to avoid finding out.
4. **The first real keys broke the line.** Every test ran on `providers/local.py` in a sandbox with no network and no GPU. The fal slugs, the Pexels endpoints (the code already guesses between two URLs), the ElevenLabs timestamp shapes and the Upload-Post AI-label field (`publish` refuses without it) all needed fixing on the first live day. Then the Wan or Seedance budget, at 3–5 attempts per usable shot, ate the cap.
5. **Client work was never sold.** `studio.md` ranks UGC ads and dubbing first. No outreach list, price sheet or spec ad was ever made. The studio was built for a client nobody had named.
6. **The doctrine contradicts itself.** ADR 0003 is "accepted, amended by 0007 when accepted". 0007 merged but still reads as proposed. The handover says "no compiler" and `main` ships one. A new agent can't tell which rule binds, so the rules bind nothing.
7. **A licensing incident.** A "people walking" or skyline clip showed an identifiable person, a logo, or a shot a third party had registered with Content ID. The result was a claim or strike on the one identity that had history.
8. **The fourth identity.** `reel` defaults to `--identity stock-reels` under `owned-derivative`. That makes a fourth identity for work the operator doesn't own, which breaks the one-identity-per-way rule in spirit.
9. **The hour cap was never written down**, so content crowded out the obligation that pays.

Earliest sign: by 11-12 there is still no `jobs/<real-id>/` holding a real key, real footage, or a real brief.

## 2. Steelman (against building more)

The tree can already make a 1080×1920 frame at −14 LUFS with QA. Failure 2 from the morning premortem ("a tree that cannot make media") is fixed. Every line written after that point works on a guess about what a buyer or an audience wants, made before either has seen a frame. Marginal code is now worth less than one rejected spec ad, because a rejection is data and code isn't. A UGC ad buyer judges hook, product and face. Nobody is paying for a light ribbon with smoothstep easing. Stock reels are the opposite of a moat: anyone with CapCut and the same free API has the same clips. **Strongest point:** the bottleneck is not the engine. The bottleneck is that the operator hasn't put a key, a clip or a pitch into it, and no commit changes that.

Counter: one real job needs the edit arm (operator footage) or the generator (UGC). Both exist now. The steelman wins only if building goes on past tonight.

## 3. Assumptions

| Assumption | Likely wrong? | Test (by when) |
|---|---|---|
| Local-fallback renders predict real-key renders | High | M1: 3 renders on real keys, QA pass (11-08) |
| Stock-montage reels are monetizable or build an audience | High | Don't test on an owned channel. Read YPP "reused content" and Meta "unoriginal content" against one sample. If a reviewer could call it a compilation, it is one |
| Pexels/Pixabay licences cover commercial client ads | Medium | Read both licences and the Pexels API terms (link-back requirement) line by line for: people, logos, "unaltered" and endorsement |
| A DTC brand pays $200–375 for an AI UGC ad from a new studio | High | 3 spec ads sent to 10 named brands; 1 paid by day 30 |
| "Apple quality" is what wins the sale | Medium | Ask the first 3 prospects what they rejected, and log the reason labels |
| Inter Display is installed where rendering happens | Unknown | `fc-list | grep -i inter` on the render box. libass silently falls back to another face |
| the operator has hours this fortnight | Medium | Write the weekly cap on the calendar today |
| Owned footage exists on disk | Unknown | Point `ingest` at one real folder tonight |

## 4. Second order

| If | Then |
|---|---|
| A place reel gets reach | Pressure to make "every city". Mass-produced templated output is the exact inauthentic signal, and the channel is judged as a whole |
| The theme becomes the house look | Every client piece looks the same, and client brand kits (M3) fight the theme |
| Real keys go in with "no spend limit" | 3–5 attempts × $0.20/s video means a 30 s piece costs $18–30 before review. Margin vanishes on a $200 ad |
| The edit arm works well on operator footage | That's the real asset. Owned-derivative from real masters is authentic by construction |
| More engine merges before 11-19 | The kill rule loses credibility, and the next rule gets ignored too |

## 5. Red team

- **Platform rules.** Stock B-roll plus TTS plus music plus captions is the textbook "low-effort, reused" pattern. Adding credits in the description doesn't make it original. It documents that the footage isn't yours.
- **Content ID.** Popular free clips are sometimes re-registered by third parties. A claim lands on a reel the operator can't defend quickly.
- **Licence edges.** Pexels and Pixabay forbid selling unaltered copies and implying endorsement, and both put trademarks and identifiable people outside what they grant. Using people in an ad for a client's product is the riskiest case. The Pexels API terms also expect a visible credit or link back from the app that uses the API. `credits()` writes "Video by X on Pexels" to the description only. Instagram captions (2,200 characters) can truncate it, and nothing checks that the credit survived.
- **Rights label mismatch.** `reel` sets `rights: licensed` on an `owned-derivative` job. QA's `rights.assets` check passes anything labelled `licensed`. The label is asserted. Nobody verifies it.
- **Synthetic flag.** Mixed stock and generated cuts need a correct per-asset `synthetic` flag, or QA's disclosure check passes without the label.
- **Sandbox illusion.** "QA passed" so far means DejaVu text over synthetic test patterns.

## 6. Verdict

**YES-IF**, narrowed. Freeze the engine tonight. The only work until 11-19 is: (a) one real-key render that meets M1, and (b) one of these two:
- 3 spec UGC ads in front of named prospects, or
- one public piece cut from the operator's own footage on its own identity.

Stock reels are allowed **only** as client deliverables, where the client has a use for them and the licence was checked, or as private pitch samples. They never go on an owned or monetized channel.

**Why the shape survives.** Human-approval bound to a hash, cost caps, sourced claims and the AI label are the right guardrails. Client-first is the right order.

**Flip to NO (stop and go back to the salary track)** if any one of these happens:
- No URL and no tracked submission by 11-19.
- Zero replies from 10 prospects by day 30.
- Real-key cost per approved piece above 30% of price.
- Any further engine merge before a job reaches `accepted` or `measured`.

**Flip to strong YES** if one paid invoice arrives, or one owned piece beats 1,000 views at 48 h with an AI label on.

**Confidence:** medium-low. The code is real, but nothing it does has been tried with a real buyer or a real audience.

## 7. Adversary

| Who wins | How |
|---|---|
| Free stock libraries and CapCut templates | They own the same clips, and their users get them for free |
| Platform integrity teams | A templated stock channel is an easy enforcement win |
| Model vendors | They bill retries on "no compromises" shots |
| Agencies with a portfolio | They close the UGC brand while Kalainova polishes its theme |
| the operator's paying obligation | It loses hours to commits |

## 8. Blind spots

1. Authenticity is a *channel* property. One stock week can taint a later real-footage channel if it's the same identity.
2. Client contracts need a rights warranty and an indemnity clause. Free stock gives no indemnity.
3. Music: Lyria or ElevenLabs output terms for commercial client ads are unread.
4. Cross-border invoicing and tax (named in `studio.md`) are still unresolved, and the first payment will be blocked by them.
5. Vertical reframing of 16:9 stock to 9:16 crops logos and faces unpredictably.
6. Long-form auto-cutting of the operator's speech can change meaning. The claim-source QA checks scripts, not ingested speech.
7. Nobody has defined what "Apple quality" looks like as a checkable rubric.
8. The doctrine docs (`CLAUDE_HANDOVER.md` §7 "no compiler") are now false, and agents will keep re-litigating them.

## 9. Reconstruction: kill checks

| Risk | Check | Kill / action |
|---|---|---|
| Scope creep | Any merge to `kalainova/` before a job is `accepted` or `measured` | Don't merge. Bug fixes from a real-key run only |
| Inauthentic content | Is >50% of the runtime third-party stock on an owned/monetized identity? | Don't publish. Stock is for client or private use only |
| Licence | People, logos or landmarks-with-brands in a stock clip, on a client job | Drop the clip, or get a release. Store the licence URL and a snapshot in `stock.json` |
| Attribution | Did the credit line survive in the posted caption? | Add a QA check, or don't post |
| Sandbox illusion | Has the render used ≥1 real provider? | M1 not met: don't call anything "studio quality" |
| Perfectionism | Days since a piece reached `rendered` without `approve`/`reject` | More than 3 days: ship or kill with a reason label |
| Cost | Real cost per approved piece vs. price | Over 30%: switch to the budget stack or stop that offer |
| No proof | 11-19 | No URL and no tracked submission: stop engine work and pause content |
| Doctrine drift | Do 0003/0007 status and handover §7 agree with `main`? | Fix the text before the next session, or the next agent will re-argue it |
| Hours | Weekly cap on the calendar | Two weeks over: pause |

## Five next actions, in order

1. **Freeze the engine tonight.** Mark 0007 as accepted and 0003 as superseded. Add one line to the handover saying the compiler now exists and the freeze holds until the first job reaches `accepted` or `measured`. After that, no feature commits.
2. **M1 on real keys (by 11-08).** Set Anthropic, ElevenLabs and fal keys, plus one of Pexels or Pixabay. Render three pieces: one from the operator's own footage through `ingest`/`edit`, and two UGC-style generated spec ads. Log real cost per approved piece. Fix only what breaks.
3. **Name 10 prospects and send 3 spec ads (by 11-12).** These are DTC or local brands, with one of them in tourism or hospitality if place reels are the pitch. Open a `client` job per prospect with a price. Log each reason for rejection.
4. **Publish one owned piece from real footage (by 11-19),** on a named identity with the AI label set if anything in it is synthetic. Write `measure.json` at 48 h. That is the day-14 proof. A stock reel does not count.
5. **Write the quality bar as 5 checkable lines and the hour cap on the calendar.** Example lines: hook within 1.5 s, no visible artifacts at 100% zoom, brand-safe frames, WER ≤ 3%, a reviewer would post it. Anything past those five is a v2 request from a paying client.
