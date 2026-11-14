# Identity-consistent multi-shot and automated studio systems

**Research date:** 2026-11-14  
**Scope:** StoryDiffusion, ConsisID, CineMaster, AutoStudio, and closely related work on character consistency, multi-agent filmmaking, shot planning, narrative video pipelines, and generate→critique→revise loops.  
**Method note (epistemic):** Live `WebSearch` / `WebFetch` / shell network access were unavailable in this research session (searches user-rejected; fetches blocked as domain-not-allowlisted; shell rejected). Findings below are synthesized from prior knowledge of the named primary papers and project artifacts, plus local Kalainova architecture (`ARCHITECTURE.md`, `src/kalainova/consistency.py`, `src/kalainova/qa.py`). Canonical URLs are listed for primary verification; treat exact page wording, secondary metrics, and any post-cutoff updates as **unverified until fetched**. Where a paper ID or date is uncertain, it is called out under **Gaps**.

---

## How do StoryDiffusion / ConsisID achieve subject/identity consistency across frames/shots?

### Takeaway
StoryDiffusion keeps subjects coherent mainly by **sharing self-attention K/V across a batch (or window) of story frames** (training-free “Consistent Self-Attention”), plus a **semantic-space motion predictor** for video between keyframes. ConsisID instead **extracts and injects identity features with frequency decomposition** into a video generator so low-frequency identity structure stays stable while high-frequency detail does not fight motion—i.e., conditioning/fine-tuning rather than cross-frame attention sharing.

### Cited Findings
- StoryDiffusion’s public paper title is *StoryDiffusion: Consistent Self-Attention for Long-Range Image and Video Generation* (Zhou et al.; arXiv listing dated **2024-05-02** for `2405.01434`). Primary abstract page: [arXiv:2405.01434](https://arxiv.org/abs/2405.01434); project page commonly cited as [storydiffusion.github.io](https://storydiffusion.github.io/); code commonly cited as [HVision-NKU/StoryDiffusion](https://github.com/HVision-NKU/StoryDiffusion).
- Consistent Self-Attention (CSA): during denoising of multiple story panels in one batch, each spatial token’s self-attention can attend to keys/values from **other images in the batch** (or a temporal window), so appearance features of a character propagate across panels without a separate ID encoder or fine-tune. This is an inference-time architectural tweak on a frozen T2I backbone (e.g. SDXL-class), not a new identity embedding model. — [arXiv:2405.01434](https://arxiv.org/abs/2405.01434); [StoryDiffusion GitHub](https://github.com/HVision-NKU/StoryDiffusion)
- For video, StoryDiffusion’s **Semantic Motion Predictor** predicts transitions between story keyframes in a compressed/semantic representation rather than raw pixels, then maps those predictions into the video diffusion path—aimed at long-range motion while preserving the character established in keyframes. — [arXiv:2405.01434](https://arxiv.org/abs/2405.01434)
- Typical StoryDiffusion product pattern: text story → multi-panel stills with CSA → optional keyframe-to-video; comic/storyboard demos are the flagship UX. — [storydiffusion.github.io](https://storydiffusion.github.io/)
- ConsisID is publicly presented as *Identity-Preserving Video Generation via Frequency Decomposition* (PKU-YuanGroup line of work; commonly abbreviated ConsisID). Code/org landing commonly cited: [PKU-YuanGroup/ConsisID](https://github.com/PKU-YuanGroup/ConsisID). A widely referenced preprint ID for this line is **arXiv:2411.17440** (November 2024 class); **live confirmation of that exact ID was not possible in this session** (see Gaps).
- ConsisID’s core claim pattern: build an **identity-preserving video** model (often on a DiT / CogVideoX-class backbone) that conditions on **one or few reference face/person images**, rather than relying only on text. — [ConsisID GitHub](https://github.com/PKU-YuanGroup/ConsisID)
- Frequency decomposition (as described in ConsisID materials): identity signals are split so **low-frequency components** carry global structure / recognizability and **high-frequency components** carry local texture/detail; injection is structured so identity does not collapse under large pose/expression/motion changes the way naïve full-feature face embedding injection often does. — [ConsisID GitHub](https://github.com/PKU-YuanGroup/ConsisID); abstract lineage on [arXiv](https://arxiv.org/abs/2411.17440) *(ID confidence: medium—verify)*
- Related baseline family ConsisID is usually compared against: IP-Adapter-style image cross-attention ([IP-Adapter paper arXiv:2308.06721](https://arxiv.org/abs/2308.06721)), InstantID / FaceID pipelines ([InstantID arXiv:2401.07519](https://arxiv.org/abs/2401.07519)), and PhotoMaker-style stacked ID embeddings ([PhotoMaker arXiv:2312.04461](https://arxiv.org/abs/2312.04461))—i.e., **external ID embeddings + adapters**, vs StoryDiffusion’s **intra-batch attention sharing**, vs ConsisID’s **frequency-aware ID injection into video**.

### Inferences
- StoryDiffusion optimizes **cross-shot / cross-panel consistency inside one generation graph**; it does not by itself solve “same character six months later on a new job” unless the operator reuses references or re-runs with shared attention context.
- ConsisID optimizes **reference-to-video identity fidelity over time**; it is closer to a Kalainova “kit face refs → every video call” pattern, but with a **model-internal ID pathway**, not only “attach reference images and hope the rented model honors them.”
- The two methods are complementary: CSA/shared attention helps **multi-shot still storyboards**; frequency-aware ID helps **single-subject video clips**; a studio stack often needs both plus an outer planning loop.

### Gaps
- Exact ConsisID arXiv number, camera-ready venue (e.g. CVPR 2025 claims in secondary blogs), and quantitative tables (ArcFace scores, user studies) could not be live-fetched.
- Precise CSA attention-mask formulas, window sizes, and multi-character grouping rules need the PDF; secondary blog summaries are unreliable.
- Whether ConsisID supports **multi-identity** shots (two named characters interacting) at the same fidelity as single-ID demos is not established here from primary text.

---

## How do CineMaster / AutoStudio structure shot planning, camera, multi-agent roles, and iteration?

### Takeaway
AutoStudio-class systems structure generation as a **multi-agent studio** (director / layout / per-subject supervisors) with an explicit **subject bank** and multi-turn iteration. CineMaster-class systems structure cinematic control as **layout + camera trajectory → video** (3D-aware boxes/poses), i.e. a geometric shot language rather than a pure chat-of-agents. Both treat “the shot” as a first-class planned object, not only a text prompt.

### Cited Findings
- AutoStudio is commonly cited as a **multi-turn interleaved image generation** system that keeps subjects consistent across turns via agents and a subject memory—title pattern: *AutoStudio: Crafting Consistent Subjects in Multi-turn Interleaved Image Generation* (2024). A frequently linked preprint is [arXiv:2406.01388](https://arxiv.org/abs/2406.01388) *(ID confidence: medium—verify)*. Project/code mentions typically point at academic GitHub mirrors under the AutoStudio name.
- Reported AutoStudio role split (secondary + abstract-level consensus in the literature discussion): a **global director/manager** plans narrative turns and tool calls; a **layout planner** assigns spatial regions; **subject-specific supervisors** own each character’s appearance tokens/images; generation modules consume layout + subject features. — [arXiv:2406.01388](https://arxiv.org/abs/2406.01388) *(verify role names against PDF)*
- AutoStudio iteration pattern: after a turn, supervisors / consistency checks can **refuse or regenerate** a subject crop when it drifts; accepted subjects are written into a **subject bank** for later turns (retrieve → bind → generate). — [arXiv:2406.01388](https://arxiv.org/abs/2406.01388)
- CineMaster is discussed in 2025-era controllable video work as a **3D-aware cinematic T2V framework**: users or upstream planners specify **character/object layouts** (often 3D boxes or poses) and **camera trajectories**, then a generator synthesizes video that respects both scene layout and camera language (pan/truck/orbit-style moves separated from subject motion). A candidate preprint pointer used in discussions is [arXiv:2502.06148](https://arxiv.org/abs/2502.06148) *(ID confidence: low–medium—verify; title/authorship must be confirmed)*.
- Adjacent multi-agent filmmaking systems (closely related, better-documented in open materials than some “CineMaster” secondary posts):
  - **FilmAgent**-style crews: LLM agents role-play director, screenwriter, cinematographer; they propose shot lists, critique rehearsals, and revise before/while calling image/video tools. Search landing: papers/code under “FilmAgent” multi-agent filmmaking (verify current GitHub org; commonly discussed 2024).
  - **Vlogger** / long-form narrative pipelines: plan story beats → retrieve or generate keyframes → animate → stitch (planning-heavy, less ID-theoretic).
  - **MovieDreamer** / storyboard-to-movie lines: expand script to storyboards then to video, emphasizing hierarchical planning.
- Shared system pattern across AutoStudio + cinematic controllers: **(1) structured shot plan**, **(2) binding of character IDs to regions or tracks**, **(3) generation**, **(4) agent or metric critique**, **(5) local revise**—not a single monolithic prompt.

### Inferences
- AutoStudio’s innovation is **organizational memory** (who owns which face across turns). CineMaster-class innovation is **cinematic controllability** (camera as data, not adjectives in a prompt).
- A kit/stream engine that only pins `provider/model` and ships reference PNGs covers neither: it has frozen assets, but not necessarily **per-shot layout/camera IR** or **per-subject supervisor loops**.

### Gaps
- CineMaster’s exact title, authors, venue, and GitHub could not be live-confirmed; treat the `2502.06148` pointer as a lead, not a fact.
- AutoStudio’s exact agent prompts, tool APIs, and whether video (vs interleaved stills) is in-scope need the primary PDF.
- Comparison tables for planning latency / cost / human preference vs single-agent GPT-4V directors were not retrieved.

---

## What memory, reference banks, attention, or ID-embedding techniques are used?

### Takeaway
Four technical families dominate: **(A) cross-frame / cross-panel attention sharing**, **(B) external ID embeddings + adapters**, **(C) explicit subject/reference banks with retrieval**, **(D) geometric layout/camera memory**. Automated studios combine (C)+(D) in the planner and (A) or (B) in the renderer.

### Cited Findings
- **Attention sharing / ConsiStory–StoryDiffusion family:** share self-attention features across images that depict the same subject; ConsiStory (*Consistent Image Generation*, ~2024) and StoryDiffusion CSA are the canonical training-light approaches. StoryDiffusion: [arXiv:2405.01434](https://arxiv.org/abs/2405.01434). ConsiStory often cited via [arXiv:2402.03286](https://arxiv.org/abs/2402.03286) *(verify)*.
- **IP-Adapter:** decoupled cross-attention for image prompts so a reference image steers generation without full DreamBooth fine-tune — [arXiv:2308.06721](https://arxiv.org/abs/2308.06721).
- **InstantID:** IdentityNet + facial keypoints + IP-Adapter-style path for strong face fidelity from one photo — [arXiv:2401.07519](https://arxiv.org/abs/2401.07519).
- **PhotoMaker:** encode multiple reference photos into a stacked ID representation for stylized consistent characters — [arXiv:2312.04461](https://arxiv.org/abs/2312.04461).
- **PuLID / FaceID / ArcFace pipelines:** contrastive or recognition embeddings (e.g. ArcFace) used as conditioning and/or as **evaluation** similarity; PuLID emphasizes “lightning” ID customization with less prompt bleed — PuLID commonly [arXiv:2404.16067](https://arxiv.org/abs/2404.16067) *(verify)*.
- **ConsisID frequency-aware ID features:** identity embedding is not a single flat vector; frequency bands are treated differently when injected into video DiT blocks — [ConsisID GitHub](https://github.com/PKU-YuanGroup/ConsisID).
- **Subject banks (AutoStudio-class):** store cropped subject images, embeddings, and binding IDs; later shots retrieve the bank entry instead of re-describing the character in free text — [arXiv:2406.01388](https://arxiv.org/abs/2406.01388).
- **Layout / track memory (CineMaster-class & layout-to-video):** per-shot tensors or JSON for boxes, depth order, camera extrinsics/intrinsics or trajectory keypoints; this is structured memory the generator must condition on — lead: [arXiv:2502.06148](https://arxiv.org/abs/2502.06148) *(verify)*.
- **LoRA / DreamBooth character kits (industry pattern):** per-character fine-tunes as durable identity memory; orthogonal to attention-sharing; common in production Midjourney/Flux/SD workflows and in “character bible” products.
- **Kalainova local analogue (engine, not generative math):** kits freeze face/voice/persona/style refs; `consistency.RULES` states identity is “reference files sent with every still and video” and checked by “vision check, then human”; locks pin exact kit versions per job. — local [`src/kalainova/consistency.py`](../../../src/kalainova/consistency.py); [`ARCHITECTURE.md` kits/streams/jobs](../../../ARCHITECTURE.md)

### Inferences
- “Reference PNG in the API call” is the weakest form of identity memory; stronger forms add **embedding geometry**, **attention coupling across shots**, or **learned subject modules**.
- Evaluation memory (ArcFace / LPIPS / CLIP) is distinct from generation memory but closes the loop when wired into QA.
- Kalainova’s kit.lock is strong **content-addressed asset memory** and weak **model-internal identity coupling**—unless the rented model’s reference pathway is itself InstantID/ConsisID-class and verified.

### Gaps
- No primary-source extraction of AutoStudio’s exact bank schema (fields, eviction, multi-subject conflict rules).
- No confirmed list of which commercial video APIs expose InstantID-like vs IP-Adapter-like vs “mystery reference” controls as of 2026-11-14 (vendor docs not fetched).

---

## What closed-loop generate → critique → revise patterns exist?

### Takeaway
Closed loops appear at three layers: **metric gates** (face similarity, VBench-style scores), **VLM/LLM judges** (rubric critique → structured findings → retake), and **multi-agent rehearsal** (crew debates shot list before spending on pixels). The mature pattern is: generate locally → score identity/story → write machine-readable faults → regenerate only failing shots with stronger bindings.

### Cited Findings
- **AutoStudio subject supervisors:** consistency agents can reject a subject rendering and trigger regeneration before committing to the subject bank—an inner loop around identity. — [arXiv:2406.01388](https://arxiv.org/abs/2406.01388)
- **FilmAgent / multi-agent rehearsal:** agents critique scripts and shot plans in language space (cheap) before image/video calls (expensive); iteration is mostly on the plan IR. — FilmAgent literature (2024; verify code/paper URL on fetch)
- **VLM-as-judge:** GPT-4V / Gemini-class models score frames for prompt alignment, character continuity, and policy; outputs are increasingly structured JSON faults. Industry and research demos (EvalCrafter discussions; various “AI director” blogs) share this pattern; primary unification paper varies.
- **Recognition metrics as critics:** cosine similarity of ArcFace (or similar) embeddings between kit reference and generated face crops; threshold → pass/fail. Used both in ConsisID-style papers’ eval sections and in production QA. Face recognition backbone literature: ArcFace [arXiv:1801.07698](https://arxiv.org/abs/1801.07698).
- **Video benchmarks as weak critics:** VBench / EvalCrafter-style dimensions (subject consistency, temporal flickering, motion smoothness) used for automatic ranking of seeds/models — VBench [arXiv:2311.17982](https://arxiv.org/abs/2311.17982) *(verify use in each studio paper)*.
- **Self-Refine / Reflexion-style loops** applied to shot lists: LLM reads its storyboard, lists contradictions, revises beat sheet, then regenerates—cheap narrative QA before pixels.
- **Kalainova existing loop (local):** QA can run a vision/LLM judge; faults become `findings` a retake can read; human approval remains the hard gate (`ARCHITECTURE.md` ADR 0007 pattern); judge failures are often advisory (`warn`) rather than sole publish authority. — [`src/kalainova/qa.py`](../../../src/kalainova/qa.py), [`src/kalainova/qachecks.py`](../../../src/kalainova/qachecks.py)
- **Kalainova known gap (local):** “QA does not predict the operator’s verdict”; “Reference-based character consistency relies on what the vendors claim”; outside-tool files “carry no enforced references.” — [`ARCHITECTURE.md` Known gaps](../../../ARCHITECTURE.md); [README consistency note](../../../README.md)

### Inferences
- The highest leverage closed loop for identity is **quantitative face/subject similarity per shot**, not only prose critique.
- The highest leverage closed loop for story is **plan-level rehearsal** (contradiction checks on beat sheets/canon) before render spend.
- Retake granularity matters: revise **one shot** with stronger ID weight / layout constraints beats regenerating the whole film.

### Gaps
- Few primary papers publish full **costed** closed-loop policies (when to stop revising, max retakes, budget caps)—operational detail often lives in unreleased studio code.
- Live confirmation of which ConsisID/StoryDiffusion demos include automatic revise (vs human click regenerate) was not available.

---

## What innovative paradigms (multi-agent directors, cinematic language DSLs, layout-to-video, storyboard agents) emerge?

### Takeaway
The emerging stack is a **studio IR**: storyboard/shot DSL + character binders + camera/layout tracks + renderer adapters + critic agents. Pixel models become interchangeable backends; coherence lives in the IR and the loops around it.

### Cited Findings
- **Multi-agent directors / film crews:** specialized LLM agents (director, DP, editor, continuity supervisor) producing and criticizing a shot list—FilmAgent-class and AutoStudio-class systems. — AutoStudio [arXiv:2406.01388](https://arxiv.org/abs/2406.01388); FilmAgent (verify URL)
- **Cinematic language as structured data:** shot size (ECU/CU/MS/WS), angle, movement, lens, duration, eyeline—encoded as fields or tokens rather than buried in prose. CineMaster-class and many storyboard agents consume this. — CineMaster lead [arXiv:2502.06148](https://arxiv.org/abs/2502.06148) *(verify)*
- **Layout-to-video:** boxes/poses/trajectories → video; separates “who is where” from “how it looks,” improving multi-character blocking. — CineMaster-class; related controllable video literature (e.g. box-conditioned T2V lines; verify peers when fetching)
- **Storyboard agents:** LLM/VLM emits panel grid (sometimes SVG/HTML or comic panels via StoryDiffusion), human or agent locks panels, then I2V animates—StoryDiffusion’s comic path is a concrete instance. — [arXiv:2405.01434](https://arxiv.org/abs/2405.01434)
- **Keyframe-then-interpolate paradigm:** generate identity-strong keyframes (CSA / ID tools) → motion model fills interiors (StoryDiffusion SMP; DynamiCrafter-class I2V). Reduces identity drift vs pure long T2V.
- **Continuity supervisor as software:** dedicated agent or checker for wardrobe, props, eyelines, left/right screen direction—mirrors live-action script supervising; appears in multi-agent film papers more than in single-model demos.
- **Product/system pattern:** “automated studio” = orchestration + asset library + critics, with rented diffusion/DiT/VLM behind adapters—aligned with Kalainova’s “rent the models, own the line” stance, but only if the **owned line includes IR + critics + binders**, not only CLI + YAML model tables.

### Inferences
- DSLs and layout IRs are the durable IP; model weights churn.
- Storyboard-first pipelines are currently more reliable for identity than end-to-end long-form T2V.
- Multi-agent helps most when agents write **machine-checkable artifacts** (JSON shot plans, binder IDs), not when they only chat.

### Gaps
- No single open standard “cinematic DSL” dominates; each paper invents fields—interoperability is weak.
- Empirical evidence that multi-agent > single strong planner for final audience preference is mixed/under-fetched.

---

## What would a Kalainova-like kit/stream engine miss if it only swaps rented models without these patterns?

### Takeaway
Swapping rented models upgrades **local shot quality**; it does not create **cross-shot attention coupling**, **owned ID embedding pathways**, **layout/camera IR**, **subject banks with supervisor loops**, or **metric identity QA**. Without those patterns, coherence remains a vendor promise plus human taste—exactly the gap Kalainova’s own docs already flag.

### Cited Findings
- Kalainova continuity objects today: **kit** (frozen face/voice/persona/places/style), **stream** (identity + generators + limits), **job lock** (exact kit versions). Preflight can refuse if a pinned model “takes no reference images.” — [`ARCHITECTURE.md`](../../../ARCHITECTURE.md); [`consistency.py` RULES + reference capacity checks](../../../src/kalainova/consistency.py)
- Enforcement model: identity applied as “reference files sent with every still and video”; checked by “vision check, then human.” Music is hash-pinned; voice is provider/voice-id pinned. — [`consistency.py` RULES](../../../src/kalainova/consistency.py)
- Documented limitations: vendor reference behavior must be tested per character; outside-tool files lack enforced references; QA ≠ operator verdict; vision judge is “one more signal.” — [`ARCHITECTURE.md` Known gaps](../../../ARCHITECTURE.md); [README](../../../README.md)
- StoryDiffusion-class capability **missing if only model-swapping:** no engine-owned CSA / cross-shot attention graph; each rented call is typically independent unless the vendor exposes multi-image consistent modes.
- ConsisID-class capability **missing:** no owned frequency-aware ID module; cannot improve identity math except by picking a vendor that implemented something similar behind the API.
- AutoStudio-class capability **missing:** no first-class **subject bank + per-subject supervisor** loop across turns; kit refs are static files, not a growing bank of accepted renders with binders and drift detectors.
- CineMaster-class capability **missing:** no layout-to-video / camera trajectory IR as a contract object alongside beats; cinematic structure lives in prose prompts and human review.
- Closed-loop gap: judge→findings→retake exists in outline, but without **hard identity metrics** (e.g. ArcFace threshold per character crop) and without **plan-level cinematic validators**, revise policies stay soft/advisory. — [`qa.py`](../../../src/kalainova/qa.py)

### Inferences
- The kit/stream/lock trinity is already the right **product abstraction** for AutoStudio’s subject bank + FilmAgent’s continuity bible; the missing pieces are mostly **algorithms under the binder** and **critics with numbers**.
- Highest-value additions suggested by this literature (conceptual, not an implementation mandate):
  1. **Shot IR**: structured camera/layout fields on every beat.
  2. **Identity metrics in QA**: reference↔render embedding similarity per role, fail_under ratchet.
  3. **Cross-shot generation modes**: batch CSA or vendor multi-shot consistent APIs when available; preflight encodes which pins support them.
  4. **Accepted-render bank**: promote QA-passed crops into versioned subject memory for later shots (still human-attested at kit freeze for canon faces).
  5. **Plan rehearsal agents**: cheap continuity/canon critique before spend (fits existing script_packet + findings paths).
- Without those, model swaps can improve aesthetics while **identity/story regressions** remain undetectable until a human watches the cut—expensive and non-scalable.

### Gaps
- This session did not benchmark Kalainova’s current vision judge prompts against ArcFace-style metrics on real jobs (`KALAINOVA_HOME` is out of scope / private).
- Vendor-by-vendor matrix of “supports CSA / InstantID / ConsisID-like reference / box conditioning” as of 2026-11-14 was not fetchable; needs a follow-up pass against `config/studio.yaml` reference_models plus provider docs.
- **Follow-up source ledger (not live-fetched):** StoryDiffusion [arXiv:2405.01434](https://arxiv.org/abs/2405.01434), [project](https://storydiffusion.github.io/), [GitHub](https://github.com/HVision-NKU/StoryDiffusion); ConsisID [GitHub](https://github.com/PKU-YuanGroup/ConsisID), [arXiv:2411.17440](https://arxiv.org/abs/2411.17440) *(verify ID)*; AutoStudio [arXiv:2406.01388](https://arxiv.org/abs/2406.01388) *(verify)*; CineMaster [arXiv:2502.06148](https://arxiv.org/abs/2502.06148) *(verify)*; IP-Adapter [2308.06721](https://arxiv.org/abs/2308.06721); InstantID [2401.07519](https://arxiv.org/abs/2401.07519); PhotoMaker [2312.04461](https://arxiv.org/abs/2312.04461); PuLID [2404.16067](https://arxiv.org/abs/2404.16067) *(verify)*; ConsiStory [2402.03286](https://arxiv.org/abs/2402.03286) *(verify)*; VBench [2311.17982](https://arxiv.org/abs/2311.17982); ArcFace [1801.07698](https://arxiv.org/abs/1801.07698). Confirm ConsisID/AutoStudio/CineMaster IDs, pull method sections and metrics, and map FilmAgent peers on a networked pass.
