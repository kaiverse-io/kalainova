# How to direct a shot

Generated video is a sample, so a piece is made shot by shot. Write what each shot does, look at what came back, and fix only the shots that need it.

## Write the plan

In `script_packet.json`, describe what must stay the same once, and name it from the beats:

```json
{
  "continuity": {
    "people": {"<name>": "age, build, hair, and exactly what they wear"},
    "places": {"<name>": "what the place is and how it is laid out"}
  },
  "beats": [
    {
      "id": "b1",
      "role": "hook",
      "text": "The spoken line.",
      "visual_kind": "video",
      "cast": ["<name>"],
      "location": "<name>",
      "ambience": "what this place sounds like",
      "shot": {
        "size": "wide",
        "first_frame": "The still picture at the start. Nothing is happening yet.",
        "last_frame": "The still picture at the end.",
        "camera": "How the camera moves, and what it reveals when it stops.",
        "action": "What the subject does, start to finish.",
        "environment": "What else moves: water, smoke, cloud, crowd."
      }
    }
  ]
}
```

- `first_frame` becomes the still. `camera`, `action`, and `environment` become the clip's prompt, in that order, because a clip that starts from a still already has the picture.
- Name what else moves. Water and cloud freeze unless asked to move.
- Decide the layout first. A person has to stand on the floor they walk across.
- Set `continues: true` on a shot that picks up where the last one ended. It starts from that clip's last frame.
- Set `on_camera: true` and a `speaker` when someone is seen saying the line. The clip is lip-synced to it, with the line padded to the clip's length. The clip as it was before the sync is kept beside it as `.presync.mp4`.
- `last_frame` is sent as a picture to a model that takes an end frame (`end_image_param` in `config/studio.yaml`). Other models are not told it, and the shot's record says it was not used.
- Set `graphics` to a composition folder in the job for a chart or a diagram, which should be drawn and not generated.

Check the plan before spending anything:

```bash
uv run kalainova shotplan <job>
```

## Make it, and look

```bash
uv run kalainova make <job>
uv run kalainova sheet <job>     # first and last frame of every shot
uv run kalainova takes <job>     # every take, and how each read
uv run kalainova cutcheck <job>  # a click or a flash at any cut
```

A row of the sheet with two nearly identical frames did not move. A shot whose reading misses gets another attempt automatically, up to `brief.max_takes`, only when the model is free to call. A paid model makes exactly `brief.takes` and stops, and another take is yours to ask for with `kalainova retake`. Set `brief.takes` to plan more up front.

## Fix one shot

```bash
uv run kalainova retake <job> <shot> "The water must keep moving."
uv run kalainova take <job> <shot> <n>    # or choose an earlier take
uv run kalainova make <job> --from edit
```

Only that shot is regenerated, and only what it touches is re-encoded. The new take is used if it reads well, because you asked for it after seeing something a reading cannot. A take you chose with `take` stands until you choose again.

A shot that asked to move and cannot stops the job. To accept a still, set `brief.allow_stills`, and it stays on the record.

## Say what you think

```bash
uv run kalainova verdict <job> reject --reviewer <you> --shot <shot> --note "The door opens the wrong way."
uv run kalainova signals    # which readings predict what you said
```

A verdict is not an approval. It is how the bar learns which of its readings mean anything.
