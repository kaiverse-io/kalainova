# Consolidation

One engine. The subject is an input the operator writes on a job. It is not a kind of job.

Every playbook shared so far collapses to the same machine: make a piece of media, put it where a person can see it, write down what happened at 48 hours, then either repeat or stop. The pieces are video, audio, stills, text, or a mix. The playbooks disagreed about topics. They did not disagree about the machine.

## Three ways a piece starts

These are the only peers. Pick one for a job.

| Way | You have | Who pays | First proof |
|---|---|---|---|
| **Funded cut** | A brief and a source the funder is allowed to give you | The funder, per verified thousand views, until the pool is empty. The network you post on is not the payer. | One submission the funder is tracking |
| **Owned master** | A long file you already hold | Later, the network or a buyer. Slow. The file stays yours either way. | One public piece cut from that master |
| **Generated** | A script or a prompt, and a money cap | Unknown until the measure log says otherwise | One public piece, cost at or under the cap |

A job is one of these. It does not mix them.

## Same rules on all three

| Rule | Why it showed up everywhere |
|---|---|
| Rent the tool that makes the file. Own the job folder, the gate, and the log. | The tools change. The record of what shipped does not. |
| One identity per stream, one strategy per stream. | A funded post on an identity you want to keep stains it. |
| A human publishes. An agent drafts, calls the tool, and logs. | Nobody in the playbooks got paid for an unreviewed dump. |
| Check the first unit on a new character or format before scheduling more. A default, not a lock (ADR 0009). | The first rejection teaches the brief. The twentieth does not. |
| One to two posts a day on that identity. | Faster reads as spam. |
| Ten-minute hook veto. No timeline craft. | The time goes into the hook, not the cut. |
| Rights on the job: `funded-brief`, `owned`, or `licensed`. | A popular file is not a right. |
| Factual line in the script has a source on the job. | Unsourced claims are how a piece gets pulled. |
| Measure at 48 hours. Keep or kill from that number. | Views on the dashboard are the only feedback that mattered. |
| Loudness once on the final mix when there is audio. Default −14 LUFS, true peak at or under −1 dBTP. Short picture defaults to 9:16. | These are finish settings, not a brand. |
| No second procedural format or SKU until one job is `accepted` or `measured`. | Every early build pass ended with a schema and no file. |

## Funded cut, operating defaults

Score at least three briefs. Keep one for 14 days. Pass is 4 of 6:

1. Budget at least 40% remaining.
2. Rate at least 1.00 per thousand views, or a high per-piece cap.
3. The minimum view count is reachable on a new identity.
4. The brief lists a platform you can post on.
5. The source is fresh.
6. You have seen the URL submit flow.

Leave if budget is under 20% when you join, the first submission is rejected twice, or the first five posts are all under 500 views at 48 hours.

Earnings are verified views / 1000 × rate. A thousand a month at about 1.25 per thousand is on the order of 800 thousand to a million verified views. Arithmetic, not a forecast. A part-time result that has shown up in the field is a few hundred a month.

## Owned master and generated, operating defaults

Owned: rent a long-to-short clipper, upload a master you hold, veto hooks, schedule one a day. Do not point the clipper at someone else's upload.

Generated: three tests, money cap written down before the first render, its own identity, synthetic media declared where the platform asks. Open this only after one funded submission is tracking, or the job sets `skip_funded: true` on purpose.

Kill either if 14 days pass with zero public pieces.

## Extensions

Not peers. They do not open a new identity and they do not count as the first proof. They attach to a job that already exists, or they wait until one job is `accepted` or `measured`.

| Extension | What it is | When |
|---|---|---|
| **Text pack** | Title, description, teleprompter, shot card, carousel, thread | With any of the three. A job may be text only if that is the whole deliverable. |
| **Audio-native** | Voice, original music, or effects. The audio can be the piece, or a stem a picture job cites by id. No artist names. No melody you do not hold. | As the media of a job above, or as its own job after one proof exists. |
| **Procedural** | A data packet plus one format: `list`, `comparison`, `countdown`, `alert`, `poll`, `recap`, `quote`, `stat`. | After one format has a measured piece. One format at a time. No sample data in this repo. |
| **Downstream SKU** | A good that extends a piece. | Parent job is `measured` and `keep: true`. The call to action appears after the good exists. |

## Not in the engine

- Cutting a broadcast, a show, or a viral clip because it is getting attention, with no brief and no license.
- A comment-to-course funnel. The pattern is intel. It is not a way to make a piece.
- A worked example of a subject, checked in so the repo "shows how."
- One shared compiler on day one.
- Treating a green contract check as a shipped piece.

## Done

A directory `jobs/<id>/` in the private home, with a `measure.json` that records either an accepted funded submission or a public URL. Until that file exists, the engine is unproven, however many streams it can address.
