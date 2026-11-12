# Notice

This repository ships the engine: strategies, the job contract, and gates.

It does not ship third-party compositions, footage, audio, or a worked example of a subject. Operator media stays on disk and out of git (`scripts/check.py` enforces that).

If a later job vendors someone else's code, credit it in that job's own notice and do not relicense it from the repo root.

A job that states a fact carries the source next to the script. A job that cuts someone else's material carries `rights: funded-brief` or `rights: licensed` and the brief or license reference in the job folder.

## Fonts

`fonts/` holds Inter, Comic Neue, Bangers, Literata, and Noto Sans Devanagari, each under the SIL Open Font License 1.1. The licenses are in `licenses/fonts/`.

## What this engine learned from other projects

Ideas are credited in `docs/studio-goal.md` and in the module that uses them. No code from a project under AGPL or a non-commercial licence is in this repository: OpenMontage (AGPL-3.0) and AdCraft were read for ideas and nothing else.

- [auto-editor](https://github.com/WyattBlue/auto-editor) (public domain): the shapes of FCPXML and OpenTimelineIO exports.
- [video-use](https://github.com/browser-use/video-use) (MIT, browser-use): cutting speech at word boundaries, and a filmstrip with a waveform.
- [ViMax](https://github.com/HKUDS/ViMax) (MIT, HKUDS): writing a shot as a first frame, a last frame, and motion, and choosing among candidates.
- [ShortGPT](https://github.com/RayVentura/ShortGPT) (MIT): the flow of a translation.
- [genblaze](https://github.com/backblaze-labs/genblaze) (MIT, Backblaze): what a record of a generated asset should hold.

[whisper.cpp](https://github.com/ggml-org/whisper.cpp) (MIT) is run as the `whisper-cli` command when `whispercpp` is listed for `transcribe`. It is not vendored, and the model file has its own terms.

`src/kalainova/providers/runners/` calls [heartlib](https://github.com/HeartMuLa/heartlib) (Apache-2.0) and [ACE-Step](https://github.com/ace-step/ACE-Step-1.5) (MIT) in their own environments. Neither is vendored, and each model's weights have their own terms: see `licences:` in `config/studio.yaml`.
