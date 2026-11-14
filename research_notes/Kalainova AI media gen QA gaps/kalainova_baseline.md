# Kalainova baseline: generation and automated review/QA

Local codebase map of what Kalainova **already does** for media generation and automated review/QA, for fair external gap analysis. Sourced only from this repo (2026-11-14). Paths are absolute `file://` links into `/Users/km2411/Desktop/work/kalainova`.

Architectural pattern in one line: **rent models through a budgeted router; own the contract, kit lock, ffmpeg render, measured bar, and human gates.** Video is drafted as an **animatic of stills**, not as local video generation ([ADR 0016](file:///Users/km2411/Desktop/work/kalainova/docs/decisions/0016-refinement-ladder-and-layered-qa.md)).

---

## What generation stack does it use (rented models vs local, control signals, lip sync, graphics)?

### Takeaway
Kalainova generates through a capability router over swappable providers (primarily fal + ElevenLabs + Anthropic rented; optional Mac GPU / Hugging Face Spaces / local placeholders), with kit reference images as identity control, optional end-frame and LivePortrait motion, fal lipsync, and HyperFrames for exact drawn graphics — then assembles and grades everything with ffmpeg.

### Cited Findings

**Orchestration and ownership**
- Every model call goes through `providers/router.py`: preference list → ledger reserve → deadline → output check → settle cost; paid identical requests can be reused with no charge. — [ARCHITECTURE.md §Component view: model access](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md); [src/kalainova/providers/router.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/providers/router.py)
- Models are swapped in config, not code: `config/studio.yaml` holds preference chains, model slugs, prices, deadlines, reference/video schemas, bar limits, and identity settings. — [config/studio.yaml](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml); [AGENTS.md](file:///Users/km2411/Desktop/work/kalainova/AGENTS.md)
- Layer view marks **Generated video / Songs / Comics / QA / Human gate** as *partial*; **ffmpeg compile and render**, **router**, **adapters** as *built*; some producers (explainers) *planned*. — [ARCHITECTURE.md §Layer view](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)
- Known gap: “Nothing added since ADR 0012 has run on a real model… Faked models prove the wiring, not the result.” Vendor slugs marked VERIFY are unconfirmed. — [ARCHITECTURE.md §Known gaps](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)

**Default preference / rented stack (studio.yaml)**
- Capabilities and default order: `llm`/`judge` → anthropic; `voice`/`music`/`sfx`/`song` → elevenlabs then fal/local; `image` → fal, local; `video` → fal only; `lipsync` → fal; `motion` → fal, mac, local; `graphics` → hyperframes; `transcribe` → fal; `search` → exa, wikipedia, openalex; `separate` empty by default (opt-in). — [config/studio.yaml `preference:`](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)
- Current fal models (as configured): image/edit `google/nano-banana-2.1`; video/image-to-video/reference-to-video `alibaba/wan-3.0-prime/...`; lipsync `fal-ai/sync-lipsync/v2`; motion `fal-ai/live-portrait`; music `fal-ai/lyria3`; song `minimax/music-3`; separate `fal-ai/demucs`; transcribe `fal-ai/whisper`. — [config/studio.yaml `models.fal`](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)
- Anthropic: planner `claude-opus-5-5`, judge `claude-haiku-4-5`. ElevenLabs: voice `eleven_v4_turbo`, music/song `music_v2_5`. — [config/studio.yaml `models`](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)
- Provider adapters present: `fal`, `remote` (Anthropic, ElevenLabs), `mac`, `local` (placeholders), `spaces` (hosted free apps), `hyperframes`, `whispercpp`, `compat` (OpenAI-compatible LLM vendors), `search`. — [ARCHITECTURE.md §providers](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md); [src/kalainova/providers/](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/providers/)

**Local / on-machine generation**
- `mac` runs open models on Mac GPU (Kokoro TTS, mflux image, LTX-2 video, MiniMax music, Whisper, HeartMuLa/ACE-Step song, LivePortrait motion); runners live under `providers/runners/` and the engine never imports them. — [config/studio.yaml `models.mac`](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml); [ARCHITECTURE.md §providers](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)
- `local` provider makes placeholders that `approve` refuses; listed so runs without keys still wire through. — [ARCHITECTURE.md §model access](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md); [config/studio.yaml](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)
- ADR 0016 rule: “Video is never drafted by generating video locally. Its draft is the animatic: accepted stills, cut to accepted audio.” — [docs/decisions/0016-…md](file:///Users/km2411/Desktop/work/kalainova/docs/decisions/0016-refinement-ladder-and-layered-qa.md)
- HyperFrames graphics: free, on-machine via `npx hyperframes render`; synthetic=false (drawn, not generated); Node 22+. — [src/kalainova/providers/hyperframes.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/providers/hyperframes.py)

**Control signals / conditioning**
- Stream kits pin face/voice/persona/places/style; jobs lock exact kit versions; `consistency` builds/verifies the lock and injects refs into shots. — [ARCHITECTURE.md §Kits, streams, and jobs](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md); [src/kalainova/consistency.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/consistency.py)
- `reference_models` configures how image/video models take reference images (params, max images, tags, durations); only listed models may be pinned by a stream with a character. — [config/studio.yaml `reference_models`](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)
- `video_models` configures image-to-video / text-to-video inputs including optional `end_image_param` (start + end frame). — [config/studio.yaml `video_models`](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)
- Shot prompts split still vs motion; motion prompts truncated to model word limits (`prompt_words_max`). Continuity text shared across shots. — [src/kalainova/shots.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/shots.py); [ARCHITECTURE.md §shots](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)
- `shotmake.take_clip` sends start still (+ optional end still), duration, aspect, seed, optional clip audio flag to video provider. — [src/kalainova/shotmake.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/shotmake.py)
- Capability `motion` = LivePortrait-style drive: character image + driving video → animated face (`router.motion`, fal/mac/local). Separate from I2V. — [src/kalainova/providers/router.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/providers/router.py); [config/studio.yaml](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)
- Drawn / kinetic captions, title/quote/stat cards via HyperFrames then ffmpeg overlay; film profiles burn nothing. — [ARCHITECTURE.md §render](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)

**Lip sync**
- After a moving shot, if `beat.on_camera`, `shotmake.lip_sync` pads the line WAV to clip length, calls capability `lipsync` (fal Sync Lipsync v2), keeps pre-sync clip beside synced. — [src/kalainova/shotmake.py `lip_sync`](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/shotmake.py); [src/kalainova/assets.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/assets.py); [config/studio.yaml](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)

**Graphics / non-model visuals**
- Beats with `graphics` go through `shotmake.graphics_shot` → HyperFrames provider. — [src/kalainova/shotmake.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/shotmake.py)
- `motion` module: camera on a still via sub-pixel sampling → 16-bit RGB to ffmpeg (animatic / Ken Burns style). — [ARCHITECTURE.md §motion](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)
- Comics: models generate art **with no words**; engine layouts pages, balloons, lettering. Books: typeset EPUB + page images. — [ARCHITECTURE.md §comic / §story](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)

**Render / delivery stack (owned)**
- Edit manifest → closed op list (`spec`) → ffmpeg execute with step cache; picture intermediates lossless 10-bit; export web H.264 + optional ProRes master (film-hd/uhd). — [ARCHITECTURE.md §render](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md); [src/kalainova/render/](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/render/)
- Grade via LUT (`look`); loudness targets per profile in studio.yaml. — [ARCHITECTURE.md §look](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md); [config/studio.yaml `profiles`](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)
- Open-tool adapters (ADR 0012): beats / speech_cuts / timeline seams; default `inhouse`, optional beat_this, auto-editor, OpenTimelineIO. — [config/studio.yaml `adapters`](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml); [ARCHITECTURE.md §opentools](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)

**Piece pipeline (generation order)**
- request → preflight kits → plan → assets (refs, voice, stills/video) → edit → render → QA → human approve → publish. Animatic path: assets(animatic) → stills+voice → animatic.mp4 → human verdict → then paid video. — [ARCHITECTURE.md §Sequence / §preproduction](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)

### Inferences
- Generation is **aggregator-first (fal) + specialist SaaS (ElevenLabs, Anthropic)**, with Mac as optional free/local path — not a single foundation model pipeline.
- Identity continuity is primarily **reference-image pinning + kit lock**, not ControlNet/IP-Adapter as first-class engine concepts (those may exist inside rented model APIs, but the engine’s contract is reference URLs / kit_refs).
- `local` in preference is a **dev/wiring fallback**, not a production generation path for releaseable media.

### Gaps
- Exact runtime wiring of LivePortrait `motion` into the main short/film assets loop vs editor/clip paths was not fully traced shot-by-shot beyond the provider surface and ARCHITECTURE description; lip_sync *is* explicitly called from assets for `on_camera` beats.
- Whether every VERIFY-marked fal slug has been production-validated: ARCHITECTURE states they have not.
- No inventory of which capabilities each operator actually has keys for (harness-private); baseline is what the engine *supports*.

---

## What QA layers exist (technical, craft bar, vision judge, kit identity, human gate)?

### Takeaway
QA is layered roughly as ADR 0016 describes — contract → measured bar → kit lock/identity → advisory vision judges → human decision — with `fail` blocking approval and most craft/judge signals as `warn` (or advisory still-judge before paid motion). Autonomy levels are schema-declared (ADR 0017) but not implemented in runtime Python.

### Cited Findings

**ADR 0016 layered QA (accepted decision)**
- Layers 0–4: Contract (free, blocks) → Measured numbers (free, blocks objective faults only) → Identity and lock (free, blocks) → Model check yes/no with citations, may say unsure (cheap, **does not block** until calibrated) → Person accept/fix/reject. — [docs/decisions/0016-…md](file:///Users/km2411/Desktop/work/kalainova/docs/decisions/0016-refinement-ladder-and-layered-qa.md)
- Model never asked about a file that failed a free check; every layer must say what it could not check. — same

**Implementation: `qa.run` (video with edit)**
- Writes `qa.json`; `fail` blocks approval, `warn` shows on review. — [src/kalainova/qa.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/qa.py)
- Technical / delivery checks include: frame size/fps vs profile, duration vs edit plan, loudness ±1 LUFS, true peak, black frames, caption coverage ≥95%, rights, synthetic disclosure, stock credits, short-form duration warn, dead air warn, hook timing/length warn, claim URL warn + research claim checks. — [src/kalainova/qa.py `run`](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/qa.py)
- Then qachecks: motion promise, placeholders, plan review, sound layers (mezzanine), cut click/flash, safe zone, cuts-on-beat, kit checks; builds contact + motion + cut sheets; vision rubric judge; studio bar as checks. — [src/kalainova/qa.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/qa.py); [src/kalainova/qachecks.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/qachecks.py)
- Alternate entrypoints: `run_song`, `run_document`, `run_file` (outside-tool intake: no content review beyond warn). — [src/kalainova/qa.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/qa.py)

**Craft bar (`kalainova bar`)**
- Three human-facing layers: Delivery (tool), Craft (tool then human), Taste (human). Perfect score = no measured defect, not “good.” — [docs/studio-bar.md](file:///Users/km2411/Desktop/work/kalainova/docs/studio-bar.md)
- Reports **conformance** (readings with `blocks=True`) vs **craft** (non-blocking) separately. — [src/kalainova/bar/readings.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/bar/readings.py); [docs/studio-bar.md](file:///Users/km2411/Desktop/work/kalainova/docs/studio-bar.md)
- Currently `blocks=True` in bar code for: delivery color tags, delivery pixel format, audio clipping (and master readings; song clipping). Most picture/sound craft metrics warn only. — [src/kalainova/bar/__init__.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/bar/__init__.py); [src/kalainova/bar/master.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/bar/master.py)
- Picture readings: banding, CAMBI (if libvmaf), stutter, detail, repetition, corner mark, dynamic range, clipping; motion: generated shot motion (camera-compensated), moving_share, cuts_per_min; sound: voice/music balance, hard cuts, digital silence, ending drop, groove steadiness, pitch snapping, etc. — [docs/studio-bar.md](file:///Users/km2411/Desktop/work/kalainova/docs/studio-bar.md); [config/studio.yaml `bar:`](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml); [src/kalainova/bar/](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/bar/)
- Songs: loudness/true peak can block on finished file; tempo/words/shape/length warn (ADR 0014). — [docs/studio-bar.md](file:///Users/km2411/Desktop/work/kalainova/docs/studio-bar.md)
- Explicit non-coverage: HDR, surround, packaged masters, story quality, “whether generated shot looks real.” — [docs/studio-bar.md](file:///Users/km2411/Desktop/work/kalainova/docs/studio-bar.md); [ARCHITECTURE.md Known gaps](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)

**Vision judges (prompts + router)**
1. **Still judge** (`prompts/qa_still.md`): anatomy, garbled text, cue match; region citations; status pass|fail|unsure. Used in animatic and before paid motion (`still_judge_refusal`). Advises via findings; on paid run can refuse sending flagged still to motion (returns refusal string / promise break). Does **not** replace human animatic accept. — [prompts/qa_still.md](file:///Users/km2411/Desktop/work/kalainova/prompts/qa_still.md); [src/kalainova/preproduction.py `still_judge_refusal`](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/preproduction.py); [ARCHITECTURE.md §preproduction](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)
2. **Final rubric judge** (`prompts/qa_rubric.md`): contact sheet + motion strip; per-shot moved/geometry/continuity/warping/flicker/objects_change/action; verdict ship|fix|kill; policy_risk. Findings → `findings.json` for retakes. Shot problems become **warn** (`judge.shots`); kill/high policy checked in qa. Beats that already failed free checks are excluded. — [prompts/qa_rubric.md](file:///Users/km2411/Desktop/work/kalainova/prompts/qa_rubric.md); [src/kalainova/qachecks.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/qachecks.py); [src/kalainova/qa.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/qa.py)
3. **Kit consistency judge** (`prompts/qa_consistency.md`): kit refs + contact sheet → same_character, style_matches, resembles_real_person, script_breaks_kit. Clear false can **fail**; null warns. — [prompts/qa_consistency.md](file:///Users/km2411/Desktop/work/kalainova/prompts/qa_consistency.md); [src/kalainova/kitchecks.py `judge_checks`](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/kitchecks.py)
- Default judge model: cheaper Haiku via capability `judge`. — [config/studio.yaml](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)
- Findings without a cited region/time are dropped (`shot_problems`). — [src/kalainova/qachecks.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/qachecks.py); ADR 0016

**Kit identity (record + measured face)**
- Record checks (no model): script vs kit rules, pinned generators, locked voices, kit music hashes, references present on cast shots — can **fail**. — [src/kalainova/kitchecks.py `recorded_checks`](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/kitchecks.py)
- Measured face identity: optional external command (`identity.face_command`); OpenCV YuNet+SFace runner shipped; cosine `same_face_min` 0.363; **warns, does not block**; if unset → “not measured,” never a pass. — [config/studio.yaml `identity`](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml); [src/kalainova/bar/identity.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/bar/identity.py); [ARCHITECTURE.md §bar](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)
- Default studio.yaml has `face_command: []` (off). — [config/studio.yaml](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)
- Kit cannot prove a face is not a real person; human attests at freeze; vision judge is one more signal. — [ARCHITECTURE.md Known gaps](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)

**Human gate**
- Agents never write `approval.json`; `kalainova approve` is human; publish only approved QA-checked bytes (ADR 0007). — [AGENTS.md](file:///Users/km2411/Desktop/work/kalainova/AGENTS.md); [ARCHITECTURE.md](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)
- `verdicts.record`: accept|fix|reject with reviewer name; animatic verdict sets `animatic_reviewed` (stills hashes); preferences between takes. — [src/kalainova/verdicts.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/verdicts.py); [ARCHITECTURE.md §verdicts](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)
- `kalainova signals` / review-set: calibration of readings vs human verdicts (AUC separation); readings that don’t separate get deleted (ADR 0011). — [docs/studio-bar.md](file:///Users/km2411/Desktop/work/kalainova/docs/studio-bar.md); [src/kalainova/verdicts.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/verdicts.py)
- Skill `review-a-piece`: agent checklist — compare source vs final, edit_manifest, ffprobe, bar numbers, sheet/motion/cuts, continuity, Whisper, write findings, retake, ask operator for verdict; never approve. — [.agents/skills/review-a-piece/SKILL.md](file:///Users/km2411/Desktop/work/kalainova/.agents/skills/review-a-piece/SKILL.md)

**ADR 0017 autonomy (proposed)**
- Stream may declare `autonomy` per gate: track_pick, stills, animatic, final ∈ {human, by-exception, audit}; publish const human. Unsure escalates in by-exception. Promotion needs ≥0.8 AUC via signals. — [docs/decisions/0017-…md](file:///Users/km2411/Desktop/work/kalainova/docs/decisions/0017-autonomy-level-per-review-gate.md); [schemas/stream.schema.json](file:///Users/km2411/Desktop/work/kalainova/schemas/stream.schema.json)
- Explicit consequence: “Runtime behavior remains unchanged until autonomy gate handlers are implemented.” — [ADR 0017](file:///Users/km2411/Desktop/work/kalainova/docs/decisions/0017-autonomy-level-per-review-gate.md)
- Confirmed: **no** `autonomy` references under `src/kalainova/*.py` (schema + `scripts/check.py` only). — codebase grep 2026-11-14
- `unsure` status exists in judge shot checks (`judge.unsure`). — [src/kalainova/qachecks.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/qachecks.py)

### Inferences
- Operational QA today is **human-centric with strong free/measured gates** and **advisory multimodal LLM checks**, not an autonomous ship pipeline.
- Identity has two channels: **hard record lock** (can fail) and **soft face embedding / vision resemblance** (warn or fail only on clear vision “no”).
- Layer view’s “QA partial / Human gate partial” matches: wiring exists; calibration and autonomy handover do not fully.

### Gaps
- Full enumeration of every `fail` vs `warn` id across song/document paths not exhaustively tabulated here (video `run` + kitchecks + bar.as_checks covered).
- Whether `identity.face_match` is always included in `bar.measure_job` for stream jobs vs only CLI/`panels_check` — identity_readings exists; default face_command empty means typically not measured in practice.

---

## What algorithms/tools (ffmpeg, OpenCV YuNet/SFace, HyperFrames, etc.)?

### Takeaway
Owned media math is ffmpeg/ffprobe-centric plus NumPy/Pillow signal processing for the bar; face ID is an optional OpenCV ONNX side-command; graphics are HyperFrames; editing seams can call auto-editor / beat_this / OTIO; speech timing prefers Whisper (fal or whisper.cpp).

### Cited Findings

**ffmpeg / ffprobe / media**
- `media` module: ffmpeg and ffprobe helpers; argument lists never shell strings. Used for render, loudness (BS.1770), blackdetect, silencedetect, decode, scene changes, etc. — [ARCHITECTURE.md §media](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md); [src/kalainova/media.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/media.py)
- Render pipeline compiles plans then executes ffmpeg steps with cache. — [ARCHITECTURE.md §render](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)
- Host checks for ffmpeg/ffprobe binaries. — [ARCHITECTURE.md §host](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)
- CAMBI banding via ffmpeg libvmaf when present (`mediascan.cambi`); else banding_score only. — [src/kalainova/bar/__init__.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/bar/__init__.py); [docs/studio-bar.md](file:///Users/km2411/Desktop/work/kalainova/docs/studio-bar.md)

**Bar algorithms (deterministic)**
- Picture: banding histograms, detail/edge ratios, stutter from frame-diff variance, repetition of shot thumbs, corner-mark persistence, dynamic range, clipping. — [src/kalainova/bar/picture.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/bar/picture.py)
- Shot motion: block phase-match for pan/zoom, undo camera, measure changed-pixel share (`bar/motion.py`); used in take assessment and `source.shot_motion`. — [src/kalainova/bar/motion.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/bar/motion.py); [src/kalainova/takes.py `assess_clip`](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/takes.py)
- Sound: hard-cut rate, voice-to-music dB, digital silence, ending drop, groove steadiness (onset flux / pulse), pitch snapping, stereo correlation. — [src/kalainova/bar/sound.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/bar/sound.py)
- Song: tempo / drift, words_found vs Whisper transcript (lyric error rate abandoned after verdict calibration). — [src/kalainova/bar/song.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/bar/song.py); [docs/studio-bar.md](file:///Users/km2411/Desktop/work/kalainova/docs/studio-bar.md)
- Master: ProRes 422 HQ, 10-bit 4:2:2, BT.709 atoms, black head/tail, duplicate frames, LPCM 48 kHz, LUFS/true peak. — [docs/studio-bar.md](file:///Users/km2411/Desktop/work/kalainova/docs/studio-bar.md); [src/kalainova/bar/master.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/bar/master.py)

**OpenCV YuNet / SFace**
- `providers/runners/face_run.py`: YuNet detector + SFace recognizer ONNX from OpenCV zoo; 128-D unit embeddings; JSON out. Engine compares cosines in `bar/identity.py` via `opentools.run`. — [face_run.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/providers/runners/face_run.py); [bar/identity.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/bar/identity.py)
- Engine ships **no** face model weights; operator supplies models dir + venv. — same; [config/studio.yaml](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)

**HyperFrames**
- Local Node render of composition folders for charts, kinetic type, cards; alpha WebM overlay path for kinetic captions. — [hyperframes.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/providers/hyperframes.py); [ARCHITECTURE.md §render](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)

**Timeline / review visualization**
- `timeline`: shot sheet (first/last), motion strip, cut strip, filmstrip+waveform, cut_report for click/flash. — [ARCHITECTURE.md §timeline](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md); used by qa and review-a-piece skill

**Transcription / speech tools**
- fal Whisper; optional `whispercpp` (`whisper-cli` + `KALAINOVA_WHISPER_CPP_MODEL`) for real word times; mac Whisper MLX; local estimates timings. — [ARCHITECTURE.md §providers](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md); [config/studio.yaml](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)
- Editor: in-house speech cuts or `auto-editor` command; beats in-house or `beat_this`. — [ARCHITECTURE.md §editor](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)

**NLE / OTIO**
- FCPXML, EDL, OTIO export; optional `otioconvert` adapter. — [ARCHITECTURE.md §nle / §nle_otio](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)

**Demucs / stem separation**
- Capability `separate` via fal Demucs (VERIFY) or mac audio-separator; opt-in. — [config/studio.yaml](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)

**Fonts**
- Vendored open fonts for deterministic type metrics (captions, books). — [AGENTS.md](file:///Users/km2411/Desktop/work/kalainova/AGENTS.md); [ARCHITECTURE.md §captions](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md)

### Inferences
- “Algorithms” for QA craft are mostly **classical DSP/vision heuristics**, not trained defect classifiers — except the LLM vision judges and optional SFace embeddings.
- Tooling philosophy: **stdlib/engine owns contracts; heavy ML stays rented or in isolated runners** (ADR 0012 open-tools pattern).

### Gaps
- No deep dive into exact ffmpeg filter graphs in `render/picture.py` / `render/sound.py` (grade chain, loudness) beyond architecture claims.
- OpenCV face threshold (0.363) noted as overlapping same/different on generated look-alikes in config comments — calibration incomplete.

---

## What loops exist (retake, animatic gate, refinement ladder)? What is explicitly NOT done / partial / planned?

### Takeaway
Implemented loops: animatic gate before paid video, fixed/few takes with free-only auto-retry, capped retakes from findings, song section polish, still-judge refusal before motion. The full ADR 0016 ladder is partially built; autonomy promotion (0017) and several ladder slices remain planned; taste, HDR, surround, and predicting human verdict are explicitly out of scope for automation today.

### Cited Findings

**Animatic gate (implemented)**
- `kalainova animatic`: voice + one still per shot, no video; render stamped ANIMATIC; `animatic.json` with quotes. — [ARCHITECTURE.md §preproduction](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md); [src/kalainova/preproduction.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/preproduction.py)
- Gate active when brief.animatic_gate true, or by default for cost-capped jobs with paid video and moving beats. — [preproduction.gate_active](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/preproduction.py)
- `require_review` refuses full assets until `animatic_reviewed.verdict == accept` and sha matches; accepted still hashes enforced. — same
- Still judge during animatic advises only; on paid run accepted stills skip re-judge; flagged stills not sent for motion. — [ARCHITECTURE.md §preproduction](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md); [assets.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/assets.py)
- Publish refuses animatic by name/hash. — [preproduction.refuse_animatic](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/preproduction.py)

**Takes / retakes (implemented)**
- Config: `takes.always: 1`, `most: 2`, `retakes_per_shot: 2`, `retakes_per_job: 6`. — [config/studio.yaml](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)
- `make_until_good`: paid models make exactly `always` takes; free providers may continue until ok or `most`; **no paid auto-loop on failed reading**. — [takes.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/takes.py); ADR 0016 / ADR 0013
- Assessment = shot_motion ≥ `shot_motion_min` (0.05). — [takes.assess_clip](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/takes.py); [config/studio.yaml](file:///Users/km2411/Desktop/work/kalainova/config/studio.yaml)
- `kalainova retake`: shared `shotmake.retake`; note or findings.json; refused past limits. — [shotmake.retake](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/shotmake.py); review-a-piece skill
- Human-chosen take stands even if motion reading fails (`motion_break`). — [shotmake.motion_break](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/shotmake.py)

**Song polish / repair (implemented)**
- `song_repair`: repaint one section into a new take beside lock (ACE-Step repaint on Mac when available); refuses if no provider can. — [ARCHITECTURE.md §song_repair](file:///Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md); [src/kalainova/song_repair.py](file:///Users/km2411/Desktop/work/kalainova/src/kalainova/song_repair.py)

**Refinement ladder (ADR 0016) — decision vs build slices**
- Decision accepted: stages by cost; lock; paid once on locked inputs; free may loop; fix order repair → polish unit → regenerate unit; separate jobs for separable pieces. — [ADR 0016](file:///Users/km2411/Desktop/work/kalainova/docs/decisions/0016-refinement-ladder-and-layered-qa.md)
- Build slices listed (PRs/issues): paid only planned takes; song clean end + bar in QA; verdicts with reason/preference; trace; measured identity; polish; autonomy; paid refuses without accepted draft (animatic); model check on stills with cheaper model; video-to-song stream. — same ADR “Building it is slices”
- Animatic refuse-without-accept, still judge, takes limits, identity module, song_repair, trace, verdicts: present in code (this map). Autonomy handlers: **not** in runtime.

**ADR 0017**
- Status **proposed**; schema exists; runtime unchanged. — [ADR 0017](file:///Users/km2411/Desktop/work/kalainova/docs/decisions/0017-autonomy-level-per-review-gate.md)

**Explicitly NOT done / partial / planned (from repo)**

| Item | Status | Source |
|---|---|---|
| Local video draft generation | Not done (animatic instead) | ADR 0016 |
| Model check blocking ship by default | Not done (advises; warn) | ADR 0016; qachecks.judged_shots |
| Autonomy by-exception/audit handlers | Planned / not in engine py | ADR 0017; grep |
| Predict operator taste/verdict | Explicitly not; QA ≠ acceptance | ARCHITECTURE Known gaps; studio-bar |
| Face “not a real person” proof | Not possible in engine; human attest | ARCHITECTURE Known gaps |
| HDR / 5.1–7.1 | Not done (SDR stereo only) | studio-bar; ARCHITECTURE |
| Packaged platform masters | Not done (single file + captions) | studio-bar |
| Content review of outside-tool files | Human only | qa.run_file; ARCHITECTURE |
| Real-model proof of post-ADR-0012 features | Wiring only / faked models | ARCHITECTURE Known gaps |
| Container runner for outside tools | Contract exists, unused in production | ARCHITECTURE Known gaps |
| Multi-machine ledger | Single machine today | ARCHITECTURE / ADR 0010 |
| Publish comics/books/audio-only | Can approve, not post | ARCHITECTURE Known gaps |
| Explainers producer | Planned in layer view | ARCHITECTURE Layer view |
| Book ligatures | Known gap | ARCHITECTURE |
| Character shot max / safe zone | Warn estimates until live check | studio-bar; studio.yaml comments |
| Lyric WER as song metric | Abandoned after verdict test | studio-bar |
| Cloud Postgres queue / review API | Planned ADR 0010 phases | ARCHITECTURE Cloud path |

**Human + agent review loop (operational, not closed-loop AI)**
- review-a-piece → findings.json → retake → re-render earliest changed stage → human `verdict` / `approve`. — [SKILL.md](file:///Users/km2411/Desktop/work/kalainova/.agents/skills/review-a-piece/SKILL.md)

### Inferences
- The important product pattern already shipped is **spend control via animatic + take caps**, not **closed-loop auto-fix until bar passes**.
- Gap analysis should not credit Kalainova with autonomous final QA or calibrated identity blocking — those are designed but mostly advisory/off-by-default.
- Fair comparison point vs other stacks: Kalainova is unusually strong on **contracts, kit locks, measured delivery bar, and human attestation**; generation quality ceiling is **whatever rented models return**.

### Gaps
- Issue/PR completion status for ADR 0016 slices 1–10 was not verified against GitHub — only the ADR’s listed intent and local code presence.
- End-to-end “first real paid short through full ladder” acceptance status: ARCHITECTURE says Built lines in studio-goal are not yet Run/Accepted on real models.
- Editor/footage path loops (patch, choose, clips) mapped only at architecture level, not as deeply as generated-shot path.

---

## Quick reference: primary modules

| Concern | Path |
|---|---|
| Architecture | `/Users/km2411/Desktop/work/kalainova/ARCHITECTURE.md` |
| Studio bar doc | `/Users/km2411/Desktop/work/kalainova/docs/studio-bar.md` |
| Ladder + QA ADR | `/Users/km2411/Desktop/work/kalainova/docs/decisions/0016-refinement-ladder-and-layered-qa.md` |
| Autonomy ADR | `/Users/km2411/Desktop/work/kalainova/docs/decisions/0017-autonomy-level-per-review-gate.md` |
| Models/limits | `/Users/km2411/Desktop/work/kalainova/config/studio.yaml` |
| QA orchestration | `/Users/km2411/Desktop/work/kalainova/src/kalainova/qa.py` |
| Individual checks | `/Users/km2411/Desktop/work/kalainova/src/kalainova/qachecks.py` |
| Kit QA | `/Users/km2411/Desktop/work/kalainova/src/kalainova/kitchecks.py` |
| Bar | `/Users/km2411/Desktop/work/kalainova/src/kalainova/bar/` |
| Face ID | `/Users/km2411/Desktop/work/kalainova/src/kalainova/bar/identity.py`, `providers/runners/face_run.py` |
| Providers | `/Users/km2411/Desktop/work/kalainova/src/kalainova/providers/` |
| Shot generation | `/Users/km2411/Desktop/work/kalainova/src/kalainova/shotmake.py`, `shots.py`, `takes.py`, `assets.py` |
| Animatic | `/Users/km2411/Desktop/work/kalainova/src/kalainova/preproduction.py` |
| Render | `/Users/km2411/Desktop/work/kalainova/src/kalainova/render/` |
| Verdicts | `/Users/km2411/Desktop/work/kalainova/src/kalainova/verdicts.py` |
| Judge prompts | `/Users/km2411/Desktop/work/kalainova/prompts/qa_*.md` |
| Human review skill | `/Users/km2411/Desktop/work/kalainova/.agents/skills/review-a-piece/SKILL.md` |
