---
kind: plan
status: active
last_reviewed: 2026-11-05
---

# Kalainova AI Studio — the goal and the road to it

## The goal

**An AI-native studio that turns a one-line brief into publish-ready media (video, audio, stills, text) at a quality a paying client accepts on the first review, and posts it after one human tap.**

Measured by three numbers, nothing else:

| Metric | 30 days | 90 days |
|---|---|---|
| First-review acceptance (human approves without a re-render) | ≥ 60% | ≥ 85% |
| Revenue per month | first paid invoice | ≥ $8K MRR |
| Brief → approved piece, wall clock | < 30 min | < 10 min |

"Most powerful" means those three move, not that the feature list grows. Cost per piece is tracked on every job (`ledger.json`) and capped (`cost_cap`).

## Where the engine is (v0.2, 2026-11-05)

Working and tested (`just test`, 33 tests, one is a full render):

- `python3 -m kalainova make <job>` runs **plan → assets → edit → compile → render → qa** from JSON contracts.
- Provider adapters: Anthropic (planner + vision judge), ElevenLabs (voice with word timestamps, music, sfx), fal (image, video, music, transcription), and a zero-cost **local** fallback for every capability so the line never stops.
- ffmpeg compiler over a closed op list (`cut scale concat overlay_text mix_audio loudnorm burn_captions export`). Paths are jailed to the job work dir, so a model-written plan cannot run a command or touch other files.
- Retention defaults: hook card, kinetic word-by-word captions with emphasis colour, motion on every still, a shot change every ≤ 4 s, progress bar, sidechain-ducked music, whoosh on cuts, two-pass loudnorm to −14 LUFS / −1 dBTP.
- QA gate: frame size, fps, duration, loudness, true peak, black frames, dead air, pacing, hook timing, caption coverage, claim sources, rights, synthetic flag, contact sheet, and an LLM vision judge when a key exists.
- Human gate: `approve` binds to the sha256 of the exact file that passed QA and refuses any job with an asset from the local provider. `publish` refuses if the bytes changed. YouTube posts through the official Data API with `containsSyntheticMedia: true`; other platforms go through Upload-Post.
- `measure` pulls 48 h stats into `measure.json`.

Placeholder render (local providers, no keys): 1080×1920, 30 fps, −14.0 LUFS, 100% caption coverage. QA records a technical pass for CI. It is not a proof of quality, and `approve` refuses the file. No piece has been accepted, so the 30-day and 90-day numbers above are the bar, not a result.

## How it makes money (first 90 days)

Research (2026-11-05) is blunt: Shorts ad revenue pays $0.03–0.20 per 1K views, YouTube terminated the biggest AI-slop channels in early 2026 and enforces "inauthentic content" at channel level, TikTok and Spotify's partner program are unavailable in some operator markets. **Selling studio output to businesses is the fastest money; owned channels are the showroom.**

| # | Path | Price | Unit cost | Kill if |
|---|---|---|---|---|
| 1 | **AI UGC + performance ad creative** for direct-to-consumer brands. Strategy `client`. | $200–375/ad; 10-pack ~$2.8K; retainer 12/mo ~$3.6K. Local-market brands at 40–60%. | ~$10–30 generation + review | < 2 paying clients by day 45, gross margin < 50%, no repeat order |
| 2 | **Localization / dubbing** (EN ↔ HI/TA/TE) for businesses and creators. Strategy `client`. | $5–15 per finished minute | $2.20/min ElevenLabs Dubbing + native QA | < 300 billed min/mo by day 60, QA > 30 min per finished min |
| 3 | **One flagship owned channel**, long-form explainers in a high-RPM category, human-approved, 2–3/week. Strategy `generated`. | ~0 ad revenue in 90 days; value is portfolio + inbound leads | ~$6 per 30 s at default stack | Day 90: < 1K subs, avg view duration < 30%, zero inbound leads |

Opportunistic: funded clipping (Whop ~$1/1K on music/logo campaigns) only if it clears $300/mo. Avoid as primary: AI music streaming, microstock volume, Shorts-only ad revenue.

## Model stack (from the 2026-11-05 survey; re-check monthly, models changed every few weeks this year)

| Capability | Default | Premium | Budget |
|---|---|---|---|
| Video (T2V/I2V, native audio) | Wan 3.0 1080p, $0.20/s | Seedance 2.5 / Kling 4.0 | MiniMax H3 768p, $0.08/s |
| Image / edit | Nano Banana 2.1, ~$0.05 | GPT Image 2.5, ~$0.21 | MAI-Image-2.6-Flash, $0.02 |
| Typography in image | GPT Image 2.5 | Ideogram 4.5 | Ideogram 4.5 low |
| Voice / clone | Eleven v4 Turbo, $40/M chars | Eleven v4 | Gemini 3.8 Flash TTS |
| Dubbing | ElevenLabs Dubbing v2, $2.20/min | HeyGen lip-sync, $4/min | — |
| Music | Lyria 3 Pro, $0.08/song | ElevenLabs Music v2 | Lyria 3 Clip |
| Lip-sync / avatar | OmniHuman 2.0 | sync-3 + HeyGen Avatar IV | sync lipsync-2 |
| Transcription (word timings) | ElevenLabs Scribe v2 | — | MAI-Transcribe-2 |
| Upscale | Topaz Starlight Precise 2.6 | Topaz Astra 2 | ByteDance upscaler |

Sora's API is closed (Sep 2026) and Veo 3.1 preview endpoints are gone (Oct 2026). Budget 3–5 attempts per usable generated shot. All of this lives in `config/studio.yaml`; swapping a model is a config edit.

## MCPs and tools (`.mcp.json` ships the first six)

1. **fal** (hosted, official): hundreds of image/video/audio models, `get_pricing` before every run.
2. **ElevenLabs** (official): voice, Scribe, cloning, sfx.
3. **Upload-Post** (vendor): post + analytics across 10+ platforms. Confirm its TikTok app is audited, or TikTok posts land private.
4. **Exa** and **Perplexity**: cited research for scripts and briefs.
5. **AssemblyAI**: transcription and post-render ASR check.
6. **Airtable** (or Notion): content calendar, client pipeline, keep/kill ledger.
7. **Remotion Agent Skills** (the hosted MCP was retired 2026-10-26): `npx remotion skills add`. Needs a paid license above 3 employees. **HyperFrames** (Apache-2.0) is the license-free alternative.
8. **n8n** instance MCP or **Inngest/Trigger.dev**: approval webhooks, the 48 h sleep, retries.
9. **Cloudflare (R2)**: public URLs that Instagram/TikTok pull media from.
10. **Google GenMedia** (experimental): Veo/Omni, Imagen, Lyria on Vertex.

Keep ffmpeg in-process (this repo); an MCP wrapper adds nothing over the executor.

## Target architecture

```
brief (Slack / form / CLI)
  → Planner agent        script_packet (hooks ×3, beats, sourced claims, publish copy)
  → Director agent       per-beat shot prompts, style bible, character refs
  → Asset fan-out        voice ∥ images ∥ video clips ∥ music   (cost-capped, provider fallback)
  → Editor agent         edit_manifest (cuts, motion, captions, overlays, audio)
  → Compiler             render_plan → ffmpeg; overlay layer → Remotion/HyperFrames (alpha) when installed
  → QA                   gates + ASR-vs-script + vision judge + loudness
  → Review card          one tap approve/reject (+ reason label) in Slack/Telegram/web
  → Publisher            official APIs / Upload-Post, AI label on
  → Analyst (48 h, 7 d)  retention by beat → hook bandit, exemplar store, rubric calibration
```

Run each job as an ephemeral agent container (session resumes from the job folder), and the scheduler/analyst as long-running workers.

## Roadmap with exit criteria

| Milestone | Build | Exit criterion |
|---|---|---|
| **M1 Real keys** (this week) | Set `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `FAL_KEY`. Verify fal slugs with the fal MCP. Render 3 pieces on the default stack. | 3 renders, QA pass, Kartik would post them |
| **M2 Quality** | Scribe/ASR check vs script (WER ≤ 3%); vision judge required; hook ×3 variants rendered; overlay renderer (Remotion or HyperFrames) behind `burn_captions`; style bibles per client | 60% first-review acceptance on 10 pieces |
| **M3 Client studio** | `client` jobs: brand kit, product images in, UGC ad formats (hook-problem-demo-CTA), 4:5 + 9:16 + 1:1 variants, dubbing job type | First paid invoice |
| **M4 Autopost + measure** | Review card (Slack/Telegram), Upload-Post live, R2 media URLs, scheduled 48 h measure | 2 weeks of posts with measure.json on every one |
| **M5 Learning loop** | Feature log per piece, retention-by-beat attribution, hook bandit, exemplar store feeding the planner | Acceptance ≥ 85%, MRR ≥ $8K |

## Guardrails that protect the money

- Original or licensed inputs only. No third-party footage, label music, league/brand marks, or real people's likeness without a release.
- AI disclosure on every synthetic piece (`containsSyntheticMedia`, platform toggles). EU AI Act Art. 50 applies since 2026-08-02.
- Human approval on every piece. YouTube judges the whole channel; one slop week can cost the channel.
- Cadence cap on owned channels: 1–2 Shorts a day or 2–3 long-form a week. Variety in format and voice.
- Every factual line carries a source; the QA judge kills unsupported claims.

## Patterns adopted from prior template work

Adopted: a hook card over the first ~1.5 s, a watch-time progress bar, a subject-agnostic format catalogue (countdown, N-reasons, poll, VS, stat card), design rules expressed as QA checks, and event-relative posting cadence. Planned: composition-as-template behind the overlay op, and crossfade-overlap timing on `concat`.
Rejected: re-uploading third-party footage, chart music, and trademarked badges or hashtags.

## What needs the operator

1. API keys: Anthropic, ElevenLabs, fal (then Upload-Post, YouTube OAuth client).
2. One house voice (clone yours or pick one) and a showroom identity name.
3. Three target clients for the first UGC-ad pilot.
4. Tax advice on invoicing clients abroad before the first export invoice.
