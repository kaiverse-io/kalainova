"""A paid song that follows a free draft (ADR 0027): the engine cuts and records the guide, and
fal's adapter uploads it and sends the vendor's id, sealed as the clip's bytes. No network."""

from __future__ import annotations

import json

import pytest
from fakes import Wire, context, make_job, needs_ffmpeg
from test_songs import _heard, _song

from kalainova import media, songs
from kalainova.blobstore import sha256_file
from kalainova.jobfs import ContractError, Job
from kalainova.providers import base, fal, payloads, rehearsal
from kalainova.providers.contract import Billable, Guide, SongRequest

pytestmark = needs_ffmpeg


def _job(tmp_path, song=None, **extra):
    job = make_job(tmp_path, media=["song"], **extra)
    job.write("song", song or _song())
    return job


@pytest.fixture
def falapi(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "k")
    wire = Wire(default={"audio": {"url": "u"}, "seed": 77}, files={"u": b"x"})
    monkeypatch.setattr(fal.Fal, "transport", wire)
    monkeypatch.setattr(media, "run", lambda *a, **k: None)
    return fal.Fal(), wire, tmp_path


# ---- the engine's side ----------------------------------------------------------------
def _draft_and_paid(tmp_path, studio, use, **paid_brief):
    studio.heard = _heard()
    draft = _job(tmp_path, job_id="d1", song=_song(job_id="d1"))
    songs.run(draft)
    brief = {
        "subject": "a test",
        "song_model": {"provider": "fake", "model": "m2"},
        "song_guide": {"job": "d1", "use": use},
        **paid_brief,
    }
    return draft, _job(tmp_path, job_id="p2", song=_song(job_id="p2"), brief=brief)


def _song_calls(studio):
    return [c for c in studio.calls if c["capability"] == "song"]


def test_a_song_follows_a_clip_of_a_finished_draft_cut_where_its_words_are_sung(tmp_path, studio):
    studio.guides = {"reference": 4.0}
    draft, paid = _draft_and_paid(tmp_path, studio, "reference")
    before = len(_song_calls(studio))
    songs.run(paid)
    asked = [c["kw"].get("guide") for c in _song_calls(studio)[before:]]
    assert asked and all(g and g["use"] == "reference" for g in asked)
    clip = paid.work / "guide.reference.m4a"
    assert media.duration(clip) == pytest.approx(4.0, abs=0.1)
    found = paid.read("asset_manifest")["assets"][0]["provenance"]["guide"]
    assert found["job"] == "d1" and found["use"] == "reference"
    assert found["source_sha256"] == sha256_file(draft.artifact())
    assert found["sha256"] == sha256_file(clip)
    assert found["end_sec"] - found["start_sec"] == pytest.approx(4.0)


def test_a_remix_takes_the_whole_draft(tmp_path, studio):
    studio.guides = {"remix": 0}
    draft, paid = _draft_and_paid(tmp_path, studio, "remix")
    songs.run(paid)
    clip = paid.work / "guide.remix.m4a"
    assert media.duration(clip) == pytest.approx(media.duration(draft.artifact()), abs=0.1)


@pytest.mark.parametrize(
    ("guides", "change", "refusal"),
    [
        ({}, {}, "takes no reference track"),
        ({"reference": 4.0}, {"song_model": None}, "names its model"),
        ({"reference": 4.0}, {"song_guide": {"job": "d1", "use": "cover"}}, "is not one of"),
        ({"reference": 4.0}, {"song_guide": {"job": "p2", "use": "reference"}}, "cannot follow"),
    ],
)
def test_a_guide_a_model_cannot_follow_is_refused_before_any_take(
    tmp_path, studio, guides, change, refusal
):
    studio.guides = guides
    _, paid = _draft_and_paid(tmp_path, studio, "reference")
    data = json.loads((paid.folder / "job.json").read_text())
    data["brief"].update(change)
    data["brief"] = {k: v for k, v in data["brief"].items() if v is not None}
    (paid.folder / "job.json").write_text(json.dumps(data))
    before = len(_song_calls(studio))
    with pytest.raises(ContractError, match=refusal):
        songs.run(Job(paid.folder))
    assert len(_song_calls(studio)) == before


def test_a_guide_must_be_finished_and_the_studios_to_use(tmp_path, studio):
    studio.guides = {"reference": 4.0}
    brief = {
        "subject": "a test",
        "song_model": {"provider": "fake", "model": "m2"},
        "song_guide": {"job": "d1", "use": "reference"},
    }
    _job(tmp_path, job_id="d1", song=_song(job_id="d1"))
    paid = _job(tmp_path, job_id="p2", song=_song(job_id="p2"), brief=brief)
    with pytest.raises(ContractError, match="no finished song"):
        songs.run(paid)
    _job(tmp_path, job_id="d2", song=_song(job_id="d2"), rights="funded-brief")
    brief["song_guide"] = {"job": "d2", "use": "reference"}
    other = _job(tmp_path, job_id="p3", song=_song(job_id="p3"), brief=brief)
    with pytest.raises(ContractError, match="a guide must be owned or licensed"):
        songs.run(other)


# ---- fal's side -------------------------------------------------------------------------
def _guide(tmp, use="reference"):
    clip = tmp / f"guide.{use}.m4a"
    clip.write_bytes(b"a clip of the draft")
    return Guide(source=clip, use=use)


def test_a_fal_song_follows_a_guide_by_the_id_its_upload_returns(falapi):
    provider, wire, tmp = falapi
    wire.replies.append({"id": "ref-1"})
    words = SongRequest(
        lyrics="[verse]\nWords", dst=tmp / "s.wav", style="house", duration=180, guide=_guide(tmp)
    )
    res = provider.song(words, context(model="mureka/v9.5/generate/song"))
    upload, song = wire.sent[-2:]
    assert upload["endpoint"] == "mureka/api/files/upload"
    assert upload["payload"] == {"file_url": "up:guide.reference.m4a", "purpose": "reference"}
    assert song["payload"] == {"lyrics": "[verse]\nWords", "duration": 180, "reference_id": "ref-1"}
    assert "prompt" not in song["payload"], "fal 422: a style cannot go with a reference"
    assert res.cost == pytest.approx(0.16)


def test_a_remix_needs_the_whole_track_and_a_model_without_guides_takes_none(falapi):
    provider, wire, tmp = falapi
    wire.replies.append({"id": "mix-1"})
    remix = "mureka/v9.5/song/remix"
    whole = SongRequest(
        lyrics="w", dst=tmp / "r.wav", style="house", duration=180, guide=_guide(tmp, "remix")
    )
    res = provider.song(whole, context(model=remix))
    assert wire.sent[-1]["payload"] == {
        "prompt": "house",
        "lyrics": "w",
        "upload_audio_id": "mix-1",
    }
    assert res.cost == pytest.approx(0.51)
    with pytest.raises(ValueError, match="give it one"):
        provider.song(SongRequest(lyrics="w", dst=tmp / "n.wav", style="x"), context(model=remix))
    with pytest.raises(ValueError, match="takes no reference track"):
        provider.song(
            SongRequest(lyrics="w", dst=tmp / "m.wav", style="x", guide=_guide(tmp)), context()
        )
    assert base.get("fal").inputs("song", remix).guides == {"remix": 0.0}
    assert base.get("fal").inputs("song", "mureka/v9.5/generate/song").guides == {"reference": 30.0}


def test_a_guided_song_is_priced_with_its_upload():
    provider = fal.Fal()
    model = "mureka/v9.5/generate/song"
    assert provider.estimate(Billable(capability="song"), model) == pytest.approx(0.15)
    assert provider.estimate(Billable(capability="song", guided=True), model) == pytest.approx(0.16)


def test_a_signed_guided_song_binds_the_clip_not_the_id_only_the_run_knows(falapi):
    """The upload id exists only once the paid run uploads, so the payload a person signed
    must name the clip by its bytes, the same in the rehearsal and in the run."""
    provider, wire, tmp = falapi
    words = SongRequest(lyrics="w", dst=tmp / "s.wav", style="house", guide=_guide(tmp))
    model = "mureka/v9.5/generate/song"
    with rehearsal.opened() as dry:
        provider.song(words, context(model=model))
    signed = [payloads.digest(r["model"], r["payload"]) for r in dry.loose]
    wire.replies.append({"id": "an-id-only-the-run-gets"})
    provider.song(words, context(model=model))
    ran = [payloads.digest(r["endpoint"], r["payload"]) for r in wire.sent[-2:]]
    assert len(signed) == 2 and ran == signed


def test_an_upload_keeps_its_own_request_id_and_is_charged_when_the_song_then_fails(
    tmp_path, monkeypatch
):
    """The upload is billed when it returns. If the song is then refused, the ledger still holds
    the upload, under its own request id, and the signed entry is not handed back."""
    from kalainova import gates
    from kalainova.providers import router
    from kalainova.providers.contract import InvalidRequestError

    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    monkeypatch.setenv("FAL_KEY", "k")
    refused = InvalidRequestError("fal answered 422: prompt and reference_id cannot be combined")
    wire = Wire({"id": "ref-1"}, refused)
    real_send = wire._send

    def send(endpoint, payload, ctx, *, wait, params):
        if endpoint.endswith("files/upload"):
            ctx.receipt.request_id = "req-upload"
        return real_send(endpoint, payload, ctx, wait=wait, params=params)

    monkeypatch.setattr(wire, "_send", send)
    monkeypatch.setattr(fal.Fal, "transport", wire)
    monkeypatch.setattr(media, "run", lambda *a, **k: None)
    given_back = []
    monkeypatch.setattr(gates, "give_back", lambda *a: given_back.append(a))
    job = make_job(tmp_path, media=["song"], cost_cap=5.0, providers={"song": ["fal"]})
    words = SongRequest(
        lyrics="w",
        dst=job.work / "s.wav",
        guide=_guide(tmp_path),
        pin=fal_pin(),
    )
    with pytest.raises(router.ProviderError, match="malformed"):
        router.generate(job, words, only=["fal"])
    rows = json.loads(job.ledger_path.read_text())
    assert [round(r["cost"], 4) for r in rows] == [0.01]
    assert rows[0]["steps"] == [
        {"model": "mureka/api/files/upload", "request_id": "req-upload", "billed_units": None,
         "cost": 0.01}
    ]  # fmt: skip
    assert rows[0]["request_id"] is None, "the song's own id is not the upload's"
    assert not given_back, "money went out under the signed entry, so it stays used"


def fal_pin():
    from kalainova.providers.contract import Pin

    return Pin(provider="fal", model="mureka/v9.5/generate/song")
