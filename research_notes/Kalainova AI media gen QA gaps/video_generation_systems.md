# Cutting-edge AI video generation systems (Movie Gen, Wan 2.1, HunyuanVideo, Cosmos, related OSS)

> Research notes for report synthesis. Focus: generation architectures, algorithms, conditioning/control, inference stacks, eval loops, and gaps vs kit/stream/job orchestration (Kalainova).
>
> **Session constraint:** Live WebSearch/WebFetch were unavailable (user rejection / domain allowlist). Citations below are to well-known primary URLs (arXiv abs pages, official GitHub/project pages) from established publication records through ~early 2025, plus local Kalainova repo paths for the orchestration comparison. Claims that could not be re-fetched live are marked in **Gaps**. Prefer re-fetching arXiv PDFs and repo READMEs before treating numeric hyperparams as authoritative.

---

## What model architectures and algorithms do they use (DiT, autoregressive, cascaded, world models, etc.)?

### Takeaway
Through 2024–2025 the dominant open and frontier recipe is a **spatiotemporal latent Diffusion Transformer (DiT)** trained with **flow matching / continuous-time diffusion**, on top of a **3D (often causal) video VAE**; Meta Movie Gen and Tencent HunyuanVideo exemplify closed vs open large DiTs, Alibaba Wan 2.1 follows the same open DiT+VAE line, while NVIDIA Cosmos is a **world-foundation** stack that adds **tokenizers + diffusion and autoregressive predictors + control/transfer models** aimed at Physical AI rather than entertainment clips alone.

### Cited Findings
- Meta’s technical report **“Movie Gen: A Cast of Media Foundation Models”** (posted ~Oct 2024) describes a cast of media foundation models including **Movie Gen Video** (large latent video generator) and **Movie Gen Audio**, with joint media generation/editing capabilities — [arXiv abs 2410.13720](https://arxiv.org/abs/2410.13720); [Meta Movie Gen research page](https://ai.meta.com/research/movie-gen/).
- Public technical summaries of Movie Gen Video characterize it as a ~**30B-parameter** transformer operating in a compressed video latent space (temporal autoencoder / video VAE), trained with modern diffusion/flow-matching objectives and strong LLM-style text conditioning — [arXiv abs 2410.13720](https://arxiv.org/abs/2410.13720); [Meta Movie Gen research page](https://ai.meta.com/research/movie-gen/).
- Movie Gen is presented as a **foundation-model family** (video + audio + editing/personalization), not a single cascaded SD1.5-style pipeline; weights are **not** released as community OSS — [Meta Movie Gen research page](https://ai.meta.com/research/movie-gen/).
- Tencent’s **“HunyuanVideo: A Systematic Framework For Large Video Generative Models”** (Dec 2024) publishes an open large video DiT framework (~**13B** class) with a **Dual-stream → Single-stream** transformer design (image/text streams merging into full spatiotemporal attention), a **3D causal VAE**, and an **MLLM text encoder** — [arXiv abs 2412.03603](https://arxiv.org/abs/2412.03603); [GitHub Tencent/HunyuanVideo](https://github.com/Tencent/HunyuanVideo).
- HunyuanVideo’s design explicitly systematizes data curation, progressive training, and full-attention DiT scaling rather than relying on a classic multi-stage cascade of separate low-res then high-res diffusion UNets — [arXiv abs 2412.03603](https://arxiv.org/abs/2412.03603).
- Alibaba **Wan 2.1** (Wan-Video / Wan-AI, announced early 2025) ships open weights for **T2V and I2V** DiT models at multiple sizes (commonly cited **1.3B** and **14B** variants) with a 3D VAE and flow-matching-style training; primary code/weights hubs are the Wan-Video GitHub and Wan-AI Hugging Face org — [GitHub Wan-Video/Wan2.1](https://github.com/Wan-Video/Wan2.1); [Hugging Face Wan-AI](https://huggingface.co/Wan-AI).
- A companion technical report title associated with the Wan line is **“Wan: Open and Advanced Large-Scale Video Generative Models”** (2025 arXiv series); treat the exact arXiv id as verify-on-fetch — [GitHub Wan-Video/Wan2.1](https://github.com/Wan-Video/Wan2.1) (paper link usually in README).
- NVIDIA **“Cosmos World Foundation Model Platform for Physical AI”** (Jan 2025) defines **World Foundation Models (WFMs)**: video tokenizers (continuous + discrete), **diffusion world models**, **autoregressive world models**, and downstream transfer/control models for robotics/AV-style Physical AI — [arXiv abs 2501.03575](https://arxiv.org/abs/2501.03575); [GitHub NVIDIA/Cosmos](https://github.com/NVIDIA/Cosmos).
- Cosmos separates **tokenization**, **prediction** (future world states / video), and **Transfer** (conditioned generation from structured signals) as platform pieces, which is a different product cut than “one T2V DiT for social clips” — [arXiv abs 2501.03575](https://arxiv.org/abs/2501.03575).
- Closely related open video generators that share the DiT+3D-VAE pattern: **CogVideoX** (“CogVideoX: Text-to-Video Diffusion Models with An Expert Transformer”, Aug 2024) — [arXiv abs 2408.06072](https://arxiv.org/abs/2408.06072); [GitHub THUDM/CogVideo](https://github.com/THUDM/CogVideo); **Mochi 1** (Genmo, open DiT) — [Hugging Face genmo/mochi-1-preview](https://huggingface.co/genmo/mochi-1-preview); **LTX-Video / LTX-2** (Lightricks, real-time-oriented DiT + spatiotemporal VAE) — [GitHub Lightricks/LTX-Video](https://github.com/Lightricks/LTX-Video); Open-Sora family — [GitHub hpcaitech/Open-Sora](https://github.com/hpcaitech/Open-Sora).
- Autoregressive / hybrid paradigms remain active beside pure DiT diffusion: discrete-token AR video LMs and AR+diffusion hybrids appear in Cosmos AR models and in research lines such as Pyramid Flow / Nova-style systems; diffusion DiT is still the default for open high-quality clip generation in 2025 community stacks — [arXiv abs 2501.03575](https://arxiv.org/abs/2501.03575); [GitHub NVIDIA/Cosmos](https://github.com/NVIDIA/Cosmos).

### Inferences
- For a production engine that only **rents** T2V/I2V endpoints, the underlying algorithm class is largely converged: **latent DiT + flow matching + 3D VAE + strong text encoder**. Differentiation shifts to **conditioning interfaces, duration, identity/reference, audio sync, and control maps**—not to inventing a new backbone.
- Cosmos is the clearest “adjacent but different” paradigm: **world prediction + controllable transfer** for Physical AI, which can be reused for cinematic camera/physics consistency but is not marketed as a drop-in Sora clone.

### Gaps
- Exact Movie Gen Video parameter counts, latent compression ratios, sampler equations, and training FLOPs could not be re-read from the PDF in this session (fetch blocked).
- Exact Wan 2.1 arXiv identifier, training recipe details (noise schedule, CFG, RoPE layout), and differences vs Wan 2.2/3.0 Prime (already appearing on fal in Kalainova config) need live README/paper fetch.
- Whether Movie Gen uses pure flow matching vs epsilon/v-prediction variants should be confirmed from the PDF, not secondary blogs.

---

## How do they handle temporal consistency, long video, camera motion, and conditioning (text/image/video/audio)?

### Takeaway
Temporal consistency is primarily bought with **3D/causal VAEs + full (or hybrid) spatiotemporal attention over latent tubes**, plus **joint image–video training** and careful data filtering; **long video** is usually **short-clip generation + extension / sliding windows / AR continuation**, not one-shot hour-long DiT; conditioning is **text (often MLLM)**, **first-frame / I2V**, **reference images for identity**, and (in Movie Gen) **instructional editing + paired audio models**—camera motion is still mostly **prompted or externally controlled**, not a solved first-class API across all systems.

### Cited Findings
- HunyuanVideo’s **3D causal VAE** compresses space and time jointly so the DiT denoises coherent latent tubes rather than independent per-frame latents; causal design supports streaming encode/decode patterns — [arXiv abs 2412.03603](https://arxiv.org/abs/2412.03603); [GitHub Tencent/HunyuanVideo](https://github.com/Tencent/HunyuanVideo).
- HunyuanVideo uses a strong **multimodal LLM text encoder** (richer than CLIP-only T2V stacks) so linguistic structure, camera verbs, and scene layout in prompts transfer more faithfully into the DiT conditioning path — [arXiv abs 2412.03603](https://arxiv.org/abs/2412.03603).
- Movie Gen reports **text-to-video**, **image-conditioned** generation, **personalized** video (identity from reference faces), and **instruction-based video editing**, plus a separate **Movie Gen Audio** model for synchronized soundtrack/Foley-style audio — [arXiv abs 2410.13720](https://arxiv.org/abs/2410.13720); [Meta Movie Gen research page](https://ai.meta.com/research/movie-gen/).
- Movie Gen Video generation lengths in public materials are on the order of **~16 seconds at up to 1080p** class outputs (clip-scale, not feature-length native) — [Meta Movie Gen research page](https://ai.meta.com/research/movie-gen/).
- Wan 2.1 public model cards emphasize **T2V** and **I2V** (start-frame conditioning) at 480p/720p class resolutions for the open 14B line, with community pipelines for longer extension via continued generation — [GitHub Wan-Video/Wan2.1](https://github.com/Wan-Video/Wan2.1); [Hugging Face Wan-AI](https://huggingface.co/Wan-AI).
- Cosmos Predict-style world models condition on **past video context** (and optionally action/control) to predict future frames—temporal consistency is framed as **dynamics learning**, not only appearance smoothing — [arXiv abs 2501.03575](https://arxiv.org/abs/2501.03575).
- CogVideoX documents an **expert transformer** and 3D VAE approach aimed at coherent motion under text conditioning; it is a frequent baseline in open T2V comparisons — [arXiv abs 2408.06072](https://arxiv.org/abs/2408.06072).
- Industry open stacks commonly implement **I2V** as concatenating/channel-concat or latent replacement of the first frame(s), and **V2V / editing** as noise-and-denoise with strength schedules; native multi-minute single-pass generation remains rare outside proprietary systems — pattern visible across [GitHub Wan-Video/Wan2.1](https://github.com/Wan-Video/Wan2.1), [GitHub Tencent/HunyuanVideo](https://github.com/Tencent/HunyuanVideo), [GitHub Lightricks/LTX-Video](https://github.com/Lightricks/LTX-Video).
- Camera motion in open ecosystems is often handled by (a) prompt language (“dolly in”, “orbit”), (b) **MotionCtrl / CameraCtrl**-style adapters in research forks, or (c) **ControlNet-like** depth/pose/trajectory maps (see next section)—not by a universal camera API inside Movie Gen/Wan/Hunyuan base releases — research lineage examples: CameraCtrl literature via community implementations linked from open video repos; Cosmos Transfer for structured controls — [GitHub NVIDIA/Cosmos](https://github.com/NVIDIA/Cosmos).

### Inferences
- “Long-form” in practice for DiT studios is an **orchestration problem**: shot planning, overlapping windows, identity locks, and edit assembly—exactly the layer Kalainova already owns—while foundation models stay clip-native.
- Audio-conditioned or jointly generated A/V (Movie Gen Audio; later commercial Wan/Kling/Seedance “generate_audio” flags) is a 2025 differentiator Kalainova already partially surfaces at the **provider schema** layer (audio flags on fal video models) without owning the joint model.

### Gaps
- Precise algorithms Movie Gen uses for personalization (IP-Adapter-like cross-attn vs FaceID embeddings vs fine-tune) need PDF confirmation.
- Quantitative long-video strategies (chunk size, overlap, latent guidance between chunks) for Wan/Hunyuan official code vs third-party “long video” scripts were not re-read live.
- Native camera-trajectory conditioning support in Wan 2.1 / HunyuanVideo official releases vs only community forks needs README verification.

---

## What control/composability interfaces exist (ControlNet-like, trajectory, depth, pose, layout)?

### Takeaway
Base T2V DiTs expose **text + image (I2V) + reference/identity** first; **ControlNet-like spatial controls** (depth, pose, edge, segmentation) and **trajectory/camera** controls are strongest in **adapter/transfer** ecosystems—especially **NVIDIA Cosmos Transfer**—and in community ComfyUI graphs, while Meta Movie Gen emphasizes **instruction editing** and **personalization** more than an open ControlNet API.

### Cited Findings
- Cosmos platform documentation and paper describe **Cosmos-Transfer** models that condition world generation on structured modalities (e.g., depth, segmentation, and related control maps)—explicitly ControlNet-adjacent composability for Physical AI video — [arXiv abs 2501.03575](https://arxiv.org/abs/2501.03575); [GitHub NVIDIA/Cosmos](https://github.com/NVIDIA/Cosmos); [NVIDIA Cosmos research/project materials](https://www.nvidia.com/en-us/ai/cosmos/).
- Movie Gen’s published capability set highlights **personalized generation from identity references** and **instruction-based video editing** (semantic edit composability) rather than shipping an open multi-ControlNet graph — [arXiv abs 2410.13720](https://arxiv.org/abs/2410.13720); [Meta Movie Gen research page](https://ai.meta.com/research/movie-gen/).
- HunyuanVideo / Wan 2.1 official open releases prioritize **T2V/I2V** APIs; richer controls (pose, depth, canny, camera) typically appear via **fine-tunes, ControlNet ports, or workflow graphs** in the Hugging Face / ComfyUI ecosystem rather than as core paper claims — [GitHub Tencent/HunyuanVideo](https://github.com/Tencent/HunyuanVideo); [GitHub Wan-Video/Wan2.1](https://github.com/Wan-Video/Wan2.1).
- Commercial APIs adjacent to these research lines increasingly expose **reference-to-video**, **start/end frame I2V**, and element/character slots (e.g., Kling “elements”, multi-image reference); Kalainova’s `config/studio.yaml` already encodes such schemas for Wan 3.0 Prime, Seedance, and Kling on fal — local [config/studio.yaml](../../config/studio.yaml) (`reference_models`, `video_models`).
- Classic image-world ControlNet (Zhang et al.) remains the conceptual parent of video control adapters; video ports inherit spatial maps and extend them temporally (apply per-frame or as video tensors) — foundational ControlNet paper [arXiv abs 2302.05543](https://arxiv.org/abs/2302.05543).

### Inferences
- The innovative composability layer worth copying into a studio engine is not “another DiT”—it is a **typed control bus**: depth/pose/traj/layout/identity/audio as first-class job inputs mapped to provider capabilities (Cosmos-Transfer style), with graceful refusal when a rented model lacks the control.
- Instructional V2V editing (Movie Gen) is a different composability axis than ControlNet: **language as edit operator** over an existing clip.

### Gaps
- Exact control modalities supported by each Cosmos-Transfer checkpoint (depth vs seg vs lidar vs blur) need live model-card fetch.
- Official Hunyuan/Wan ControlNet support matrix (native vs third-party) not verified in this session.
- Layout/box/trajectory APIs in Sora/Veo/Kling closed systems are poorly documented in primary papers; treat secondary claims cautiously.

---

## What OSS inference/serving patterns and tooling surround them?

### Takeaway
Open video DiTs cluster around **Hugging Face Diffusers / custom CUDA kernels / ComfyUI graphs / fal & Replicate serverless**, with multi-GPU sequence parallelism and VAE tiling as standard serving tricks; Cosmos ships as an **NVIDIA platform repo** with tokenizers + predict/transfer packages; Kalainova today mostly **HTTP-rents** (fal) and keeps a thin **local runner** path (LTX on Mac), with a proposed move to a **unified external workflow runtime** (ADR 0019).

### Cited Findings
- HunyuanVideo’s GitHub provides inference scripts, weight download instructions, and community Diffusers integration paths for local multi-GPU generation — [GitHub Tencent/HunyuanVideo](https://github.com/Tencent/HunyuanVideo); model cards on [Hugging Face tencent/HunyuanVideo](https://huggingface.co/tencent/HunyuanVideo).
- Wan 2.1’s GitHub documents installation, T2V/I2V CLIs, and recommended GPU memory footprints for 1.3B vs 14B; weights hosted under Wan-AI on Hugging Face — [GitHub Wan-Video/Wan2.1](https://github.com/Wan-Video/Wan2.1); [Hugging Face Wan-AI](https://huggingface.co/Wan-AI).
- NVIDIA Cosmos GitHub organizes tokenizer, diffusion/AR world models, and transfer/control components for research and robotics pipelines — [GitHub NVIDIA/Cosmos](https://github.com/NVIDIA/Cosmos).
- Diffusers and ComfyUI remain the default **graph-composed** inference UX for open video (nodes for VAE, sampler, ControlNet, upscalers, FaceID); serverless hosts (fal, Replicate, Together-style) wrap the same graphs behind HTTP — ecosystem pattern reflected in fal model slugs used by Kalainova — local [config/studio.yaml](../../config/studio.yaml).
- LTX-Video markets low-latency / real-time-oriented generation; Kalainova’s Mac video path pins `notapalindrome/ltx2-mlx-av` with a dedicated runner — [GitHub Lightricks/LTX-Video](https://github.com/Lightricks/LTX-Video); local [docs/how-to/run-models-on-a-mac.md](../../docs/how-to/run-models-on-a-mac.md); [src/kalainova/providers/runners/ltx.py](../../src/kalainova/providers/runners/ltx.py).
- Kalainova ADR **0019** (proposed 2026-11-14) states that per-model bespoke runners should give way to a **single workflow adapter** calling an external node-runtime over HTTP/WebSocket, with workflow JSON living in `$KALAINOVA_HOME/workflows/`—explicitly aligning the engine with Comfy-like OSS serving patterns without embedding them — local [docs/decisions/0019-self-hosted-models-workflow-runtime.md](../../docs/decisions/0019-self-hosted-models-workflow-runtime.md).
- Common serving optimizations across open DiT repos: **model offload / sequential CPU offload**, **VAE tiling**, **flash/sage attention**, **CFG distillation / fewer steps**, **FP8/FP16**, and **sequence or context parallelism** for long token axes — documented in Hunyuan/Wan/LTX READMEs — [GitHub Tencent/HunyuanVideo](https://github.com/Tencent/HunyuanVideo); [GitHub Wan-Video/Wan2.1](https://github.com/Wan-Video/Wan2.1); [GitHub Lightricks/LTX-Video](https://github.com/Lightricks/LTX-Video).

### Inferences
- The OSS “innovation” for a Kalainova-like engine is **workflow portability** (ADR 0019), not re-implementing samplers: treat Comfy/Cosmos graphs as replaceable backends behind capability pins.
- Serverless fal already collapses Hunyuan/Wan/Kling/Seedance differences into JSON schemas; the missing piece is **exposing control modalities** in those schemas, not hosting GPUs.

### Gaps
- Benchmarked tokens/sec, VRAM tables, and TensorRT/TensorRT-LLM (or TensorRT for DiT) deployment recipes were not fetched live.
- Whether Diffusers has first-class pipelines for Wan 2.1 / HunyuanVideo / Cosmos-Transfer in-tree vs only community PRs needs version-pin verification.
- Cosmos commercial licensing vs research use constraints for production content engines needs legal read of NVIDIA license text.

---

## What evaluation/self-check loops (if any) are baked into generation?

### Takeaway
Foundation video papers primarily report **offline benchmarks and human preference studies** (VBench-style automatic metrics, FVD/CLIP variants, side-by-side raters); **self-check loops inside the sampler** (generate → critic → regenerate) are uncommon in base T2V releases—preference optimization / reward models appear in post-training for some frontier systems, while production engines like Kalainova put QA **outside** the model (bar readings, animatic gates, human approve).

### Cited Findings
- Movie Gen’s report emphasizes large-scale **human evaluations** and qualitative comparisons against prior T2V systems as primary evidence of quality, alongside automatic metrics typical of the literature — [arXiv abs 2410.13720](https://arxiv.org/abs/2410.13720); [Meta Movie Gen research page](https://ai.meta.com/research/movie-gen/).
- HunyuanVideo’s paper frames a **systematic** pipeline including data filtering and evaluation against open T2V benchmarks; community comparisons often cite **VBench** — [arXiv abs 2412.03603](https://arxiv.org/abs/2412.03603); VBench paper [arXiv abs 2311.17982](https://arxiv.org/abs/2311.17982).
- VBench proposes a **multi-dimensional** video generation benchmark (subject consistency, background consistency, motion smoothness, temporal flickering, aesthetic/imaging quality, object class, etc.), i.e., evaluation as an external suite, not an in-model loop — [arXiv abs 2311.17982](https://arxiv.org/abs/2311.17982).
- Cosmos evaluation is oriented to **Physical AI** metrics (prediction fidelity, control adherence, downstream robotics usefulness) rather than social-media clip aesthetics alone — [arXiv abs 2501.03575](https://arxiv.org/abs/2501.03575).
- Kalainova’s refinement ladder places **animatic lock before paid video**, layered QA (contract → identity → model judge → human verdict), and explicitly avoids drafting video by generating video locally as the cheap draft — local [docs/decisions/0016-refinement-ladder-and-layered-qa.md](../../docs/decisions/0016-refinement-ladder-and-layered-qa.md).
- Kalainova identity QA is **post-hoc face embedding comparison** against kit refs (`bar/identity.py`), not an in-DiT identity loss at sample time; motion QA had to be redesigned after “file is video” false positives — local [docs/how-to/run-models-on-a-mac.md](../../docs/how-to/run-models-on-a-mac.md); [.agents/memory/a-video-file-is-not-motion.md](../../.agents/memory/a-video-file-is-not-motion.md).

### Inferences
- The gap vs foundation labs is less “missing VBench” and more **closed-loop generation**: reward-model guidance, identity-aware CFG, or critic-in-the-loop retakes at sample time—Kalainova approximates this with **takes/retakes and human gates**, which are slower but provenance-clean.
- Baking eval into generation (best-of-N with a video reward model) is an innovative paradigm Kalainova could adopt **above** providers without training a DiT.

### Gaps
- Whether Movie Gen / Wan / Hunyuan use RLHF, DPO, or reward-weighted fine-tuning in post-training needs PDF confirmation.
- No primary source found in this session for an official “self-critique then regenerate” loop inside Wan 2.1 or HunyuanVideo sampling code.
- Proprietary systems (Sora, Veo, Kling) may use internal verifiers that are unpublished.

---

## What are they doing that a kit/stream/job orchestration engine like Kalainova (provider-renting, human-gated studio pipeline) typically is NOT doing?

### Takeaway
Foundation systems invest in **weights, tokenizers, joint A/V training, world dynamics, and control-transfer architectures**; Kalainova invests in **rights, kits, animatic cost gates, ledgered spend, human approve/publish, and provider-schema pinning**. The largest unused paradigms for Kalainova are **in-model control buses (Cosmos-Transfer-like)**, **world-model predictive consistency**, **instructional V2V editing**, **joint audio–video generation as a native generator**, **latent-space long-form extension**, and **sample-time reward/critic loops**—not swapping one rented DiT for another.

### Cited Findings
- Kalainova’s public agent context defines the product as a **content generation engine** that rents models, freezes **kits**, routes **streams**, and locks **jobs**, with humans gating approve/publish and attesting kits — local [AGENTS.md](../../AGENTS.md).
- Default rented video stack (as of config dated checks 2026-11-06) pins **Alibaba Wan 3.0 Prime** T2V/I2V/reference-to-video on fal, with alternates listed for Kling and Seedance reference/I2V schemas—i.e., **API consumption** of successors to the Wan 2.1 research line — local [config/studio.yaml](../../config/studio.yaml).
- Local open video is **LTX via Mac runner**, not Hunyuan/Wan/Cosmos self-host by default; ADR 0019 proposes workflow-runtime hosting rather than new in-tree DiT code — local [config/studio.yaml](../../config/studio.yaml); [docs/decisions/0019-self-hosted-models-workflow-runtime.md](../../docs/decisions/0019-self-hosted-models-workflow-runtime.md).
- Kalainova treats video draft as **animatic (stills+audio)** before paying for motion; foundation models draft by **sampling video latents directly** — local [docs/decisions/0016-refinement-ladder-and-layered-qa.md](../../docs/decisions/0016-refinement-ladder-and-layered-qa.md); contrast DiT sampling in [arXiv abs 2412.03603](https://arxiv.org/abs/2412.03603).
- Identity in Kalainova is **kit references + post-hoc face bar**, whereas Movie Gen publishes **in-generator personalization** and commercial APIs expose **reference-to-video** conditioning at sample time — local [src/kalainova/bar/identity.py](../../src/kalainova/bar/identity.py); [arXiv abs 2410.13720](https://arxiv.org/abs/2410.13720); local [config/studio.yaml](../../config/studio.yaml) `reference_models`.
- Cosmos-style **world foundation + Transfer controls** (depth/seg → video) have no first-class equivalent in Kalainova’s job/brief schema today—the engine’s control surface is prompt/image URLs/duration/resolution flags — [arXiv abs 2501.03575](https://arxiv.org/abs/2501.03575); local [config/studio.yaml](../../config/studio.yaml) `video_models`.
- Movie Gen’s **cast** (video + audio + editing) is a multi-model media foundation; Kalainova composes **separate providers** (video, music, lipsync, motion/LivePortrait) via router/ledger rather than one jointly trained cast — [Meta Movie Gen research page](https://ai.meta.com/research/movie-gen/); local [docs/feature-map.md](../../docs/feature-map.md).
- Open training paradigms Kalainova does not run: **curating video pretraining corpora**, **3D VAE training**, **DiT pretrain/SFT**, **flow-matching schedule design**, **MLLM text-encoder alignment**—all owned by Meta/Tencent/Alibaba/NVIDIA labs — [arXiv abs 2410.13720](https://arxiv.org/abs/2410.13720); [arXiv abs 2412.03603](https://arxiv.org/abs/2412.03603); [arXiv abs 2501.03575](https://arxiv.org/abs/2501.03575).

### Inferences
- Innovative paradigms a Kalainova-class engine might still lack operationally:
  1. **Typed spatial/temporal controls** (depth, pose, traj, layout) as brief fields mapped to Transfer/ControlNet backends.
  2. **World-model rollouts** for physics/camera consistency checks before final beauty pass.
  3. **Instructional V2V** as a first-class revise path (edit the clip, don’t only retake from stills).
  4. **Joint A/V generators** instead of lipsync+music bolted on.
  5. **Latent continuation / memory** for multi-shot consistency beyond “same kit refs + prompt”.
  6. **Best-of-N + video reward model** inside `takes` before human review.
  7. **Tokenizer-level caching** (reuse VAE latents across retakes) for spend reduction.
- Kalainova already leads foundation repos on **provenance, rights, human gates, cost refusal, and kit locking**—those are not gaps; the gaps are **generative control depth** and **model-internal consistency mechanisms**.

### Gaps
- No public primary source compares Kalainova (or similar studio orchestrators) to Movie Gen/Cosmos directly; the comparison above is inferred from Kalainova’s own docs plus the cited system papers.
- Wan 3.0 Prime internals (vs Wan 2.1 paper) are vendor-opaque on fal; architectural continuity is assumed, not proven from a public 3.0 paper in this session.
- Whether any rented fal endpoint already exposes Cosmos-Transfer or Hunyuan ControlNet graphs under different slugs was not inventoried live.

---

## Cross-cutting innovative paradigms checklist (for report writer)

### Takeaway
Across 2024–2026 generation research, the reusable “new” ideas for a rented-model studio are mostly **interfaces and loops**, not novel attention formulas.

### Cited Findings
- **Latent video DiT + flow matching + 3D causal VAE** as the default open stack — [arXiv abs 2412.03603](https://arxiv.org/abs/2412.03603); [GitHub Wan-Video/Wan2.1](https://github.com/Wan-Video/Wan2.1).
- **MLLM text encoders** replacing CLIP-only conditioning — [arXiv abs 2412.03603](https://arxiv.org/abs/2412.03603); [arXiv abs 2410.13720](https://arxiv.org/abs/2410.13720).
- **Foundation cast** (video+audio+edit+personalization) — [Meta Movie Gen research page](https://ai.meta.com/research/movie-gen/).
- **World Foundation Models + Transfer controls** — [arXiv abs 2501.03575](https://arxiv.org/abs/2501.03575).
- **Real-time / distilled DiT paths** (LTX family) for cheap drafts or interactive previs — [GitHub Lightricks/LTX-Video](https://github.com/Lightricks/LTX-Video).
- **External multi-axis benchmarks (VBench)** as quality contracts — [arXiv abs 2311.17982](https://arxiv.org/abs/2311.17982).
- **Workflow-graph serving** (Comfy-like) as the OSS integration surface — inferred from ADR 0019 — local [docs/decisions/0019-self-hosted-models-workflow-runtime.md](../../docs/decisions/0019-self-hosted-models-workflow-runtime.md).

### Inferences
- A production content engine that only swaps fal slugs is ~12–18 months behind the research interface surface (controls, world models, joint A/V, instructional edit), even when its rented pixels are state-of-the-art.

### Gaps
- Live re-fetch of all PDFs/READMEs recommended before publication of any numeric claims (params, seconds, resolutions, VRAM).
- Related systems intentionally under-covered here due to tool budget: Open-Sora 2.0, Step-Video, SkyReels, Pyramid Flow, Vidu, Sora, Veo 2/3—worth a second research pass if the report needs competitive landscape breadth.
