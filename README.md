# Kalainova

Content generation engine. Any subject the operator brings. The repo does not contain a vertical, a niche, or a sample topic.

It generates and assembles **video, audio, stills, and text**, alone or together. What the piece is *about* lives in the job the operator opens. It is not named here.

The plan is `docs/consolidation.md`. Three peer ways in: a funded cut, a master you hold, or a generated piece. Audio, text, procedural formats, and a downstream good are extensions, and they wait on a proof. The premortem is `docs/explanation/adversarial-2026-11-05.md`. Tool brands are the rented half. The job folder, the gates, and the measure log are the half this repo owns.

```bash
just ci        # check + contract eval + docs lint
```

`just` is optional; each target is one `python3 scripts/...` line in `justfile`. GitHub Actions is not on `main` yet: pushing a workflow needs a token with `workflow` scope. Opening a job: `docs/how-to/open-a-job.md`. `CLAUDE_HANDOVER.md` is the brief for the next agent.

## Studio engine

```bash
pip install -r requirements.txt     # plus ffmpeg on PATH
python3 -m kalainova providers      # which rented models have keys; local fallbacks run the line, but approve refuses their output
python3 -m kalainova make jobs/<id> # plan → assets → edit → compile → render → qa
python3 -m kalainova intake jobs/<id> <file> --record <record.json>  # a finished file from an outside tool
python3 -m kalainova approve jobs/<id> --reviewer <you> --platforms youtube
python3 -m kalainova publish jobs/<id> youtube --live
python3 -m kalainova measure jobs/<id>   # at 48 h
```

Plan, model stack, and money paths: `docs/studio.md`. Decision: `docs/decisions/0007-own-the-compile-path.md`.

Media files stay on disk. A human approves every piece.
