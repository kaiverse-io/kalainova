"""Mureka's own API (platform.mureka.ai): a song from lyrics, and one span of a take sung again.

fal answered 410 for its Mureka song routes on 2026-11-20, billing nothing, and Mureka V9.5 is
the best-ranked vocal model reachable by API. Losing a host must not lose the model (ADR 0023),
so the same request goes to the vendor itself. It is the request fal's row sends (fal_song, read
from this provider's own rows in audio_models: notes on the lyric tags, gender, pronunciation in
the style, the length), plus:

- **One song a call.** `n` defaults to 2 and each song is charged, so `n: 1` always.
- **The lossless file.** `wav_url`, else `flac_url`, else the MP3 `url`; all last 30 days.
- **The vendor's song id**, kept on the take with the day it lapses: an edit by id takes a song
  made in the last month (`song_id_until`). After that, the take goes up as a file.
- **What the API refuses, before sending** (`problems`): its field limits, its models, and which
  controls combine (prompt with a voice, or a reference with a voice; never a prompt with a
  reference; a melody alone). Read from the spec embedded in its docs on 2026-11-20, held here.

The API answers a task, and the transport polls `song/query/{id}` until it is done. A task the
vendor marks failed is not billed by its account, so the router releases what it held; a wait
that runs out may have been billed, and is charged as such.
"""

from __future__ import annotations

import datetime as dt
import os
import time
from pathlib import Path
from typing import Any

import requests

from .. import media
from ..config import model_for
from . import fal_song
from .base import Provider, register
from .contract import Context, Result, SongRequest, UnavailableError
from .transport import TIMEOUT, Reply, Transport, raise_for

API = "https://api.mureka.ai/v1"
DONE, FAILED = "succeeded", ("failed", "timeouted", "cancelled")
POLL_SEC = 3.0
SONG_ID_DAYS = 30  # "Only supports songs generated within the last month"
FILE_AT = ("choices.0.wav_url", "choices.0.flac_url", "choices.0.url")

# The published spec (platform.mureka.ai/docs, SongGenerateReq and SongRegionEditReq, 2026-11-20)
MODELS = ("auto", "mureka-7.6", "mureka-o2", "mureka-8", "mureka-9", "mureka-9.5")
GENERATE_FIELDS = {"lyrics", "model", "n", "prompt", "gender", "duration", "reference_id",
                   "vocal_id", "melody_id", "stream"}  # fmt: skip
EDIT_FIELDS = {"song_id", "upload_audio_id", "lyrics", "edit_start", "edit_end"}
CONTROLS = ("prompt", "reference_id", "vocal_id", "melody_id")
COMBINE = ({"prompt", "vocal_id"}, {"reference_id", "vocal_id"})
LYRICS_MOST, EDIT_LYRICS_MOST, PROMPT_MOST = 5000, 3000, 1024
DURATION = (120, 300)  # mureka-9.5 only
EDIT_LEAST_MS = 3000


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {os.environ['MUREKA_API_KEY']}"}


def _generate_problems(payload: dict[str, Any]) -> list[str]:
    found = [f"song/generate takes no field {k!r}" for k in sorted(set(payload) - GENERATE_FIELDS)]
    model = payload.get("model")
    if not payload.get("lyrics"):
        found.append("song/generate needs lyrics")
    elif len(str(payload["lyrics"])) > LYRICS_MOST:
        found.append(f"lyrics run past {LYRICS_MOST} characters")
    if model not in MODELS:
        found.append(f"model {model!r} is not one of {', '.join(MODELS)}")
    if not 1 <= int(payload.get("n", 2)) <= 3:
        found.append("n is 1 to 3")
    if len(str(payload.get("prompt") or "")) > PROMPT_MOST:
        found.append(f"the prompt runs past {PROMPT_MOST} characters")
    if payload.get("gender") not in (None, "female", "male"):
        found.append("gender is female or male")
    return found + _control_problems(str(model), payload)


def _control_problems(model: str, payload: dict[str, Any]) -> list[str]:
    """The length, which only V9.5 takes, and which of the four controls go together."""
    found = []
    if "duration" in payload:
        if model != "mureka-9.5":
            found.append("only mureka-9.5 takes a duration")
        elif not DURATION[0] <= int(payload["duration"]) <= DURATION[1]:
            found.append(f"duration is {DURATION[0]} to {DURATION[1]} s")
    used = {c for c in CONTROLS if payload.get(c)}
    if len(used) > 1 and used not in COMBINE:
        found.append(f"{' and '.join(sorted(used))} cannot be combined")
    if model == "mureka-o2" and used & {"vocal_id", "melody_id"}:
        found.append("mureka-o2 takes no vocal_id or melody_id")
    return found


def _edit_problems(payload: dict[str, Any]) -> list[str]:
    found = [f"song/region-edit takes no field {k!r}" for k in sorted(set(payload) - EDIT_FIELDS)]
    if bool(payload.get("song_id")) == bool(payload.get("upload_audio_id")):
        found.append("a region edit names the song by song_id or by upload_audio_id, one of them")
    if len(str(payload.get("lyrics") or "")) > EDIT_LYRICS_MOST:
        found.append(f"an edit's lyrics run past {EDIT_LYRICS_MOST} characters")
    if int(payload.get("edit_end", 0)) - int(payload.get("edit_start", 0)) < EDIT_LEAST_MS:
        found.append("the edited region is at least 3 s")
    return found


def problems(model: str, payload: dict[str, Any]) -> list[str]:
    """What Mureka's API would refuse in this payload, from its published spec."""
    if "edit_start" in payload or "edit_end" in payload:
        return _edit_problems(payload)
    return _generate_problems(payload)


class MurekaApi(Transport):
    """Mureka's API: a POST answered with a task, polled at song/query/{id} until done."""

    platform = "mureka"

    def _send(
        self,
        endpoint: str,
        payload: dict[str, Any],
        ctx: Context,
        *,
        wait: float,
        params: dict[str, str],
    ) -> Reply:
        r = requests.post(f"{API}/{endpoint}", headers={**_headers(), "content-type":
                          "application/json"}, json=payload, timeout=TIMEOUT)  # fmt: skip
        raise_for(r, self.platform)
        task = r.json()
        ctx.receipt.request_id = str(task.get("id") or "") or None
        deadline = time.time() + wait
        while True:
            status = str(task.get("status") or "")
            if status == DONE:
                return Reply(data=task)
            if status in FAILED:
                said = task.get("failed_reason") or "no reason given"
                raise UnavailableError(f"mureka {endpoint} {status}: {said}")
            if time.time() >= deadline:
                raise TimeoutError(f"mureka {endpoint} timed out")
            time.sleep(POLL_SEC)
            q = requests.get(f"{API}/song/query/{task['id']}", headers=_headers(), timeout=TIMEOUT)
            raise_for(q, self.platform)  # a refused key fails now, not after the wait
            task = q.json()

    def _upload(self, path: Path) -> str:
        """A take up for an edit (purpose `audio`: mp3 or m4a, at most 10 MB), as its file id."""
        with open(path, "rb") as fh:
            r = requests.post(f"{API}/files/upload", headers=_headers(), data={"purpose": "audio"},
                              files={"file": (path.name, fh)}, timeout=TIMEOUT)  # fmt: skip
        raise_for(r, self.platform)
        found = r.json().get("id")
        if not found:
            raise UnavailableError("mureka files/upload answered with no file id")
        return str(found)

    def problems(self, model: str, payload: dict[str, Any]) -> list[str]:
        return problems(model, payload)


def _kept(reply: Reply) -> dict[str, Any]:
    """The vendor's id of the song, and the last day an edit can name it."""
    found = reply.get("choices.0.id")
    if not found:
        return {}
    until = dt.date.today() + dt.timedelta(days=SONG_ID_DAYS - 1)
    return {"song_id": str(found), "song_id_until": until.isoformat()}


@register
class Mureka(Provider):
    """Songs from lyrics on Mureka's own API, and a span of a take sung again (region edit)."""

    name = "mureka"
    capabilities = ("song",)
    env_key = "MUREKA_API_KEY"
    rehearses = True  # everything goes out through its transport
    transport: Transport = MurekaApi()

    def song(self, req: SongRequest, ctx: Context) -> Result:
        model = ctx.model or model_for("mureka", "song")
        if req.repaint is not None:  # one span sung again: the edit route of the take's model
            sent, how = fal_song.edit_payload(model, req, host="mureka")
            if how:
                upload = fal_song.upload_copy(req.repaint.source)
                sent[str(how["field"])] = self.transport.upload(upload)
            endpoint = "song/region-edit"
        else:
            body, _ = fal_song.payload(model, req, host="mureka")
            sent, endpoint = {"model": model, "n": 1, **body}, "song/generate"
        wrong = problems(model, sent)
        if wrong:  # refused here, so a rehearsal and a paid run stop at the same place
            raise ValueError(f"Mureka's API would refuse this request: {'; '.join(wrong)}")
        cost = fal_song.cost(model, req, host="mureka")
        reply = self.transport.send(endpoint, sent, ctx, model=model, wait=1200)
        raw = req.dst.with_suffix(".src")
        self.transport.fetch(reply, raw, at=FILE_AT, billed=cost)
        media.run(["-i", str(raw), "-ar", "48000", "-ac", "2", str(req.dst)])
        raw.unlink(missing_ok=True)
        return Result(path=req.dst, cost=cost, model=model, meta=_kept(reply))
