# Claude handover — Kalainova

Date: 2026-11-05. Written by Ben for the next agent (Claude) taking this repo. Operator: Kartik. Channel: Buzz `product-kalainova`.

This file is the brief. It is not engine doctrine. Proper nouns in the source map below stay in this file. Do not copy them into `README.md`, `AGENTS.md`, `ARCHITECTURE.md`, `docs/strategies.md`, `docs/consolidation.md`, schemas, or a sample job.

Read `HANDOVER_FEEDBACK.md` first, then `PREMORTEM.md`, before section 7. Section 7 stays frozen. The studio it describes is already on main, and the implementation review scored it short of a paying-client piece. Follow the order in `HANDOVER_FEEDBACK.md`. Do not add another cockpit plane.

Published remote: https://github.com/kaiverse-io/kalainova
Published `main` at the time of this handover: `8b59afe` (`8b59afe4679b9668682bc8c6b3c34544c0f5df5f`).

---

## 1. What Kartik asked for

In his words, condensed from the Buzz thread on 2026-11-05, nothing softened:

- The repo is the content generation engine Kalainova is supposed to be. It is not a vertical and not a niche.
- Media, audio, everything. Video, audio, stills, and text, alone or mixed.
- No references to a specific domain or segment in the engine.
- Strategies come from the playbooks and material he had already shared. Best of those, not a new invention and not a copy of one lane.
- Consolidate everything first. Then run the adversarial premortem already used on the lanes (the power.ai / Kahneman battery).
- The GitHub repo already existed and he made it public: https://github.com/kaiverse-io/kalainova. Push it. Use his `km2411` GitHub role, not the Cursor app bot.
- Then: "Is it setup like chassis? ai native +"
- Then: hand Claude a markdown file with the vision, the strategies, and the discussion, nothing left out, so Claude can turn the repo into an actual AI-native studio and content engine.

He has not asked for a Copier stamp, a Python service, a compiler, or a sample subject. Do not add those to "complete" the studio.

## 2. Vision

Kalainova is one engine and many jobs.

The subject is an input the operator writes on a job. It is not a kind of job, and it is not named in the engine docs. A sports cut, a facts short, a travel master, a generated explainer, and a canon episode are the same machine with different `job.json` files. If a sentence in an engine doc only makes sense for one of those, it does not belong in the engine doc.

Every playbook he shared collapses to the same machine: make a piece of media, put it where a person can see it, write down what happened at 48 hours, then repeat or stop. The playbooks disagreed about topics. They did not disagree about the machine.

Rent the moving half. Own the stable half. Generators, clippers, voices, music models, and schedulers are rented. The job folder, the gates, and the measure log are what this repo owns. That is Kartik's standing principle ("rent the moving half, own the stable half", 2026-07-31), applied here.

A schema is not a shipped frame. A green `just check` is not a piece. Humans publish. Agents draft, call the rented tool, and log.

Definition of done for the *engine*, already written in `docs/consolidation.md`: a directory `jobs/<id>/` that is not the template, subject written only there, and a `measure.json` that records either an accepted funded submission or a public URL. Until that file exists, the engine is unproven and the tree does not grow a compiler, a second format, or a SKU.

Definition of done for *this handover's ask* (the studio), which is different: the cockpit chassis actually runs, adapted to this content engine, on `main`. That work does not require a shipped piece, and it must not pretend one exists.

## 3. What is already on `main`

Commit `8b59afe`. Message: "Open Kalainova as a subject-agnostic content engine. Three ways a piece starts: a funded cut, a master you hold, or a generated piece. The tree stays put until one job is accepted or measured."

21 files. Root commit. No parent. The earlier local history that contained a third-party fixture was not pushed. Keep it that way.

| Path | Role |
|---|---|
| `README.md` | Product face. Subject-free. |
| `AGENTS.md` | Agent context. Points here. |
| `ARCHITECTURE.md` | Spine: intent → strategy → job → script/assets → edit → render plan → human gate → publish outside the repo → measure at 48h. |
| `NOTICE.md` | No third-party compositions. Operator media stays out of git. Facts carry sources. Rights are `funded-brief`, `owned`, or `licensed`. |
| `justfile` | One target: `check` → `python3 scripts/check.py`. |
| `scripts/check.py` | Stdlib gate. See section 6. |
| `docs/consolidation.md` | The operating plan. Read this before strategies. |
| `docs/strategies.md` | The loops, ranked so extensions are not peers. |
| `docs/pipeline.md` | Same spine for every medium. Who does what. Rent now / own later. |
| `docs/explanation/adversarial-2026-11-05.md` | Full 9-prompt premortem of the consolidation. |
| `schemas/*.schema.json` | `job`, `script_packet`, `asset_manifest`, `edit_manifest`, `render_plan`, `measure`. Draft 2020-12. `job` has `additionalProperties: false`. |
| `jobs/README.md` | One directory per piece. |
| `jobs/_template/` | The only job. `status: template`. `distribution_identity: null`. |
| `evals/README.md` | Slot reserved. Not a gate. |

There is no `.github/`, no pre-commit, no devcontainer, no skills, no hooks, no Codex rules, no prompt lint, no ADR, no how-to, no LICENSE, no CODEOWNERS.

`docs/explanation/adversarial-2026-11-05.md` still says this environment cannot see the GitHub repo and nothing has been pushed. That was true when the premortem was written. It is false now. Correct that paragraph when you touch the file. Do not treat it as the current remote state.

## 4. Strategies — nothing dropped

Full loops live in `docs/strategies.md` and `docs/consolidation.md`. This section is the decision record so a later edit cannot quietly restore a seven-way menu.

### Peers (a job is exactly one)

| Engine id | Plain name | You have | Who pays | First proof | Identity |
|---|---|---|---|---|---|
| `funded-clip` | Funded cut | A brief and a source the funder is allowed to give you | The funder, per verified thousand views, until the pool is empty. The network you post on is not the payer. | One submission the funder is tracking (`status: accepted`) | Dedicated. Never the identity used for work you own. |
| `owned-derivative` | Owned master | A long file you already hold (picture, sound, or both) | Later, the network or a buyer. Slow. The file stays yours either way. | One public piece cut from that master | Different from the funded identity. |
| `generated` | Generated | A script or a prompt, and a money cap written down before the first render | Unknown until `measure.json` says otherwise | One public piece, cost at or under the cap | A third identity. Not the funded one. Not the owned one. |

A job does not mix them. Variants (9:16, square, captioned, audio stem, text pack) are new files on the **same** job, same strategy, same identity.

Generated opens only after one funded submission is tracking, or the job sets `skip_funded: true` on purpose.

### Same rules on all three

- Rent the tool that makes the file. Own the job folder, the gate, and the log.
- One distribution identity per way. A funded post on an identity you want to keep stains it.
- A human publishes. An agent does not upload and does not submit a campaign URL.
- One unit accepted or public before a batch. The first rejection teaches the brief.
- One to two posts a day on that identity. Faster reads as spam.
- Ten-minute hook veto. No timeline craft before the first accepted unit.
- Rights on the job: `funded-brief`, `owned`, or `licensed`. A popular file is not a right.
- A factual line in the script has a source on the job (`script_packet.json` claims).
- Measure at 48 hours. Keep or kill from that number.
- Loudness once on the final mix when there is audio. Default −14 LUFS, true peak at or under −1 dBTP. Short picture defaults to 9:16. Overrides live on the job, not in a brand file.
- No compiler, scheduler, or second format until one job is `accepted` or `measured`.

### Funded scorecard

Score at least three briefs. Keep one for 14 days. Pass is 4 of 6:

1. Budget at least 40% remaining.
2. Rate at least 1.00 per thousand views, or a high per-piece cap.
3. The minimum view count is reachable on a new identity.
4. The brief lists a platform you can post on.
5. The source is fresh.
6. You have seen the URL submit flow.

Leave if budget is under 20% when you join, the first submission is rejected twice, or the first five posts are all under 500 views at 48 hours.

Earnings are verified views / 1000 × rate. A thousand a month at about 1.25 per thousand is on the order of 800 thousand to a million verified views. Arithmetic, not a forecast. A part-time result that has shown up in the field is a few hundred a month.

### Owned and generated defaults

Owned: rent a long-to-short clipper, upload a master you hold, veto hooks, schedule one a day. Do not point the clipper at someone else's upload. Kill if 14 days pass with zero public pieces.

Generated: three tests, money cap on the job before the first render, its own identity, synthetic media declared where the platform asks. Kill when cost per piece times a month of posts is higher than anything the measure log supports, or when 14 days pass with zero public pieces.

### Extensions (not peers, not the first proof)

They do not open a new identity. Procedural and downstream SKU stay shut until a job is `accepted` or `measured`.

| Engine id | What it is | When |
|---|---|---|
| `text-pack` | Title, description, teleprompter, shot card, carousel, thread. `media` is exactly `["text"]` when text is the whole deliverable. | With any of the three, or as its own job. |
| `audio-native` | Voice, original music, or effects. The audio can be the piece, or a stem a picture job cites by id. No artist names in the prompt. No melody you do not hold. Must include `audio` in `media`. | As the media of a job above, or as its own job after one proof exists. Citing an audio job does not merge strategies. |
| `procedural` | A data packet plus one format: `list`, `comparison`, `countdown`, `alert`, `poll`, `recap`, `quote`, `stat`. | After one format has a measured piece. One format at a time. No sample data in this repo. |
| `downstream-sku` | A good that extends a piece. Needs `parent_job_id`. | Parent is `measured` and `keep: true`. The call to action appears after the good exists. |

### Explicitly not strategies

- Cutting a broadcast, a show, or a viral clip because it is getting attention, with no brief and no license.
- A comment-to-course funnel. The pattern is intel. It is not a way to make a piece. Do not build "comment a word, get a guide" until the guide exists as a file, and do not build it as an engine strategy at all unless Kartik states a pivot.
- One shared compiler on day one.
- Treating a green contract check as a shipped piece.
- A salary / job-application track. It runs in parallel in the operator's life so content work does not eat the thing that pays the bills. It is not a Kalainova strategy. Do not encode it in this repo. The premortem's hour-cap risk is the only part that belongs here: content work has a weekly cap, and two weeks over the cap pauses content work.

### Job contract (schema 0.1)

`jobs/_template/job.json` today:

- `schema_version`: `0.1`
- `job_id`: `_template`
- `strategy`: `generated` (template only; a real job picks one peer)
- `media`: `["video", "audio", "text"]`
- `rights`: `owned`
- `distribution_identity`: `null`
- `status`: `template`
- `skip_funded`: `false`
- `cost_cap`: `null`
- `parent_job_id`: `null`

Status enum: `template`, `draft`, `rented`, `rendered`, `accepted`, `measured`, `killed`.

Only `job_id: _template` may use `status: template`. Any other status requires `distribution_identity`.

Folder shape (`jobs/README.md`):

```
jobs/<id>/
  job.json             required
  script_packet.json   when there is a script
  asset_manifest.json  when there are files on disk
  edit_manifest.json   when something is being cut or mixed
  render_plan.json     only after a compiler exists
  measure.json         after publish
```

Script beats use roles `hook`, `body`, `payoff`, `cta`. Claims need a `source`. Asset kinds are `video`, `audio`, `still`, `text`, and each asset has a local `path`. Bytes are not committed. Edit `runtime` is `rented-tool`, `ffmpeg`, or `remotion`. Render ops, when a compiler exists, are only: `cut`, `concat`, `scale`, `overlay_text`, `mix_audio`, `loudnorm`, `burn_captions`, `export`.

Pipeline actors:

| Actor | Does | Does not |
|---|---|---|
| Agent | Draft the packet, call a rented tool, write the job files, log the measure | Upload, submit a payout URL, invent a claim |
| Rented tool | Clip, voice, picture, schedule | Own the job folder |
| Human | Pick the strategy, approve, publish, submit | Edit a timeline by hand once the veto is enough |
| Cron, later | Remind, batch after proof, fan out variants | Decide the hook |

Two orchestration modes are both legitimate once a unit has shipped: an agent for judgement, a deterministic runner for a batch. Do not stand up the runner before the proof.

## 5. Premortem — the verdict you inherit

Battery, applied to the consolidation, not to a subject. Same nine prompts as the earlier lane pass: premortem, steelman, assumptions, second order, red team, verdict, adversary, blind spots, reconstruction. Full text: `docs/explanation/adversarial-2026-11-05.md`. Method source: an Instagram carousel from `@power.ai` (`DfI0YSOFXaV`) in the Kahneman premortem family, written up in the operator workspace before this recast.

**Verdict: YES-IF.** By day 14 there is one proof: a funded submission that is tracking, or one public URL of a piece from a master the operator holds or a generation he paid for.

Why the shape is still right: three ways in, one identity each, rent the file, own the log, human publishes, no unlicensed source. That is what the playbooks actually shared.

The hole: time, and a tree that cannot make media. The seven-way menu and the green check do not move either. The ranking in `docs/strategies.md` is the correction. Extensions are not peers.

Would flip the verdict: a new identity cannot get a funded brief accepted, and three public pieces each sit under 200 views with a real hook. Then stop. Do not add a format.

Confidence: medium. It hangs on the calendar, not on the document.

How the plan dies, ranked, so you do not rebuild the failure:

1. Menu, no unit. Seven strategies written as peers. Template is still the only job. The subject ban made a real job feel like a policy violation. A real job is allowed. Its subject lives only in `jobs/<id>/`.
2. The only runnable tree was deleted. Domain-agnostic became file-agnostic. Do not "fix" this by checking in a sample film. Fix the studio (section 7). The first frame comes from a real job the operator opens.
3. The check is the product. `just check` is green. There is nothing to watch or hear.
4. Two repos. Local history and GitHub history diverge. See section 8. This is the live risk.
5. Review ate the proof window. More docs make a zero-URL day 14 worse.
6. Every first step is outside the repo (a brief, a master on disk, a cap and a render) and none of them happened.
7. Extensions snuck in as strategy.
8. Tool invoices with no measure.
9. `distribution_identity` stayed null, so a post landed on whatever account was logged in.
10. Content work spilled past the hour cap and crowded out the obligation that keeps the lights on.

Steelman, keep it in view: do not build an engine. The playbooks already say rent a clipper or a generator, post, and write down the URL. A repository of strategies is how a month passes with no file. A single operator loses a volume game, and a schema does not change that. The plan survives only as one proof inside a hard hour cap, then a kill. The steelman wins if that cap is not held.

Hidden assumption that already burned us once: a subject-free contract is more useful than one shipped piece whose subject lives only in the job folder.

Reconstruction kills you must not merge past:

| Risk | Check | Kill |
|---|---|---|
| Dry brief | Budget remaining at join | Under 40%, do not join |
| No proof | Day 14 | No tracked submission and no public URL → stop writing engine docs |
| Scope | Any compiler, format, or SKU | Before a job is `accepted` or `measured` → do not merge it |
| Hours | A weekly cap on the calendar | Two weeks over the cap → content work pauses |
| Wrong repo | Does this token read and write `kaiverse-io/kalainova`, and is the branch the published root? | No → do not push |

The lane-by-lane premortem (before the recast) revised each lane the same way: one accepted submit or one public piece before any factory build; tool spend capped until a number exists; comment-to-course stays off unless Kartik states a pivot. The consolidated engine is that revision with the topics removed. Do not re-expand it back into lanes inside this repo.

## 6. The gate that exists

`python3 scripts/check.py` (also `just check`). Stdlib only. It fails if:

- Any git-tracked path ends in `.mp3`, `.mp4`, `.wav`, `.m4a`, `.mov`, `.webm`.
- A `jobs/*/job.json` breaks the contract in section 4 (schema version, strategy enum, media subset, rights, status, identity, procedural format, audio-native includes audio, text-pack media, downstream parent).
- An optional `script_packet.json`, `asset_manifest.json`, `edit_manifest.json`, `render_plan.json`, or `measure.json` beside that job is malformed. `measure.json` currently only requires `job_id`. Tighten it when the first real measure exists; do not invent fields for a piece that has not shipped.

It cannot tell you a piece is good, true, paid, or published. The adversarial doc is right about that.

## 7. AI-native studio — the chassis gap, and what to build

Kartik asked whether this repo is set up like chassis, "ai native +". Answer already given to him: partly. The cockpit files are on `main`. The gates chassis actually runs are not. It is not, and must not become, a Copier stamp of chassis's Python template. That stamp is the wrong language. There is no service here. The compiler is deliberately absent.

Chassis (`kaiverse-io/chassis`, look at `template/` and `docs/explanation/ai-usage-cockpit.md`) is the reference for planes, not for code. Adapt the plane. Do not copy the package.

| Plane | Chassis | This repo at `8b59afe` | What you add |
|---|---|---|---|
| Agent context | `AGENTS.md` | Yes | Keep it short. Point at this handover, the consolidation, and the strategies. Do not grow it into a procedure manual. |
| Architecture | `ARCHITECTURE.md` | Yes | Leave the spine. Fix any sentence that claims CI is already running. |
| One runner | `justfile` | Yes, `just check` | New gates become `just` targets. Agents and CI call `just`, not a pile of scripts. |
| Docs | explanation / how-to / decisions | Explanation, strategies, pipeline. No ADRs, no how-to. | Add `docs/how-to/open-a-job.md` and a few ADRs (below). Diátaxis, not a second strategy doc. |
| Eval that runs | A check in CI | `evals/README.md` only | Contract fixtures that must fail or pass. Not a sample film. |
| Pre-commit | Yes | No | Run `python3 scripts/check.py` plus a secret scan. |
| CI | Workflow that calls `just` | Written locally, rejected by GitHub | Put the workflow on `main` once the token has `workflow` scope. YAML is below. |
| Devcontainer | Yes | No | Python 3.12 and `just`. No extra services. |
| Skills, Claude hooks, Codex rules | Yes | No | One skill: open a job without naming a subject in engine docs. Hooks that remind, not a second policy. |
| Prompt / repo lint | opengrep | No | A lint that fails if engine docs outside this handover and outside `jobs/<id>/` grow a worked example. Exclude this file. |
| CODEOWNERS, LICENSE, release-please | Yes | No | LICENSE and CODEOWNERS are fine if Kartik wants them. Release-please is premature. Ask before adding a license; do not invent one. |

### ADRs worth writing (short, one decision each)

1. The subject is an input on the job, not a kind of job.
2. Rent the tool, own the job folder, the gate, and the log.
3. No compiler, second format, or SKU until one job is `accepted` or `measured`.
4. A human publishes. Agents stop at the gate.
5. Three peers. Extensions are not the first proof.
6. This repo is not a Copier Python service.

### Eval shape that does not fake a piece

`evals/README.md` says the directory stays empty until a measured job exists. That sentence is about a *content* eval. A *contract* eval is cockpit work and is allowed now:

- Keep `jobs/_template` as the valid job. `just check` must pass on the clean tree.
- Add fixtures of invalid JSON (bad strategy, media blob path, text-pack with video, procedural without a format, missing identity on a non-template job, render op outside the allowlist) that `scripts/check.py` must reject. Put them where the checker looks, or teach the checker a `--fixtures` mode. Do not give the fixtures a topic. Broken shape is the test.
- Do not add a golden video, a sample script about a real subject, or a `measure.json` with a made-up URL.

### CI workflow that GitHub refused

The `km2411` OAuth token on the machine that pushed `8b59afe` has `gist`, `read:org`, and `repo`. It does not have `workflow`. GitHub rejects any push that adds or updates `.github/workflows/*` with: refusing to allow an OAuth App to create or update workflow without `workflow` scope.

Do not "solve" that by deleting the gate, by committing the workflow under a different filename and hoping, or by putting a token in the remote URL. Get `workflow` scope (Kartik completes a device login that requests it) or have someone who already has it push this file as `.github/workflows/ci.yml`:

```yaml
name: ci

on:
  push:
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: engine contract
        run: python3 scripts/check.py
```

When you add targets, the last step becomes `just check` (install `just` in the job). Until the file is on `main`, say in the README that Actions is absent. The README on this commit already says that.

### What "studio" does not mean

- Not a Python package, not FastAPI, not a Copier copy of chassis `template/`.
- Not `compile.py`, ffmpeg orchestration, or a Remotion app in this PR. Those are the owned half *after* a rented job has an accepted or measured unit. `edit_manifest.runtime` may name `ffmpeg` or `remotion` later. Naming them in a schema is not permission to build them now.
- Not a sample subject "so Claude can see it work."
- Not restoring the third-party fixture that was removed.
- Not a scheduler, a Buzz bot that posts, or an agent that submits payout URLs.
- Not seven strategy docs rewritten as peers.
- Not importing operator media, 4K masters, or publish queues into git.

### Order of work

1. Read this file, `docs/consolidation.md`, `docs/strategies.md`, `docs/explanation/adversarial-2026-11-05.md`. Confirm `git rev-parse HEAD` on the branch you will push is `8b59afe` or a descendant of it that does not contain the fixture history.
2. Add the cockpit planes that do not touch `.github/workflows/`: pre-commit, contract fixtures, how-to, ADRs, devcontainer, one skill. Run `python3 scripts/check.py` and the fixture tests.
3. Tell Kartik CI is still blocked on `workflow` scope, with the exact yaml above, if you cannot push it.
4. Stop. Do not open `jobs/<some-topic>/` yourself. The operator opens the first real job, on his machine, because the brief, the master, and the publish login are his. Cloud agents cannot join a marketplace, upload, or submit.

If he later says "open the first job," the job folder gets the subject and the engine docs do not.

## 8. Git — read this before you push

Two histories exist on the operator machine. Only one is public.

| Ref | Commit | Safe to push? |
|---|---|---|
| `origin/main` and local `publish-clean` | `8b59afe` | This is GitHub `main`. Descendants of this commit are the only history to push. |
| local `engine-root` | `cbc3508` | Same tree as `8b59afe` plus `.github/workflows/ci.yml`. Pushing it fails until the token has `workflow` scope. A later commit that only deletes the workflow still fails if the parent that adds the workflow is in the push. |
| local `main`, `archive/pre-publish`, `consolidate-premortem` | `f778f64` | Do not push. Ancestry includes `1587ce6`, a third-party fixture stamp that was removed in `513f00a`. That history must not become public. The fixture had no LICENSE. |
| local `engine-domain-agnostic` | `513f00a` | The recast. It is an ancestor of the bad `main`, not of `8b59afe`. Do not push it. |

`8b59afe` is an orphan root. It is not a descendant of `f778f64`. Do not merge the two. Do not force-push `main` over `8b59afe`.

Auth that worked:

- The Cursor app's `gh` user is `cursor`. That token is `cursor[bot]`. It cannot push this repo (403, permissions false).
- `~/.gitconfig` on the build machine rewrites `github.com` URLs to that installation token. `git remote -v` can look as if a token is in `.git/config` when the file itself is clean. Do not edit the global git config. Do not print that token. Do not put any token in a remote URL or in this repo.
- `km2411` device-login state lived in `GH_CONFIG_DIR=/tmp/gh-km2411` on the build machine. Scopes: `gist`, `read:org`, `repo`. Missing: `workflow`. It may be gone on a new machine. Do not paste a personal access token into Buzz.
- Push command that worked, from a clean `https://github.com/kaiverse-io/kalainova.git` remote:

```bash
GIT_TERMINAL_PROMPT=0 \
GIT_CONFIG_GLOBAL=/dev/null \
GIT_CONFIG_SYSTEM=/dev/null \
GH_CONFIG_DIR=/tmp/gh-km2411 \
git -c credential.helper='!gh auth git-credential' \
  push origin HEAD:main
```

`GIT_CONFIG_GLOBAL=/dev/null` is required so the cursor rewrite does not replace `km2411`. `GIT_TERMINAL_PROMPT=0` is required because there is no TTY; without a credential helper, git asks for a username and dies with "could not read Username for 'https://github.com': No such device or address".

Commit identity on that machine was `Cursor Agent <cursoragent@cursor.com>` from git config. Read `user.name` and `user.email` before you commit. If email is empty, stop and ask. No required commit trailer was found for the commits that landed. The fixture stamp had a `Co-authored-by` trailer; the published root does not. Do not add trailers you have not verified the repo requires.

Local checkout note: `/workspace/REPOS/kalainova` was left on `engine-root` (`cbc3508`) after the push. This handover was written on a worktree of `publish-clean` so the workflow file would not ride along. If you continue there, branch from `8b59afe`, not from `engine-root` and not from local `main`.

## 9. Source map — operator workspace only

These are the materials the consolidation was drawn from. They live in the operator's agent workspace, not in this repo. They name verticals, channels, and tools on purpose. Use them to understand why a rule exists. Do not import their topics, their sample scripts, or their queue into Kalainova.

| Workspace path | What it contributed |
|---|---|
| `GUIDES/KALAINOVA-SHORTS-GET-STARTED-v6-2026-11-04.md` | Lane plan: funded campaign clips, owned long-to-short, generated explainers, a canon series, a later physical/digital good. Day-by-day. Rent now, own the factory later. |
| `GUIDES/CLIPPER-CAMPAIGN-PLAYBOOK.md` | 14-day operator SOP for one funded source. Scorecard, fresh identity, URL submit the same day, 48h log. |
| `RESEARCH/strategy-consolidation-report-2026-11-05.md` | Ranking across those lanes plus a salary track and a comment-to-course lane that was filed as intel. Math for the funded rate. |
| `RESEARCH/kalainova-content-pipelines-premortem-2026-11-05.md` | Lane-by-lane failure stories. The "schema = product" and "build the factory before a submit" failures. |
| `RESEARCH/kalainova-power-ai-prompt-battery-2026-11-05.md` | The nine prompts. |
| `RESEARCH/shorts-automation-playbooks-2026-11-04.md` | Rent-versus-own tool map (clipper, long-to-short, script-to-picture, generative). |
| `RESEARCH/clipper-campaign-references-2026-11-04.md` | Marketplace references and the note to skip the course funnel. |
| `PLANS/content-engine/` | Older engine sketches, including a character mark and topic-specific schemas. Do not copy those schemas in. The job contract in this repo replaces them. |

How those lanes became engine ids:

| What he had been calling it | Became |
|---|---|
| Funded marketplace clipping (campaign CPM, one source for 14 days, fresh account) | `funded-clip` |
| Owned long master cut into shorts | `owned-derivative` |
| Generated explainers, after one funded proof or an explicit skip | `generated` |
| Script packs, titles, teleprompters, carousels | `text-pack` |
| Voice, original music, effects as their own product | `audio-native` |
| Same-shape pieces where only the data changes | `procedural` |
| A good that extends a piece that already measured well | `downstream-sku` |
| Comment-a-word course funnel | Not a strategy |
| Salary / applications | Not in this repo |
| "Replace the rented clipper with our own compiler" | Later, after proof. Not this studio pass. |

Tool brands in those guides (clippers, generators, schedulers) are the rented half. You may name one in a job folder when that job actually calls it. You do not pin the engine to a vendor.

Other operator context that is easy to get wrong:

- The channel canvas in Buzz `product-kalainova` is still an older shorts-lane board (canvas event `17fe94a5…`, last modified 2026-11-04). He was told. He did not ask to rewrite it. Leave it unless he asks.
- Ideas and positions stay in the operator's agent workspace. Specs and code stay in this repo. If you write a design, write it here, not into his knowledge base.
- Publish, marketplace join, and account login happen on his machine. A cloud agent that cannot open the browser cannot complete the day-14 proof. Say so. Do not fake the URL.

## 10. First session checklist

- [ ] `git rev-parse HEAD` is `8b59afe` or a descendant that does not contain `1587ce6`.
- [ ] `python3 scripts/check.py` prints `check ok` before you change anything.
- [ ] You have read sections 4, 5, and 7 of this file.
- [ ] Cockpit additions are gates, docs, and harness files. No sample subject. No compiler. No workflow file unless the token has `workflow` scope.
- [ ] Engine docs outside this file still contain no vertical, niche, brand, creator, or topic.
- [ ] You tell Kartik what landed, what is still blocked (CI scope, if so), and that the first real job is his to open.
