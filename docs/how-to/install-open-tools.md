# Install the open tools the engine can call

Some capabilities have a second implementation beside the engine's own: an open tool, run as a command in its own environment (ADR 0012). The engine's own code is the default, and nothing here is needed to use it. A tool is chosen in the `adapters:` block of `config/studio.yaml`. When it is chosen and missing, the step stops and names the program. It never falls back by itself.

Each tool lives outside this repository, on Python 3.12. Put its `bin` folder on PATH, or give the full path in the adapter's `command:`.

## OpenTimelineIO (`adapters.timeline`)

```bash
uv venv --python 3.12 ~/tools/otio-env
uv pip install --python ~/tools/otio-env/bin/python \
  opentimelineio==0.18.1 otio-cmx3600-adapter otio-fcpx-xml-adapter
export PATH=~/tools/otio-env/bin:$PATH
otioconvert --version
```

OpenTimelineIO does not run on Python 3.14 yet. The adapter expects 0.18.x, and says so when it finds another.

Choose it:

```yaml
adapters:
  timeline: {use: otio, command: otioconvert}   # timeout_sec: 120, version: "0.18" are the defaults
```

Then:

```bash
kalainova export <job> --to fcpxml      # or edl; written by otioconvert into the job's work folder
kalainova timeline-import <job> edited.fcpxml
```

`timeline-import` writes `imports/edited.fcpxml.json` in the job's work folder: each clip in order, where it sits, and which part of its source it uses. It reads FCPXML, EDL, and OTIO. It changes no cut. Every run is recorded in the job's `tool_runs.json`.

A cut whose sources are not on disk has no lengths to carry, and the FCPXML writer in OpenTimelineIO fails on it. The step reports that as the tool's failure.

## auto-editor (`adapters.speech_cuts`)

```bash
uv venv --python 3.12 ~/tools/auto-editor-env
uv pip install --python ~/tools/auto-editor-env/bin/python auto-editor==29.3.1
export PATH=~/tools/auto-editor-env/bin:$PATH
auto-editor --version
```

The package downloads the program's binary from its GitHub releases the first time it runs, so run `--version` once with a network before a job needs it. The adapter expects 29.x.

```yaml
adapters:
  speech_cuts: {use: auto_editor, command: auto-editor}   # margin: 0.2s, edit: audio, timeout_sec: 900
```

A long-form footage edit (`kalainova edit`) then keeps the loud spans auto-editor reports for each take with sound, instead of cutting at gaps between words. It judges loudness, not words, so a cut can land inside a quiet word; raise `margin` to guard against that. Words from a transcript, when there is one, are still laid over the kept spans for captions. A take that is silent throughout stops the step rather than falling back. Results are kept in the job's `speech_cuts/` folder, by the file's bytes and options, and every run is recorded in `tool_runs.json`.
