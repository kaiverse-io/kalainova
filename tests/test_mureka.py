"""Mureka's own API: the request fal's row sends, one song a call, the lossless file, the vendor's
song id with the day it lapses, a region edit, what its spec refuses, and its task polling."""

from __future__ import annotations

import datetime as dt
import json

import pytest
from fakes import Wire, context, needs_ffmpeg

from kalainova import media, song_repair
from kalainova.providers import balances, mureka
from kalainova.providers.contract import Repaint, SongRequest, UnavailableError

pytestmark = needs_ffmpeg
SECTIONS = [
    {"kind": "verse", "lines": ["Juntos, one breath in"], "style": "voice set back"},
    {"kind": "chorus", "lines": ["Hold the light"]},
]
TASK = {"id": "t1", "status": "succeeded",
        "choices": [{"id": "song-9", "url": "m.mp3", "wav_url": "w.wav"}]}  # fmt: skip


@pytest.fixture
def api(monkeypatch, tmp_path):
    monkeypatch.setenv("MUREKA_API_KEY", "k")
    wire = Wire(default=TASK, files={"w.wav": b"wav", "m.mp3": b"mp3"})
    monkeypatch.setattr(mureka.Mureka, "transport", wire)
    monkeypatch.setattr(media, "run", lambda *a, **k: None)
    return mureka.Mureka(), wire, tmp_path


def _song(tmp, **kw):
    base = {"lyrics": "[Verse]\nJuntos, one breath in\n", "dst": tmp / "s.wav",
            "style": "melodic house, female voice", "duration": 180, "sections": SECTIONS,
            "vocal_gender": "female"}  # fmt: skip
    return SongRequest(**{**base, **kw})


def test_a_song_goes_as_fals_row_sends_it_with_one_song_a_call(api):
    provider, wire, tmp = api
    res = provider.song(_song(tmp), context(model="mureka-9.5"))
    sent = wire.sent[-1]
    assert sent["endpoint"] == "song/generate"
    body = sent["payload"]
    assert body["model"] == "mureka-9.5" and body["n"] == 1, "each song is charged: never two"
    assert body["lyrics"].startswith("[Verse] voice set back\nJuntos"), "notes on the lyric tags"
    assert body["gender"] == "female" and body["duration"] == 180
    assert body["prompt"] == "melodic house, female voice"
    assert res.cost == pytest.approx(0.15)
    assert res.meta["song_id"] == "song-9"
    until = dt.date.fromisoformat(res.meta["song_id_until"])
    assert 28 <= (until - dt.date.today()).days <= 30


def test_the_lossless_file_is_fetched_before_the_mp3(api, monkeypatch):
    provider, wire, tmp = api
    fetched = []
    real = wire._download
    monkeypatch.setattr(wire, "_download", lambda url, dst: (fetched.append(url), real(url, dst)))
    provider.song(_song(tmp), context(model="mureka-9.5"))
    assert fetched == ["w.wav"]


def test_v9_is_sent_no_length_and_v95_holds_its_shortest(api):
    provider, wire, tmp = api
    provider.song(_song(tmp), context(model="mureka-9"))
    assert "duration" not in wire.sent[-1]["payload"]
    with pytest.raises(ValueError, match="at least 120 s"):
        provider.song(_song(tmp, duration=90), context(model="mureka-9.5"))


def test_what_the_spec_refuses_is_refused_before_sending():
    assert mureka.problems("mureka-9.5", {"model": "mureka-9.5", "lyrics": "w", "n": 1}) == []
    said = mureka.problems("mureka-9", {"model": "mureka-9", "lyrics": "w", "duration": 180,
                                        "prompt": "p", "reference_id": "r"})  # fmt: skip
    assert "only mureka-9.5 takes a duration" in said
    assert "prompt and reference_id cannot be combined" in said
    assert mureka.problems("mureka-9.5", {"model": "mureka-9.5", "lyrics": "w", "prompt": "p",
                                          "vocal_id": "v"}) == []  # fmt: skip
    assert mureka.problems("x", {"model": "mureka-9.5", "lyrics": "", "n": 4, "colour": 1}) == [
        "song/generate takes no field 'colour'",
        "song/generate needs lyrics",
        "n is 1 to 3",
    ]
    edit = mureka.problems("region-edit", {"lyrics": "w", "edit_start": 0, "edit_end": 2000})
    assert edit == [
        "a region edit names the song by song_id or by upload_audio_id, one of them",
        "the edited region is at least 3 s",
    ]


def test_a_section_is_sung_again_by_the_vendors_id_or_by_an_upload(api, monkeypatch):
    provider, wire, tmp = api
    take = tmp / "take.wav"
    take.write_bytes(b"x")
    monkeypatch.setattr(mureka.fal_song, "upload_copy", lambda path: path)
    span = Repaint(source=take, start_sec=69.1, end_sec=76.8, lyrics="[Pre-Chorus]\nJuntos",
                   vendor_id="song-9")  # fmt: skip
    res = provider.song(_song(tmp, repaint=span), context(model="region-edit"))
    sent = wire.sent[-1]
    assert sent["endpoint"] == "song/region-edit"
    assert sent["payload"] == {"lyrics": "[Pre-Chorus]\nJuntos", "edit_start": 69100,
                               "edit_end": 76800, "song_id": "song-9"}  # fmt: skip
    assert res.cost == pytest.approx(0.10)
    gone = Repaint(source=take, start_sec=69.1, end_sec=76.8, lyrics="[Pre-Chorus]\nJuntos")
    provider.song(_song(tmp, repaint=gone), context(model="region-edit"))
    assert wire.sent[-1]["payload"]["upload_audio_id"] == "up:take.wav"
    too_long = Repaint(source=take, start_sec=0, end_sec=40, lyrics="[Verse]\nW")
    with pytest.raises(ValueError, match="at most 30 s"):
        provider.song(_song(tmp, repaint=too_long), context(model="region-edit"))


def test_a_take_past_its_song_ids_month_goes_up_as_a_file():
    today = dt.date.today()
    fresh = {"provider": "mureka", "meta": {"song_id": "s", "song_id_until": today.isoformat()}}
    old = {
        "provider": "mureka",
        "meta": {"song_id": "s", "song_id_until": (today - dt.timedelta(days=1)).isoformat()},
    }
    assert song_repair._vendor_id(fresh, "mureka") == "s"
    assert song_repair._vendor_id(old, "mureka") is None
    assert song_repair._vendor_id(fresh, "fal") is None, "another vendor's id means nothing here"


class _Resp:
    def __init__(self, data, status=200):
        self.status_code, self._data, self.text, self.headers = status, data, json.dumps(data), {}

    def json(self):
        return self._data


def test_the_task_is_polled_until_it_is_done(monkeypatch):
    monkeypatch.setenv("MUREKA_API_KEY", "k")
    asked = []
    polls = iter([_Resp({"id": "t1", "status": "running"}), _Resp(TASK)])

    def post(url, **kw):
        asked.append(url)
        return _Resp({"id": "t1", "status": "preparing"})

    def get(url, **kw):
        asked.append(url)
        return next(polls)

    monkeypatch.setattr(mureka.requests, "post", post)
    monkeypatch.setattr(mureka.requests, "get", get)
    monkeypatch.setattr(mureka.time, "sleep", lambda s: None)
    ctx = context()
    reply = mureka.MurekaApi()._send("song/generate", {"lyrics": "w"}, ctx, wait=60, params={})
    assert reply.get("choices.0.wav_url") == "w.wav"
    query = f"{mureka.API}/song/query/t1"
    assert asked == [f"{mureka.API}/song/generate", query, query]
    assert ctx.receipt.request_id == "t1"


def test_a_failed_task_is_unavailable_and_a_long_wait_times_out(monkeypatch):
    monkeypatch.setenv("MUREKA_API_KEY", "k")
    failed = {"id": "t2", "status": "failed", "failed_reason": "lyrics refused"}
    monkeypatch.setattr(mureka.requests, "post", lambda url, **kw: _Resp(failed))
    with pytest.raises(UnavailableError, match="lyrics refused"):
        mureka.MurekaApi()._send("song/generate", {}, context(), wait=60, params={})
    monkeypatch.setattr(
        mureka.requests, "post", lambda url, **kw: _Resp({"id": "t3", "status": "queued"})
    )
    with pytest.raises(TimeoutError):
        mureka.MurekaApi()._send("song/generate", {}, context(), wait=0, params={})


def test_a_take_goes_up_for_an_edit_as_an_audio_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MUREKA_API_KEY", "k")
    take = tmp_path / "t.m4a"
    take.write_bytes(b"x")
    seen = {}

    def post(url, **kw):
        seen.update(url=url, purpose=kw["data"]["purpose"])
        return _Resp({"id": "file-1"})

    monkeypatch.setattr(mureka.requests, "post", post)
    assert mureka.MurekaApi()._upload(take) == "file-1"
    assert seen == {"url": f"{mureka.API}/files/upload", "purpose": "audio"}


def test_the_balance_is_read_in_dollars_from_cents(monkeypatch):
    monkeypatch.setenv("MUREKA_API_KEY", "k")

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"balance": 1000, "total_recharge": 1000}'

    monkeypatch.setattr(balances.urllib.request, "urlopen", lambda *a, **k: Reply())
    assert balances._mureka() == pytest.approx(10.0)
    monkeypatch.delenv("MUREKA_API_KEY")
    assert balances._mureka() is None
