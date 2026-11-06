# How to run channels and characters

Name a channel and a brief. The engine holds everything else fixed.

## 1. Set up a private home

This repo is public, so real work lives elsewhere. Make a private repository and point the engine at it.

```bash
export KALAINOVA_HOME=~/work/kalainova-studio    # jobs, kits, streams, store, out
export KALAINOVA_STORE_URI=s3://<bucket>/kits    # optional: durable, private copy of reference files
export KALAINOVA_KMS_KEY=<key-id>                # optional: encrypt each object with SSE-KMS
uv sync --extra cloud                            # only if you set KALAINOVA_STORE_URI
```

Add `store/` and `out/` to the private repository's `.gitignore`. Without `KALAINOVA_STORE_URI`, the only copy of a face is on this disk, so set it before the first public piece.

## 2. Make a kit

A character is a kit. So is a channel's look, or a client's brand. Fill in only what applies.

```bash
uv run kalainova kit new <kit>
uv run kalainova kit add <kit> identity front.png --label front
uv run kalainova kit add <kit> identity profile.png --label profile
uv run kalainova kit add <kit> looks.<name> outfit.png
uv run kalainova kit add <kit> music.theme theme.wav
uv run kalainova kit set <kit> fields.json
uv run kalainova kit freeze <kit> --by <your name>
```

`fields.json` holds the text. For a character:

```json
{
  "origin": {"invented": true, "real_person": false, "attested_by": "<your name>", "made_with": "<model>"},
  "person": {"fictional": true, "adult": true, "age": 30},
  "identity": {"description": "<what the face and build look like>"},
  "voice": {"provider": "elevenlabs", "voice_id": "<id>", "model": "<model>"},
  "persona": {
    "traits": ["<trait>"],
    "speech": "<how they talk>",
    "never_say": ["<phrase>"],
    "backstory": {"fiction": true, "text": "<their invented past>"}
  }
}
```

To cast a face: generate candidates, pick one, then make a front, a three-quarter, a profile, a full-body shot, and a few expressions from that pick. Freezing is your attestation that the face and voice were invented and the character is an adult. Check that the face does not resemble a real person, because no software can prove that.

To change anything later, run `kit bump`, edit, and freeze again. Existing jobs keep the version they locked.

## 3. Make a stream

```bash
uv run kalainova stream new <stream> --identity <account label> --cost-cap 10 \
  --kit lead=<kit>@1 --kit house=<style kit>@1 \
  --image fal:google/nano-banana-2.1/edit \
  --video fal:alibaba/wan-3.0-prime/reference-to-video \
  --account youtube=<handle> --max-per-day 1 --skip-funded
uv run kalainova stream show <stream>    # what is fixed, and how
```

Posting credentials stay in the environment. Each stream reads its own YouTube refresh token from `YOUTUBE_REFRESH_TOKEN_<IDENTITY>`, with the identity in capitals and other characters as `_`. Upload-Post uses the handle in `--account` as its profile.

## 4. Ask for a piece

```bash
uv run kalainova request <stream> "<brief>"                # one character: no need to name them
uv run kalainova request <stream> "<brief>" --cast a,b     # several on the stream: name who appears
uv run kalainova make jobs/<id>
uv run kalainova approve jobs/<id> --reviewer <you> --platforms youtube
uv run kalainova publish jobs/<id> youtube --live
```

The job records exact kit versions in `kit.lock.json`. If a reference changes on disk, or a kit version is edited, the engine stops.

## 5. Keep the story straight

```bash
uv run kalainova stream canon <stream> "<what happened>" --by <your name>
```

Canon only grows, and later scripts must not contradict it. A fact that must follow a character to every stream belongs in a new kit version.

## 6. Plan ahead without rendering

```bash
uv run kalainova schedule <stream> 2026-12-01 "<brief>"
uv run kalainova request <stream> --slot 2026-12-01
```

A stream holds up to thirty open slots, within its daily limit. A slot renders only when requested, and each job passes the human gate.

## What the engine stops

| Situation | What happens |
|---|---|
| The pinned model takes no reference images | The request stops before spending |
| A beat names a look, place, or prop the kit lacks | The script is refused |
| A line uses a phrase from `never_say` | The script is refused |
| A shot was made without its references, or by another model | QA fails |
| A voice differs from the kit, or none is fixed | The request or QA fails |
| The vision judge says the face or style does not match | QA fails |
| The stream has no account on a platform | Approval is refused |
| The daily limit is reached | The live post is refused |
