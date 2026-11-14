# AI audio-for-video and AV sync generation systems

> **Research status:** Live web search/fetch was unavailable in this research session (tool calls rejected). Notes below are structured for the report writer from established primary literature and project pages known as of late 2025; every claim that could not be re-verified live is marked. Prefer re-fetching the cited URLs before treating quantitative numbers as authoritative.

## How do FoleyCrafter and MMAudio generate synchronized audio from video (or joint AV)?

### Takeaway
FoleyCrafter is a **video-conditioned latent diffusion Foley system** that steers a text-to-audio backbone with temporal event cues extracted from video; MMAudio is a **flow-matching / multimodal transformer** that jointly conditions on video, text, and optional audio to generate synchronized soundtrack-scale audio. Both are primarily **video→audio** (not joint AV latent decode), with sync coming from temporal conditioning rather than post-hoc alignment.

### Cited Findings
- FoleyCrafter (OpenMMLab / collaborators) frames Foley as generating sound effects that match on-screen events, built on a latent diffusion text-to-audio model with added video conditioning and temporal control — [FoleyCrafter project](https://foleycrafter.github.io/); [arXiv:2407.01494](https://arxiv.org/abs/2407.01494); [GitHub open-mmlab/FoleyCrafter](https://github.com/open-mmlab/FoleyCrafter)
- FoleyCrafter’s public materials describe a **semantic adapter** (aligning visual content to audio semantics, often via CLAP-like / audio-text space) plus a **temporal controller / adapter** that injects frame-level timing so onsets track visible events — [FoleyCrafter project](https://foleycrafter.github.io/); [arXiv:2407.01494](https://arxiv.org/abs/2407.01494)
- FoleyCrafter typically conditions generation with **video frames + optional text prompt** (category or free text for the Foley class), producing waveform/spectrogram audio intended to be laid under the same clip — [GitHub open-mmlab/FoleyCrafter](https://github.com/open-mmlab/FoleyCrafter)
- MMAudio (Cheng et al.) targets **multimodal audio generation** conditioned on video and/or text, aiming at both semantic match and temporal sync for video soundtracks — [MMAudio project](https://hkchengrex.github.io/MMAudio/); [arXiv MMAudio](https://arxiv.org/abs/2412.15322); [GitHub hkchengrex/MMAudio](https://github.com/hkchengrex/MMAudio)
- MMAudio’s design (per project/paper framing) uses a **large multimodal transformer** trained with **conditional flow matching** over audio latents, taking visual features over time plus text tokens rather than a two-stage “detect events then Foley library” pipeline — [MMAudio project](https://hkchengrex.github.io/MMAudio/); [arXiv:2412.15322](https://arxiv.org/abs/2412.15322)
- Related predecessors in the same problem class include **Diff-Foley** (contrastive audio-visual pretraining + latent diffusion for temporally aligned Foley), **Seeing and Hearing** (ImageBind-conditioned generation), **V2A-Mapper**, **SpecVQGAN**, and **Make-An-Audio / AudioLDM** as TTA backbones often adapted for V2A — [Diff-Foley arXiv](https://arxiv.org/abs/2306.17203); [Seeing and Hearing project](https://genjib.github.io/projectpage/SeeingandHearing/index.html); [AudioLDM](https://audioldm.github.io/)
- Neither FoleyCrafter nor MMAudio is primarily a **joint AV generator** in the Sora/MovieGen sense (shared latent decoding to pixels+waveform); they are **audio generators conditioned on given video**, which is the pattern production pipelines use when video is already rendered by a separate model — [FoleyCrafter project](https://foleycrafter.github.io/); [MMAudio project](https://hkchengrex.github.io/MMAudio/)

### Inferences
- For a studio engine that already rents TTS and music APIs, FoleyCrafter/MMAudio-class models fill the **diegetic / event / ambience** layer that TTS+music leave empty, not the dialogue or score layer.
- Sync in these systems is mostly **baked into conditioning and training objectives**, not a separate “nudge the WAV until SyncNet peaks” loop—though evaluation still uses sync metrics after the fact.

### Gaps
- Exact layer counts, latent rates, CFG schedules, and checkpoint sizes could not be re-verified live in this session; report writer should pull numbers from the PDFs at the arXiv links above.
- Whether MMAudio arXiv ID `2412.15322` remains the canonical citation should be confirmed on the project page (IDs sometimes shift with camera-ready versions).

## What architectures (diffusion, transformers, CLAP-like embeddings, temporal alignment)?

### Takeaway
The dominant stack is **latent diffusion or flow-matching over mel/audio latents**, with **video encoders (CLIP/ViT/ImageBind-style or specialized AV encoders)** providing per-frame or per-chunk features, **text encoders (CLAP / T5 / CLIP text)** for semantic control, and **temporal cross-attention or adapters** for alignment. Explicit onset detectors and contrastive AV sync heads appear mainly in Diff-Foley-like lines and in **evaluation**, not always inside the generator.

### Cited Findings
- **Latent diffusion TTA → V2A:** AudioLDM / AudioLDM 2 and Make-An-Audio-style VAEs compress mel spectrograms; Foley systems fine-tune or adapt UNet/DiT denoisers with visual tokens — [AudioLDM](https://audioldm.github.io/); [FoleyCrafter arXiv](https://arxiv.org/abs/2407.01494)
- **Flow matching:** MMAudio is presented as using **conditional flow matching** instead of (or alongside) classic DDPM sampling for faster/higher-quality audio latent generation under multimodal conditions — [MMAudio project](https://hkchengrex.github.io/MMAudio/); [arXiv:2412.15322](https://arxiv.org/abs/2412.15322)
- **CLAP / audio-text embeddings:** Contrastive Language-Audio Pretraining (CLAP) embeddings are widely used for (a) text conditioning, (b) semantic retrieval of Foley, and (c) **CLAP score** as a semantic quality metric for generated audio vs text or captions — [Microsoft CLAP / LAION CLAP](https://github.com/LAION-AI/CLAP); [arXiv CLAP](https://arxiv.org/abs/2206.04769)
- **ImageBind / joint embedding spaces:** Seeing-and-Hearing-style work binds vision and audio (and other modalities) so a video embedding can condition an audio diffusion prior without paired Foley labels for every event — [ImageBind](https://github.com/facebookresearch/ImageBind); [Seeing and Hearing](https://genjib.github.io/projectpage/SeeingandHearing/index.html)
- **Temporal alignment mechanisms commonly reported in this literature:**
  - Frame-wise visual feature sequences cross-attended into the denoiser
  - Temporal adapters / ControlNet-like branches on the UNet (FoleyCrafter framing)
  - Contrastive AV objectives that pull matching time windows together (Diff-Foley)
  - Optional onset / energy conditioning from optical flow, detection, or audio-visual event labels (VGGSound, AudioSet, Greatest Hits, etc.)
  — [Diff-Foley arXiv](https://arxiv.org/abs/2306.17203); [FoleyCrafter arXiv](https://arxiv.org/abs/2407.01494); [VGGSound](https://www.robots.ox.ac.uk/~vgg/data/vggsound/)
- **Transformer vs UNet:** Newer systems (MMAudio and several 2024–2025 V2A papers) move toward **DiT / multimodal transformer** backbones over UNet diffusion; FoleyCrafter remains closer to the **adapter-on-diffusion-UNet** pattern — [MMAudio project](https://hkchengrex.github.io/MMAudio/); [FoleyCrafter project](https://foleycrafter.github.io/)
- **Lip-sync / speech-specific architectures are a parallel track:** Wav2Lip, SyncTalk, MuseTalk, LatentSync, etc., drive **mouth motion from audio** (or refine video), which is the inverse problem of Foley V2A and uses SyncNet-style discriminators heavily — [Wav2Lip](https://github.com/Rudrabha/Wav2Lip); [SyncNet paper](https://www.robots.ox.ac.uk/~vgg/publications/2016/Chung16a/)

### Inferences
- Production “semantic Foley layers” map cleanly onto **CLAP-guided stems** (whoosh vs impact vs ambience) while **temporal adapters** map onto **event-driven stems**; stem-aware mixing is still mostly a **pipeline concern**, not a native multi-stem diffusion head in most OSS releases.
- Dialogue lip sync and Foley sync share metrics (offset correlation) but **not models**; conflating them in a studio bar is a common design mistake.

### Gaps
- Side-by-side parameter counts and training dataset hours for FoleyCrafter vs MMAudio were not retrieved live.
- Internal details of any commercial closed models (e.g., Runway / Pika / Luma audio tracks) are not publicly documented at the same level.

## How is sync evaluated (beyond SyncNet) and how do systems self-correct?

### Takeaway
Beyond SyncNet (lip-audio offset classification), V2A papers rely on **AV-Align / temporal alignment scores**, **onset F1**, **energy/correlation alignment**, **ImageBind or CLAP semantic scores**, **FAD / FD / KL** for audio fidelity, and **human MOS** for sync and relevance. True **self-correction** (closed-loop regenerate until sync metric passes) is rare in published systems; most “correction” is training-time contrastive loss or classifier-free guidance, not inference-time QA loops.

### Cited Findings
- **SyncNet** (Chung & Zisserman): CNN that scores lip–speech sync and estimates time offset; still the default for **talking-head** LSE-C / LSE-D style metrics, but it is **speech/mouth-centric**, not general Foley — [SyncNet / VGG](https://www.robots.ox.ac.uk/~vgg/publications/2016/Chung16a/); [Wav2Lip metrics usage](https://github.com/Rudrabha/Wav2Lip)
- **AV-Align / audiovisual alignment metrics:** Recent V2A evaluations introduce or reuse metrics that correlate **visual motion / event timing** with **audio onsets or envelope**, better suited to Foley than SyncNet — discussed across Diff-Foley, FoleyCrafter, MMAudio evaluation sections — [Diff-Foley arXiv](https://arxiv.org/abs/2306.17203); [FoleyCrafter arXiv](https://arxiv.org/abs/2407.01494); [MMAudio arXiv](https://arxiv.org/abs/2412.15322)
- **DeSync / offset-based scores:** Some pipelines report mean absolute sync offset (ms) by sliding audio against video features and maximizing a similarity curve (SyncNet-like search generalized to non-lip features) — pattern documented in talking-head and AV retrieval literature — [SyncNet](https://www.robots.ox.ac.uk/~vgg/publications/2016/Chung16a/)
- **Semantic AV metrics:** ImageBind score, CLAP score, and retrieval Accuracy@K measure whether the **right sound class** occurred, independent of frame-accurate hits — [ImageBind](https://github.com/facebookresearch/ImageBind); [CLAP](https://github.com/LAION-AI/CLAP)
- **Distributional audio quality:** Fréchet Audio Distance (FAD), KL divergence on classifier labels (PANNs), and Inception-style audio features remain standard for “does it sound real?” orthogonal to sync — [FAD paper](https://arxiv.org/abs/1812.08466)
- **Human protocol:** Papers typically ask raters for **temporal alignment**, **audio quality**, and **semantic relevance** on Likert scales; automated metrics correlate imperfectly, especially for polyphonic or ambient scenes — [FoleyCrafter arXiv](https://arxiv.org/abs/2407.01494); [MMAudio arXiv](https://arxiv.org/abs/2412.15322)
- **Self-correction in published generators:** Primary mechanisms are (1) **stronger temporal conditioning**, (2) **CFG / dual guidance** (text + video), (3) **re-sampling with different seeds**, (4) optional **post-process peak alignment** of detected onsets—not a learned critic that edits the latent mid-denoise in most OSS codebases — [GitHub FoleyCrafter](https://github.com/open-mmlab/FoleyCrafter); [GitHub MMAudio](https://github.com/hkchengrex/MMAudio)
- **Lip-sync self-correction** is more mature: SyncNet-guided losses during training (Wav2Lip) and inference-time face crops; that pattern has **not** fully transferred to general Foley QA — [Wav2Lip](https://github.com/Rudrabha/Wav2Lip)

### Inferences
- A studio engine that only checks loudness, duration, and “file exists” is missing the entire **temporal AV-Align / onset F1** family that research treats as first-class.
- Practical self-correction for production is likely **metric-gated regenerate + stem remix** (cheap) rather than training a Foley SyncNet equivalent (expensive, domain-specific).

### Gaps
- No single community-standard “Foley SyncNet” with the adoption level of lip SyncNet was confirmed; naming and implementations of AV-Align variants differ by paper—report writer should not treat one GitHub script as universal.
- Live confirmation of exact metric formulas/tables in FoleyCrafter vs MMAudio papers was blocked; cite PDF tables directly when drafting the final report.

## What OSS tooling and integration patterns exist for video gen pipelines?

### Takeaway
Integration patterns cluster into: (1) **CLI/Python callable V2A models** (FoleyCrafter, MMAudio, Diff-Foley) run after video render; (2) **ComfyUI / node-graph wrappers**; (3) **Diffusers-style pipelines**; (4) **separate TTS + music + SFX buses** mixed in ffmpeg; (5) **QA hooks** (SyncNet, CLAP, FAD, loudness) as offline jobs. Few engines ship a unified multi-stem AV critic.

### Cited Findings
- **FoleyCrafter OSS:** Official code under OpenMMLab organization; typical use is prepare video → extract frames/features → sample diffusion → write WAV aligned to video length — [GitHub open-mmlab/FoleyCrafter](https://github.com/open-mmlab/FoleyCrafter); [project](https://foleycrafter.github.io/)
- **MMAudio OSS:** Official PyTorch repo with pretrained checkpoints; README-oriented API for video+text → audio; positioned for research and demos rather than a full DAW — [GitHub hkchengrex/MMAudio](https://github.com/hkchengrex/MMAudio); [project](https://hkchengrex.github.io/MMAudio/)
- **Diff-Foley OSS:** Earlier open release often used as baseline in papers; contrastive + diffusion stack — [Diff-Foley GitHub](https://github.com/luosiallen/Diff-Foley) (verify path on search); [arXiv](https://arxiv.org/abs/2306.17203)
- **Hugging Face / demos:** Space demos and model cards are a common integration path for prototyping V2A without local GPU ops — search hubs for `MMAudio`, `FoleyCrafter`, `Diff-Foley` on [Hugging Face](https://huggingface.co/models?search=mmaudio)
- **ComfyUI ecosystem:** Community nodes wrap video-to-audio and lip-sync models so agencies chain **image/video gen → V2A → mux** in one graph (quality and maintenance vary by third-party node) — pattern visible across ComfyUI custom-node indexes (e.g. ComfyUI Manager registries); treat individual node repos as unstable deps
- **Mux / loudness tooling (production-grade, non-ML):** `ffmpeg` for mux and trim; ITU-R BS.1770 loudness (`ffmpeg loudnorm`, `pyloudnorm`); these address **delivery specs**, not sync semantics — [ffmpeg](https://ffmpeg.org/); [pyloudnorm](https://github.com/csteinmetz1/pyloudnorm)
- **Lip-sync OSS commonly bolted onto talking-head pipelines:** Wav2Lip, MuseTalk, InsightFace+audio drivers—orthogonal to Foley but often the only “AV sync” step teams run — [Wav2Lip](https://github.com/Rudrabha/Wav2Lip)
- **Dataset / training commons:** VGGSound, AudioSet, Greatest Hits, Clotho, AudioCaps—used both to train V2A and to calibrate metrics — [VGGSound](https://www.robots.ox.ac.uk/~vgg/data/vggsound/); [AudioSet](https://research.google.com/audioset/)

### Inferences
- The **lowest-risk integration** for a studio that rents providers is: keep TTS/music as SaaS stems; add **one local or rented V2A** for diegetic SFX; **ffmpeg mix** with explicit gain bus; gate on **CLAP semantic + onset alignment + loudness**.
- Node-graph (ComfyUI) integration favors experimentation; **batch job folders with locked model versions** favor reproducible studio engines (closer to Kalainova’s kit/job model).

### Gaps
- Exact ComfyUI node package names and maintenance status were not enumerated live.
- Commercial API offerings that wrap MMAudio/FoleyCrafter-class models (if any) need a fresh market scan.

## Innovative paradigms: semantic Foley layers, stem-aware mixing, event-driven audio, joint AV latent models?

### Takeaway
Research is moving from **monolithic soundtrack generation** toward **controllable, layered, event-conditioned audio**, while frontier video models experiment with **joint or tightly coupled AV**. Production practice still mostly **composites stems**. The innovative middle ground—**event graphs → per-event Foley → stem mix → sync critic**—is under-served by both pure research demos and SaaS TTS/music stacks.

### Cited Findings
- **Semantic Foley layers:** Systems that separate “what sound” (CLAP/text class) from “when” (temporal controller)—explicit in FoleyCrafter’s semantic vs temporal adapters—enable promptable categories without losing hit timing — [FoleyCrafter project](https://foleycrafter.github.io/); [arXiv:2407.01494](https://arxiv.org/abs/2407.01494)
- **Event-driven audio:** Detect or predict AV events (hits, whooshes, footsteps) then synthesize or retrieve per event; classical Foley + modern onset-conditioned diffusion; Diff-Foley’s contrastive temporal learning is a learned variant of event alignment — [Diff-Foley arXiv](https://arxiv.org/abs/2306.17203)
- **Stem-aware mixing:** Research generators usually emit **one mixed mono/stereo track**; stem separation (dialogue / music / effects) remains a **post** concern via source separation (e.g. Demucs) or by **never generating mixed** and instead calling specialized models per bus — [Demucs](https://github.com/facebookresearch/demucs)
- **Joint AV latent / native AV models:** Closed and open video generators increasingly claim **native audio** (joint training or parallel audio heads). Public research still lags video-only generators; when native audio exists, sync is implicit in joint sampling but **controllability and stem replacement** often regress — coverage in vendor blogs and AV generation surveys; treat vendor claims cautiously without paper-level detail
- **Language / LLM planners for sound design:** Emerging pattern: LLM proposes a **cue sheet** (timecoded SFX list) from a caption or shot list, then a V2A or sample library fills cues—bridges semantic layers and event-driven pipelines (mostly engineering blogs and prototype repos rather than a single canonical paper)
- **Audio-driven video vs video-driven audio:** Two opposing paradigms; talking-head stacks are audio→video; Foley stacks are video→audio; **coherence** for full pieces often needs **both** plus music bed — [Wav2Lip](https://github.com/Rudrabha/Wav2Lip); [MMAudio project](https://hkchengrex.github.io/MMAudio/)

### Inferences
- The highest-leverage “innovative” architecture for a rented-model studio is not a full joint AV foundation model—it is a **cue-sheet + multi-stem + metric gate** orchestration layer on top of existing providers.
- Joint AV latents help sync but hurt **kit identity** (voice locks, music style kits) unless stems remain editable.

### Gaps
- Sparse primary literature specifically naming “stem-aware diffusion Foley” as a solved problem; much of this is systems engineering.
- Vendor native-audio claims need dated primary citations per product when the final report is written.

## Gaps vs a studio engine that rents TTS/music providers and does basic bar/sound checks?

### Takeaway
Typical studio engines that rent **TTS + music**, mux with ffmpeg, and check **duration / peak / loudness / presence of audio** systematically omit: **diegetic Foley generation**, **frame-level AV temporal metrics**, **semantic AV relevance (CLAP/ImageBind)**, **per-stem coherence**, **lip–dialogue sync for on-camera speech**, **onset event coverage**, and **closed-loop regenerate-on-fail**. Research systems provide generators and offline metrics but rarely a production-grade **approve/publish gate**.

### Cited Findings
- **What research V2A systems optimize:** temporal alignment to visual events + semantic match + perceptual audio quality — [FoleyCrafter arXiv](https://arxiv.org/abs/2407.01494); [MMAudio arXiv](https://arxiv.org/abs/2412.15322); [Diff-Foley arXiv](https://arxiv.org/abs/2306.17203)
- **What SyncNet-class QA covers:** mouth–speech sync for talking faces—not footsteps, whooshes, or ambience — [SyncNet](https://www.robots.ox.ac.uk/~vgg/publications/2016/Chung16a/)
- **What delivery/loudness tooling covers:** integrated loudness, true peak, clipping, sample rate, channel layout—not whether the bang lands on the cut — [ffmpeg loudnorm](https://ffmpeg.org/); [ITU-R BS.1770 overview via pyloudnorm docs](https://github.com/csteinmetz1/pyloudnorm)
- **What TTS/music APIs cover:** intelligible speech and musical beds with weak or no binding to **pixel-level events**; any “sync” is usually beat-matching or subtitle timing, not visual Foley — characteristic of provider APIs such as ElevenLabs / music gen services (product docs; not V2A papers)
- **Automated QA stack research implies but studios often skip:**
  1. Onset / envelope alignment score vs optical flow or event detector
  2. CLAP or ImageBind score vs shot caption / brief
  3. FAD or PANNs label sanity vs expected classes
  4. Lip SyncNet if faces speak on screen
  5. Stem balance checks (dialogue intelligibility vs music bed)
  6. Regenerate or re-time policy when thresholds fail
  — synthesized from metric sections of [FoleyCrafter](https://arxiv.org/abs/2407.01494), [MMAudio](https://arxiv.org/abs/2412.15322), [Diff-Foley](https://arxiv.org/abs/2306.17203), [FAD](https://arxiv.org/abs/1812.08466), [CLAP](https://arxiv.org/abs/2206.04769), [SyncNet](https://www.robots.ox.ac.uk/~vgg/publications/2016/Chung16a/)
- **Human gate still required:** papers and production ADRs alike treat automated sync scores as **necessary but insufficient**; polyphonic scenes and stylistic silence (intentional mute) defeat naive metrics — [FoleyCrafter human studies](https://arxiv.org/abs/2407.01494)

### Inferences
- Kalainova-like engines that already enforce **human approve** and **bar checks** are ahead on process gates but behind research on **AV temporal critics** and **diegetic generation**.
- Highest ROI omissions to close: (1) optional V2A Foley pass for non-talking pieces, (2) CLAP-vs-brief semantic check, (3) onset-alignment check for cut-driven SFX, (4) SyncNet only when a face speaks—gated by scene type so ambience pieces aren’t falsely failed.

### Gaps
- This session could not inspect Kalainova’s current `bar` implementation or `studio.yaml` audio checks; comparison to “basic bar/sound checks” is against the objective’s stated baseline, not a verified inventory of the repo.
- Cost/latency of running MMAudio or FoleyCrafter per job (GPU-minutes, $) needs a fresh benchmark on target hardware.

---

## Source index (for report writer)

| Topic | Primary URL |
|-------|-------------|
| FoleyCrafter project | https://foleycrafter.github.io/ |
| FoleyCrafter paper | https://arxiv.org/abs/2407.01494 |
| FoleyCrafter code | https://github.com/open-mmlab/FoleyCrafter |
| MMAudio project | https://hkchengrex.github.io/MMAudio/ |
| MMAudio paper | https://arxiv.org/abs/2412.15322 |
| MMAudio code | https://github.com/hkchengrex/MMAudio |
| Diff-Foley | https://arxiv.org/abs/2306.17203 |
| AudioLDM | https://audioldm.github.io/ |
| CLAP | https://arxiv.org/abs/2206.04769 |
| ImageBind | https://github.com/facebookresearch/ImageBind |
| SyncNet | https://www.robots.ox.ac.uk/~vgg/publications/2016/Chung16a/ |
| FAD | https://arxiv.org/abs/1812.08466 |
| Wav2Lip | https://github.com/Rudrabha/Wav2Lip |
| VGGSound | https://www.robots.ox.ac.uk/~vgg/data/vggsound/ |

**Epistemic note for report writer:** Prefer quoting tables and architecture diagrams from the PDFs at the arXiv links. Where this note says “framing,” “typically,” or “per project,” re-open the primary page before elevating to a hard claim. Live fetch was unavailable during note collection.
