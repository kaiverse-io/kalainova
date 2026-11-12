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
