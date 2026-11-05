# Strategies

Loops for the plan in `docs/consolidation.md`. The premortem is `docs/explanation/adversarial-2026-11-05.md`.

Rank, after that premortem:

- **Peers.** Funded cut, owned master, generated, client. A job is one of these.
- **Extensions.** Audio-native, text pack, procedural, downstream SKU. Not peers. They do not count as the first proof, and procedural plus SKU stay shut until a job is `accepted` or `measured`.

The engine does not rank by topic. It ranks by whether a proof exists.

Current operating defaults (override on the job if the brief says otherwise):

- One strategy, one distribution identity.
- One funded source for 14 days before a second.
- One to two posts a day on that identity.
- Score a funded source at 4 of 6 before committing.
- Three generative tests, under a money cap, on their own identity.
- A downstream SKU only after a measured win on the media it extends.

## 1. Funded clip

Someone else holds the rights and has deposited a budget. You cut **their** long source into shorts, post on the platforms the brief allows, submit the post URL, and get paid per verified thousand views until the pool runs out. The network you post on is not the payer. The campaign is.

**When.** Fastest path to a paid unit. Use it when a funded brief exists that a new identity can join.

**Loop.**

1. Open the marketplace. Do not download a source that has no brief.
2. Score at least three candidates. Keep one. Pass is 4 of 6:
   - Budget at least 40% remaining.
   - Rate at least 1.00 per thousand views, or a high per-piece cap.
   - The minimum view count is reachable on a new identity.
   - The brief lists a platform you can actually post on.
   - The source is fresh, not a file everyone has already cut.
   - The submit flow is a URL in the dashboard, and you have seen it work.
3. Rent a clipper. Paste the allowed source URL. Take the top few by hook score.
4. Ten-minute veto. Fix a caption error. Do not recut on a timeline.
5. Post from the funded identity. Submit the URL the same day.
6. If the submission is rejected, read the brief and fix that post. Do not batch.
7. Log views at 48 hours. Leave a source whose budget falls under 20%, or whose first five posts all sit under 500 views.

**Money.** Earnings are verified views divided by 1000, times the rate. A part-time band that has shown up in the field is a few hundred a month. A thousand a month at about 1.25 per thousand is on the order of 800 thousand to a million verified views. Treat that as arithmetic, not a forecast.

**Account.** Dedicated identity. Never the identity you use for work you own.

## 2. Owned derivative

You already hold a long master (picture, sound, or both). Cut many shorts from it. Monetisation is the network's own program or a later brand deal, which is slow. The asset is yours either way.

**When.** You have masters and want a library, not a campaign cheque.

**Loop.**

1. Rent a long-to-short clipper. Upload a master you own. Do not point it at someone else's upload.
2. Keep the top hooks. Reject the rest. Fifteen minutes.
3. Schedule one a day. Two is the ceiling.
4. Log each post.
5. Only after 14 days of that schedule, consider replacing the rented clipper with this repo's compile path.

**Account.** A different identity from funded clip.

## 3. Generated

A prompt or a script packet becomes a new piece: voice, picture, captions, or any subset. Nothing is clipped from a third party. The payer is not a campaign. Treat revenue as unknown until the measure log says otherwise.

**When.** After strategy 1 has one **accepted** submission, or after you set `skip_funded: true` on the job and mean it.

**Loop.**

1. Write the script packet. Three hooks. Claims have sources.
2. Rent a generator. Render on a cap: three tests, and a money ceiling written on the job before the first render.
3. Post on a third identity, not the funded one and not the owned-master one.
4. Declare synthetic media where the platform asks.
5. Kill the loop when cost per piece times a month of posts is higher than anything the measure log supports.

Do not run a "comment a word, get a guide" call to action until the guide exists as a file.

## 3b. Client

The studio makes media for a business: ad creative, explainers, localization. The client supplies the brief, brand kit, and product material, and holds rights to the output (`rights: licensed`, contract reference in the job folder). The deliverable goes to the client, or posts to the client's own accounts with their approval. `distribution_identity` is the client label.

**Loop.** One pilot pack (3 to 5 pieces) at a fixed price, client review, then a monthly retainer. Track first-review acceptance per client.

## 4. Procedural

A data packet plus a format template renders the picture. The template is a machine for a **format**, not a subject. Formats the engine will grow, one at a time, after one of them has shipped:

`list` · `comparison` · `countdown` · `alert` · `poll` · `recap` · `quote` · `stat`

The data packet is part of the job. It is not a fixture in this repo. No sample dataset is checked in.

**When.** The piece is the same shape every time and only the data changes.

**Loop.** Put the data on the job, name the format, render locally, human gate, measure. Do not add a second format until the first has a measured unit.

## 5. Audio-native

Audio is a product, not a decoration on a video. A job with `media: ["audio"]` is complete when the file exists and the measure (listens, uses, or a downstream video that cites it) is logged.

Covers three outputs:

- **Voice** — narration or dialogue from the script packet.
- **Music** — original. Instrumental unless the job asks for voice. No artist names in the prompt. No melody you do not own.
- **Effects** — hits, beds, atmospheres, referenced by id from a video job's edit manifest.

Files stay on disk. The job stores the prompt, the model, the duration, and `rights: owned` (you generated it and the tool's terms allow that) or `rights: licensed`.

A video job may reference an audio job by id. That does not merge the two strategies. The audio job remains audio-native. The video job remains whatever strategy it declared.

## 6. Text pack

A job can ship with `media: ["text"]` and no picture: title, description, teleprompter, shot card, carousel slides, thread. Same gates. A factual line needs a source. Use this for the words that accompany another job, or as the whole deliverable.

## 7. Downstream SKU

A physical or digital good that **extends** a piece that already shipped. It is not a way to start.

**Open only when** the parent job is `measured` and `keep: true`.

**Loop.** One SKU. Human reviews every page or mock. Declare generated images where the printer or marketplace asks. The call to action in the parent piece appears after the SKU exists, not before.

## What is not a strategy

- Cutting a broadcast, a show, or a viral clip because it is getting views, with no funded brief and no license.
- Mixing funded posts onto an identity you want to keep as owned work.
- A comment-to-course funnel. File the pattern as intel. Do not build it here.
- A compiler, a scheduler, or a multi-job factory before one accepted or measured unit.

## Kill rules

| Signal | Action |
|---|---|
| Funded source under 20% budget when you join | Do not start |
| First submission rejected twice | Fix the brief, or leave the source |
| First five funded posts all under 500 views at 48h | Change source or hook, not the tool |
| 14 days, zero accepted submissions | Stop the rented clipper. Pick a source or close the strategy. |
| Generative cost above the cap | Stop rendering |
| 14 days, zero posts on an owned or generated identity | Close the queue. One piece or drop the strategy. |
