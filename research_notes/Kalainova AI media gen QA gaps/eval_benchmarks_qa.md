# AI video evaluation benchmarks and automated review QA

> **Session note:** Live WebSearch/WebFetch/curl were blocked in this research pass (domains not allowlisted / calls rejected). Findings below are synthesized from established primary literature and project pages known for these systems, cross-checked against Kalainova’s local `docs/studio-bar.md`, ADR 0011/0016/0017, and `bar/` + `qa.py` code. Treat paper titles and GitHub/arXiv URLs as the intended primary sources; re-fetch before shipping citations into a public report if any arXiv IDs must be exact.

## What dimensions does each benchmark/metric cover (motion, aesthetics, fidelity, consistency, sync, human preference)?

### Takeaway
Research suites split into (1) multi-axis generative-model benchmarks (VBench / VBench-2.0), (2) learned human-preference / multi-aspect judges (VideoScore), (3) no-reference perceptual VQA disentangling aesthetics vs technical quality (DOVER), and (4) classical AV-sync detectors (SyncNet). None of them, alone, covers production concerns like brand, rights, kit identity locks, or platform ingest.

### Cited Findings
- **VBench** (“VBench: Comprehensive Benchmark Suite for Video Generative Models”) organizes evaluation into a hierarchical suite of quality and semantic dimensions commonly reported as ~16 axes, including subject consistency, background consistency, temporal flickering, motion smoothness, dynamic degree, aesthetic quality, imaging quality, plus prompt-conditioned semantic checks (object class, multiple objects, human action, color, spatial relationship, scene, appearance/temporal style, overall consistency). — [VBench project](https://vchitect.github.io/VBench-project/); [arXiv:2311.17982](https://arxiv.org/abs/2311.17982); [GitHub Vchitect/VBench](https://github.com/Vchitect/VBench)
- **VBench quality axes** emphasize motion/temporal integrity (flicker, smoothness, how much moves) and perceptual look (aesthetic + imaging), while **semantic axes** emphasize text–video fidelity / prompt following rather than studio craft delivery. — [arXiv:2311.17982](https://arxiv.org/abs/2311.17982)
- **VBench-2.0** shifts emphasis from perceptual/“looking good” scores toward **intrinsic faithfulness**: human fidelity (anatomy, identity-like stability of people), controllability, creativity, and commonsensical / physical plausibility—explicitly targeting failure modes that earlier suites under-weighted. — [VBench project / VBench-2.0 materials](https://vchitect.github.io/VBench-project/); [GitHub Vchitect/VBench](https://github.com/Vchitect/VBench) (2.0 docs/branch as published by authors)
- **VideoScore** (“VideoScore: Building Automatic Metrics to Simulate Fine-grained Human Feedback for Video Generation”) scores generated clips on multi-aspect human-feedback dimensions typically reported as visual quality, temporal consistency, dynamic degree, text-to-video alignment, and factual consistency—i.e., a preference-style judge rather than a classical distortion metric. — [arXiv:2406.15252](https://arxiv.org/abs/2406.15252); [GitHub TIGER-AI-Lab/VideoScore](https://github.com/TIGER-AI-Lab/VideoScore)
- **DOVER** (“Exploring Video Quality Assessment on User Generated Contents from Aesthetic and Technical Perspectives”, CVPR 2023) disentangles **aesthetic quality** (looks pleasing / composition-like) from **technical quality** (compression, blur, noise, other distortions), producing separable and fused scores for no-reference VQA. — [arXiv:2211.04894](https://arxiv.org/abs/2211.04894); [GitHub QualityAssessment/DOVER](https://github.com/QualityAssessment/DOVER) (also mirrored under VQAssessment orgs in community forks)
- **SyncNet** (“Out of Time: Automated Lip Sync in the Wild”, Chung & Zisserman) measures **audio–visual lip synchrony**, not picture aesthetics: whether mouth motion matches speech timing. Downstream talking-head papers (e.g. Wav2Lip lineage) popularized SyncNet-derived **LSE-D / LSE-C** (distance / confidence) as sync metrics. — [Oxford VGG SyncNet page](https://www.robots.ox.ac.uk/~vgg/software/lipsync/); [Chung & Zisserman publication page](https://www.robots.ox.ac.uk/~vgg/publications/2016/Chung16a/); [syncnet_python](https://github.com/joonson/syncnet_python)
- Adjacent T2V research judges (often co-cited with the above) add complementary axes: **FVD** for distributional video realism vs real footage, **CLIP/UMT-style text–video similarity** for prompt adherence, **EvalCrafter / FETV / T2V-CompBench / ChronoMagic-Bench** for compositional, temporal, or longer-horizon prompt suites, and **PhyGenBench**-class work for physical plausibility. — [FVD / “Towards Accurate Generative Models of Video” literature commonly linked via paperswithcode Video Generation benchmarks](https://paperswithcode.com/task/video-generation); [EvalCrafter](https://github.com/evalcrafter/EvalCrafter)
- Kalainova’s published bar layers explicitly separate **delivery** (tool), **craft** (tool then human), and **taste/acceptance** (human), and lists craft signals such as banding/CAMBI, stutter, detail, repetition, corner marks, moving share, shot motion, cuts/min, audio mix/clipping, song tempo/loudness—not VBench-style semantic prompt axes. — local [`docs/studio-bar.md`](../../docs/studio-bar.md); ADR [0011](../../docs/decisions/0011-the-studio-bar.md)

### Inferences
- “Automated review” in T2V research usually means **multi-metric model ranking** or **learned preference scoring of short clips**, not end-to-end studio QA of a finished master.
- Sync and identity are different problems: SyncNet answers “does the mouth match the audio?”; kit face embedding (YuNet/SFace) answers “is this the locked character?”—both can pass while story/craft fails.
- VBench-2.0’s faithfulness turn is the research community’s closest analogue to “does this shot violate physics / anatomy / control?” which production vision-LLM judges also chase via motion strips.

### Gaps
- Exact VBench-2.0 dimension list, paper title string, and arXiv ID could not be re-fetched live this session; confirm against the project page before quoting a definitive dimension table.
- VideoScore2 / later checkpoints’ exact aspect taxonomy and correlation numbers vs humans were not re-verified online here.
- Head-to-head correlation tables (which metric best predicts human “ship it?” for long-form edited pieces) remain sparse in public literature; most papers evaluate short single-shot generations.

## What model architectures / classical CV algorithms underlie them?

### Takeaway
These systems are ensembles of frozen vision backbones, optical-flow / quality networks, and (for VideoScore) fine-tuned video-LMMs—not a single “video GPT judge.” Classical CV (flow, face crops, MFCC audio) still underpins motion and sync; modern suites wrap those signals in CLIP/DINO/aesthetic predictors or regression heads.

### Cited Findings
- **VBench** does not train one monolithic critic; it **composes specialist metrics**: DINO/ViT-style features for subject consistency across frames; CLIP image–text or video–text similarities for many semantic dimensions; LAION aesthetic predictors for aesthetic quality; image-quality networks such as **MUSIQ** for imaging quality; **RAFT** (or related optical-flow) statistics for motion smoothness / temporal flicker / dynamic degree. — [arXiv:2311.17982](https://arxiv.org/abs/2311.17982); [GitHub Vchitect/VBench](https://github.com/Vchitect/VBench)
- **VBench-2.0** extends the same “suite of specialized evaluators” pattern into faithfulness checks (often mixing detectors, pose/anatomy heuristics, VLM questions, and physics-oriented probes—exact module list is paper-defined). — [VBench project](https://vchitect.github.io/VBench-project/)
- **VideoScore** trains / fine-tunes a **video multimodal LLM / vision-language backbone** on the **VideoFeedback** multi-aspect human rating dataset so the model regresses or ranks clips like a fine-grained human rater. — [arXiv:2406.15252](https://arxiv.org/abs/2406.15252); [GitHub TIGER-AI-Lab/VideoScore](https://github.com/TIGER-AI-Lab/VideoScore)
- **DOVER** builds on the **FAST-VQA** family: efficient video quality transformers that sample **spatial–temporal fragments** (grid/tube fragments) rather than full-resolution full-length encode, with **disentangled aesthetic and technical heads** fused for a final score. — [arXiv:2211.04894](https://arxiv.org/abs/2211.04894); [FAST-VQA companion work commonly linked from DOVER README](https://github.com/QualityAssessment/DOVER)
- **SyncNet** is a **two-stream CNN**: one stream embeds face/mouth crops over a short window; the other embeds audio features (classically MFCC); trained with a **contrastive sync vs shifted-audio** objective so cosine distance encodes lip-sync error. — [Chung & Zisserman 2016](https://www.robots.ox.ac.uk/~vgg/publications/2016/Chung16a/); [software page](https://www.robots.ox.ac.uk/~vgg/software/lipsync/)
- Classical / still-used NR image metrics often appear beside these in pipelines: **NIQE/BRISQUE**, **LPIPS**, **CLIPScore**, **FVD** (I3D feature Fréchet distance), optical-flow magnitude histograms, face detectors for talking-head crops. — survey-style coverage in video quality / AIGC eval papers citing these baselines; see also [paperswithcode Video Quality Assessment](https://paperswithcode.com/task/video-quality-assessment)
- Kalainova craft readings are largely **deterministic signal processing / ffmpeg–VMAF-adjacent** (e.g. CAMBI when `libvmaf` present), frame-difference stutter, and optional OpenCV **YuNet + SFace** embeddings—not CLIP/DINO suites. Vision-LLM judging is a separate advisory layer over motion/cut strips. — local [`docs/studio-bar.md`](../../docs/studio-bar.md); [`src/kalainova/bar/identity.py`](../../src/kalainova/bar/identity.py); [`src/kalainova/qa.py`](../../src/kalainova/qa.py)

### Inferences
- Architectural pattern A: **metric zoo** (VBench)—cheap to interpret per failure mode, heavy to maintain, hard to turn into one reward scalar without weighting debates.
- Architectural pattern B: **learned scalar/multi-head judge** (VideoScore, DOVER)—easy to plug into ranking/RL, opaque when it fails, drifts as generators improve (distribution shift).
- Architectural pattern C: **task-specific classical detector** (SyncNet, face ID)—high precision on one contract (sync / identity), zero coverage of taste.

### Gaps
- Implementation details of every VBench-2.0 sub-evaluator (which exact detectors/VLMs) need a fresh paper PDF read.
- Whether labs still prefer SyncNet LSE vs newer AV-HuBERT / Wav2Vec-based sync critics for 2025 talking-head stacks was not verified live.

## How are they used in training (reward models, RLHF/RLAIF) vs inference-time filtering vs human-in-the-loop?

### Takeaway
The same scores serve three roles: offline leaderboards for model selection, inference-time best-of-N / reject filters, and (increasingly) reward models for preference optimization—while humans still label the datasets that train the judges and adjudicate edge cases.

### Cited Findings
- **Leaderboard / research eval:** VBench and successors publish prompt suites and aggregate radar/score tables so labs compare T2V systems under a shared protocol (fixed prompts, reported per-dimension and overall scores). — [VBench project](https://vchitect.github.io/VBench-project/); [arXiv:2311.17982](https://arxiv.org/abs/2311.17982)
- **Inference-time filtering / selection:** Learned judges (VideoScore, DOVER aesthetic/technical) are commonly used to **rank multiple samples** of the same prompt and keep the top-k—classic best-of-N without updating generator weights. — [VideoScore paper framing as automatic fine-grained feedback](https://arxiv.org/abs/2406.15252); [DOVER as deployable NR-VQA](https://arxiv.org/abs/2211.04894)
- **Reward modeling / RLHF–RLAIF:** VideoScore is explicitly motivated as simulating fine-grained human feedback usable for improving generators; broader T2V work uses preference models (VideoScore-like, VisionReward-like, CLIP-aesthetic hybrids) inside RL, DPO, or reject-sampling loops. SyncNet LSE sometimes appears as an auxiliary loss/metric for talking-head training (Wav2Lip-style), not as a general video reward. — [arXiv:2406.15252](https://arxiv.org/abs/2406.15252); SyncNet use in lip-sync training literature via [VGG lipsync](https://www.robots.ox.ac.uk/~vgg/software/lipsync/)
- **Human-in-the-loop:** Human ratings create VideoFeedback / VQA MOS datasets that train judges; benchmark papers still report human studies to validate automatic metrics; production-facing systems keep humans for taste and policy. — [arXiv:2406.15252](https://arxiv.org/abs/2406.15252); Kalainova ADR [0011](../../docs/decisions/0011-the-studio-bar.md) (taste stays human); ADR [0017](../../docs/decisions/0017-autonomy-level-per-review-gate.md) (gates may later move to by-exception/audit after measured agreement)
- **Cost-ordered generate–eval loops (production-shaped):** Kalainova ADR 0016 documents free → cheap → paid stages and layered checks (contract → measured → identity → model judge → human), with model judges advisory until calibrated against human verdicts—an explicit alternative to “score then RL forever.” — local [ADR 0016](../../docs/decisions/0016-refinement-ladder-and-layered-qa.md)

### Inferences
- Research loops optimize **model weights or sample rank** against proxy metrics; studio loops optimize **spend and gate reliability** against human ship decisions.
- Using VBench dimensions as RL rewards is risky without careful weighting—maximizing “dynamic degree” can fight “subject consistency.”
- Kalainova’s “signals must separate good from bad on reviewed samples or die” is a calibration doctrine most research metrics lack once published.

### Gaps
- Public, detailed postmortems of which reward mixes actually improved shipped T2V products (vs gaming the metric) are rare; most evidence is academic ablation.
- Exact industry wiring (which commercial video APIs run DOVER/VideoScore server-side) is not transparently documented.

## What OSS packages, leaderboards, and integration patterns exist?

### Takeaway
OSS centers on GitHub eval harnesses (VBench, VideoScore, DOVER, SyncNet) plus prompt-suite benchmarks; integration patterns are “score a folder of MP4s,” “plug score into sample ranker,” or “report radar charts.” Few packages speak job folders, rights, or approval hashes.

### Cited Findings
- **VBench OSS + leaderboard:** Installable evaluation code, prompt lists, and a public project/leaderboard presence for comparing generative models. — [GitHub Vchitect/VBench](https://github.com/Vchitect/VBench); [project/leaderboard](https://vchitect.github.io/VBench-project/)
- **VideoScore OSS:** Model checkpoints + inference scripts to score videos on multi-aspect axes; positioned for automatic feedback / evaluation. — [GitHub TIGER-AI-Lab/VideoScore](https://github.com/TIGER-AI-Lab/VideoScore); [arXiv:2406.15252](https://arxiv.org/abs/2406.15252)
- **DOVER OSS:** Pretrained weights and inference for aesthetic / technical / fused scores on arbitrary videos (UGC origins, widely reused for AIGC). — [GitHub QualityAssessment/DOVER](https://github.com/QualityAssessment/DOVER); [arXiv:2211.04894](https://arxiv.org/abs/2211.04894)
- **SyncNet OSS:** Reference pipelines to compute sync confidence/distance on talking-head video; many forks wrap preprocessing (face track → crops → score). — [VGG software](https://www.robots.ox.ac.uk/~vgg/software/lipsync/); [joonson/syncnet_python](https://github.com/joonson/syncnet_python)
- **Related OSS / suites often wired beside them:** EvalCrafter; FETV; T2V-CompBench; ChronoMagic-Bench; LAION aesthetic predictor; RAFT; CLIP variants; FVD implementations in common video-gen codebases. — [EvalCrafter GitHub](https://github.com/evalcrafter/EvalCrafter); [paperswithcode video generation](https://paperswithcode.com/task/video-generation)
- **Integration pattern — research harness:** generate N clips per prompt → run metric suite → aggregate CSV/radar → publish model table. — described across VBench README workflows ([GitHub](https://github.com/Vchitect/VBench))
- **Integration pattern — sample filter:** parallel decode → DOVER/VideoScore → keep max score under latency budget. — implied by VideoScore “automatic metrics” framing ([arXiv:2406.15252](https://arxiv.org/abs/2406.15252))
- **Integration pattern — talking-head QA:** detect face → SyncNet window scores → threshold LSE for reject/retry. — SyncNet + Wav2Lip evaluation practice ([VGG lipsync](https://www.robots.ox.ac.uk/~vgg/software/lipsync/))
- **Integration pattern — studio job QA (Kalainova):** `kalainova bar` + `qa` writes structured checks; vision judge optional; human `approve` bound to bytes; layered autonomy planned. — [`docs/feature-map.md`](../../docs/feature-map.md); [`docs/studio-bar.md`](../../docs/studio-bar.md)

### Inferences
- Dropping VBench/DOVER into Kalainova would look like **new free/cheap measured or model-check layers**, not a replacement for approve/publish.
- Leaderboards optimize **generator research**; studio packages optimize **per-piece gate decisions**—different packaging, different success criteria.

### Gaps
- No live scrape of current VBench leaderboard top models or DOVER star/fork counts this session.
- Packaging quality (PyPI modules vs research scripts requiring conda + GPU) varies; operational cost to run full VBench on every take was not benchmarked here.

## What gap remains between research eval and production studio QA (craft, brand, identity, rights)?

### Takeaway
Research eval measures short-clip perceptual quality, prompt adherence, and increasingly faithfulness; production studio QA must also enforce delivery specs, locked identity, rights/licence, edit craft, platform ingest, and a human ship gate. Those production dimensions are mostly absent from VBench-class suites.

### Cited Findings
- Research suites assume the unit of evaluation is a **generated clip vs a text prompt** (sometimes I2V), scored for quality/semantics/faithfulness—not a multi-shot edit with captions, loudness targets, and platform masters. — [VBench](https://arxiv.org/abs/2311.17982); [VideoScore](https://arxiv.org/abs/2406.15252)
- DOVER’s aesthetic/technical split comes from **UGC quality assessment**, which correlates with “looks clean/pretty” but not with brand voice, claim sourcing, or kit canon. — [arXiv:2211.04894](https://arxiv.org/abs/2211.04894)
- SyncNet covers **lip sync only**; it does not certify the speaker’s identity, the words’ factuality, or mix levels. — [VGG SyncNet](https://www.robots.ox.ac.uk/~vgg/software/lipsync/)
- Kalainova documents explicit non-goals of the bar: it cannot judge writing, performance, or whether a shot “looks real”; taste stays human; rights/licence checks and human approve/publish are first-class. — [`docs/studio-bar.md`](../../docs/studio-bar.md) (“What only eyes can catch”, “Known gaps”); ADR [0011](../../docs/decisions/0011-the-studio-bar.md); licence checks in [`qachecks.py`](../../src/kalainova/qachecks.py)
- Production craft signals Kalainova already names (banding, stutter, CAMBI, hard audio cuts, LUFS/true peak, ProRes master atoms, caption profiles) are **delivery/craft conformance**, largely orthogonal to CLIP-aesthetic or VBench semantic scores. — [`docs/studio-bar.md`](../../docs/studio-bar.md)
- Identity as **kit-attested face embeddings** (YuNet/SFace; agents never attest kits) is a studio contract research benchmarks do not encode. — [`bar/identity.py`](../../src/kalainova/bar/identity.py); AGENTS.md hard rules on human kit attestation
- Innovative research paradigms beyond simple PSNR-like checks include: disentangled aesthetic vs technical (DOVER); fine-grained multi-aspect preference imitation (VideoScore); faithfulness / physics probes (VBench-2.0); metric zoos with per-failure interpretability (VBench); RLAIF with VLM judges; best-of-N with learned rewards. Production innovation leans instead toward **layered cost-ordered gates**, **verdict-calibrated signals**, and **autonomy levels** (shadow → by-exception → audit). — [DOVER](https://arxiv.org/abs/2211.04894); [VideoScore](https://arxiv.org/abs/2406.15252); [VBench-2.0 project](https://vchitect.github.io/VBench-project/); local ADR [0016](../../docs/decisions/0016-refinement-ladder-and-layered-qa.md), [0017](../../docs/decisions/0017-autonomy-level-per-review-gate.md)

### Inferences
- The largest structural gap is **unit of work**: clip-vs-prompt vs job-vs-stream-vs-kit-vs-platform.
- Brand and rights are policy/provenance problems; no amount of DOVER score substitutes for `rights` and licence obligations.
- Faithfulness metrics (VBench-2.0) and motion-strip VLM judges are converging on similar failure classes (anatomy, impossible motion)—possible bridge layer.

### Gaps
- Little published work measures whether VBench/VideoScore rankings predict **human approve rates** on multi-minute edited programs.
- “Brand consistency” automated metrics for generative video remain immature relative to face ID and prompt CLIP scores.

## What would a Kalainova-like bar/qa system be missing relative to these?

### Takeaway
Relative to the research stack, a Kalainova-like system is strong on delivery/craft, identity locks, rights, layered human gates, and advisory VLM review—but thin on standardized multi-axis generative metrics (consistency via DINO/CLIP, DOVER aesthetics/technical, VideoScore preference heads, SyncNet lip-sync, faithfulness/physics suites) and on leaderboard-style generator selection loops.

### Cited Findings
- **Already present (Kalainova-like):** pixel craft signals; delivery/master conformance; YuNet/SFace identity vs kit; motion/cut strips; vision-LLM judge writing `findings.json`; human approval gate; cost-ordered ladder; verdict/signal calibration doctrine. — [`docs/studio-bar.md`](../../docs/studio-bar.md); [`qa.py`](../../src/kalainova/qa.py); ADR [0011](../../docs/decisions/0011-the-studio-bar.md), [0016](../../docs/decisions/0016-refinement-ladder-and-layered-qa.md)
- **Missing vs VBench:** frozen, comparable scores for subject/background consistency, temporal flicker, motion smoothness, dynamic degree, imaging/aesthetic predictors, and prompt-semantic axes usable to compare generators or takes under a shared protocol. — [arXiv:2311.17982](https://arxiv.org/abs/2311.17982)
- **Missing vs VBench-2.0:** dedicated intrinsic-faithfulness probes (physics, commonsensical interaction, structured human-fidelity checks) beyond generic VLM freeform findings. — [VBench project](https://vchitect.github.io/VBench-project/)
- **Missing vs VideoScore:** a **calibrated multi-aspect preference model** trained on fine-grained human feedback for ranking takes automatically (visual quality / temporal consistency / dynamics / T2V alignment / factuality)—today’s judge is rubric/LLM advisory, not a VideoFeedback-style regressor. — [arXiv:2406.15252](https://arxiv.org/abs/2406.15252); local judge path in [`qa.py`](../../src/kalainova/qa.py)
- **Missing vs DOVER:** a cheap NR **aesthetic vs technical** split score for prefiltering ugly/distorted takes before human review. — [arXiv:2211.04894](https://arxiv.org/abs/2211.04894)
- **Missing vs SyncNet:** automated **lip-sync distance/confidence** for dialogue/dubbing/talking-head shots (Kalainova has mix/loudness and identity, not mouth–audio sync). — [VGG SyncNet](https://www.robots.ox.ac.uk/~vgg/software/lipsync/); [`docs/studio-bar.md`](../../docs/studio-bar.md) sound/identity sections
- **Missing vs research generate–eval loops:** first-class best-of-N ranking by learned video rewards; FVD-style distributional eval (usually irrelevant per single job); public prompt-suite regression tests against generator upgrades. — [VBench workflows](https://github.com/Vchitect/VBench); [VideoScore](https://github.com/TIGER-AI-Lab/VideoScore)
- **Not missing (research is missing these):** platform ingest masters, LUFS gates, licence obligations, kit attestation, approve-bound bytes, stream strategy separation, rights classes—Kalainova-like systems are ahead here. — AGENTS.md hard rules; [`docs/studio-bar.md`](../../docs/studio-bar.md); ADR [0007]-class publish gate as referenced in project context

### Inferences
- Highest-leverage imports for a Kalainova-like bar are likely: **DOVER (or FAST-VQA) as a cheap craft prefilter**, **SyncNet for speech-driven shots**, **selective VBench consistency/flicker metrics** as measured warnings, and optionally **VideoScore** only after local calibration against `kalainova verdict` labels (ADR 0011 doctrine).
- Blindly optimizing VBench totals would conflict with Kalainova’s rule that only objective defects block and taste stays human.
- VBench-2.0 faithfulness and the existing motion-strip VLM judge should be treated as competing implementations of the same layer—measure agreement, don’t run both unpaid forever.

### Gaps
- No empirical correlation study in-repo between current bar readings / judge findings and VBench/DOVER/VideoScore on the same jobs (would require private `$KALAINOVA_HOME` media, out of scope for this public-repo research pass).
- Live confirmation of package install footprints, GPU requirements, and per-minute runtime costs for each OSS judge was blocked by network restrictions this session.
