# Pipeline

Same spine for a video, an audio piece, a still, a text pack, or a mix. The subject is an input. It is not a stage.

```
INTENT
  subject, audience, and outcome — supplied by the operator, stored only on the job
IDEATION
  hook variants. Three is enough to start. Kill on measure, do not stockpile.
SCRIPT
  script_packet.json — beats with roles hook | body | payoff | cta
  any factual claim has a source record
ASSET
  generate or ingest video, audio, stills, text
  asset_manifest.json points at local paths. The bytes are not committed.
REPRESENTATION
  proxy, duration, word timings when the asset has speech
  cut edges must not split a word
EDIT
  edit_manifest.json — cuts, captions, audio stems, loudness, aspect
  ten-minute human veto of the hook. No timeline craft before the first accepted unit.
RENDER
  rented tool now
  later, render_plan.json whose ops come from a fixed list (see schemas/render_plan.schema.json)
GATE
  human approves. Agents stop here.
PUBLISH
  outside the repo, on the distribution identity named by the job
MEASURE
  measure.json — views at 48h, accepted flag for funded work, keep or kill
```

## Who does what

| Actor | Does | Does not |
|---|---|---|
| Agent | Draft the packet, call a rented tool, write the job files, log the measure | Upload, submit a payout URL, invent a claim |
| Rented tool | Clip, voice, picture, schedule | Own the job folder |
| Human | Pick the strategy, approve, publish, submit | Edit a timeline by hand once the veto is enough |
| Cron (later) | Remind, batch after proof, fan out variants | Decide the hook |

Two orchestration modes, both legitimate once a unit has shipped: an agent for judgement, a deterministic runner for a batch. Do not stand up the runner before the proof.

## Rent, then own

| Need | Rent now | Own later |
|---|---|---|
| Long source → shorts | A clipper that scores hooks and reframes | Ingest, word timings, edit manifest, compile |
| Script → picture + voice | A generator with a human approve step | Script packet → voice → assemble |
| Original audio | A music or voice model | The prompt and the license note on the job |
| Post | The platform's own scheduler | A publish log, still human-triggered |
| Procedural picture | A template runtime, when one format has shipped | The template, data packet in, media out |

## Variants

One approved master can yield more than one output: a vertical cut, a square cut, a captioned cut, an audio-only stem, a text pack (title, description, teleprompter). Variants are new files on the **same** job, same strategy, same identity. They are not a reason to open a second strategy.

## Loudness and frame

When the output has audio, set a loudness target on the edit profile (default integrated −14 LUFS, true peak at or under −1 dBTP) and apply it once on the final mix. When the output has a picture destined for a short feed, default aspect is 9:16. Overrides live on the job, not in a global brand file.
