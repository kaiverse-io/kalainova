# How to watch a rough cut before video is paid for

A studio locks a rough cut of stills and temporary sound before it pays for shots. This is that step. The first full review of a piece should not come after the money is spent.

## Make it

```bash
uv run kalainova animatic <job>
```

This runs the assets stage with every video call held back. It makes the voice and one still per shot, which are the same files a full run reuses, so nothing is paid for twice. It then draws a small video, `animatic.mp4` in the job's work folder: each still under a slow camera move, the words, the voice, and the finished track if the brief names one. The picture carries the word ANIMATIC.

It prints what the video still to be bought would cost, shot by shot and in total, against what is left under the cap. A shot whose model has no price says so. Where the total is over the cap it says that too, and you can fix it before a cent goes to video: raise `cost_cap`, or set `brief.max_video_beats` to move fewer shots.

The record is `animatic.json` in the job folder. It lists each shot's timing, its still, whether it is asked to move, and its estimate.

## Judge it

Watch it. Then say what you think:

```bash
uv run kalainova verdict <job> accept --animatic --reviewer <your name>
```

The verdict is `accept`, `fix`, or `reject`, and it names you. It is written to `verdicts.jsonl`, and the job's `animatic_reviewed` field records which cut you watched. A rough cut's verdict is not a sample for the studio bar, so it never enters the review set.

## Hold video until it is accepted

Set `"animatic_gate": true` in the job's `brief`. The assets stage then refuses, before any spend, until the animatic has an `accept` for the cut that exists now. Make the animatic again and the earlier accept no longer counts. A job without the flag behaves as before.

Set it for any job with a cap and moving shots.

## What it cannot do

- It is not the piece. `approve` and `publish` refuse it, by its name and by its hash.
- The camera moves are a plain rotation of push, pan, and pull. They show pace and framing, not the movement a model will make.
- A shot that carries on from the one before holds that shot's frame, because the frame it will really start on does not exist until the clip does.
- A drawn card is shown as its words on a dark card, and is made in the full run.
- Generated music and ambience are not made. Only the voice and a finished track are heard.
