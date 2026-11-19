"""From a song file to its release: what a song model is sent, what a take keeps, what is refused
before spend, a rehearsal of the takes, a pin set by command, the chosen master released, and the
record of what AI made."""

from __future__ import annotations

import json

import pytest
from fakes import Wire, context, make_job, needs_ffmpeg

from kalainova import media, rehearse, song_master, songs, takes
from kalainova.__main__ import main
from kalainova.jobfs import ContractError
from kalainova.providers import fal
from kalainova.providers.contract import SongRequest
from kalainova.render import release

pytestmark = needs_ffmpeg
MUREKA = "mureka/v9.5/generate/song"
VERSE = ["Paper boats on the kitchen floor", "Pencil marks beside the door"]


def _song(**extra):
    return {
        "schema_version": "0.1",
        "job_id": "p1",
        "title": "A Song",
        "style": "warm indie pop, acoustic guitar, clear lead vocal",
        "duration_sec": 12,
        "bpm": 120,
        "vocal_gender": "female",
        "words_by": "model",
        "sections": [{"kind": "verse", "lines": VERSE, "bars": 6}],
        **extra,
    }


@pytest.fixture
def mureka(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "k")
    wire = Wire(default={"audio": {"url": "u"}, "song_id": "vendor-17"}, files={"u": b"x"})
    monkeypatch.setattr(fal.Fal, "transport", wire)
    monkeypatch.setattr(media, "run", lambda *a, **k: None)
    return fal.Fal(), wire, tmp_path


# ---------------------------------------------------------------- what the model is sent


def test_the_vocal_gender_goes_to_mureka_as_its_own_setting(mureka):
    provider, wire, tmp = mureka
    req = SongRequest(lyrics="[Verse]\nW", dst=tmp / "s.wav", style="house", duration=180,
                      vocal_gender="female")  # fmt: skip
    res = provider.song(req, context(model=MUREKA))
    assert wire.sent[-1]["payload"]["gender"] == "female"
    assert res.meta == {"song_id": "vendor-17"}  # kept, so an edit of the take needs no upload


def test_an_instrumental_or_a_model_without_the_setting_is_sent_no_gender(mureka):
    provider, wire, tmp = mureka
    req = SongRequest(lyrics="[Inst]", dst=tmp / "s.wav", style="house", duration=180,
                      vocal_gender="male", instrumental=True)  # fmt: skip
    provider.song(req, context(model=MUREKA))
    assert "gender" not in wire.sent[-1]["payload"]
    sung = SongRequest(lyrics="[Verse]\nW", dst=tmp / "t.wav", style="pop", vocal_gender="male")
    provider.song(sung, context(model="fal-ai/lyria3/pro"))
    assert "gender" not in wire.sent[-1]["payload"]


@pytest.mark.parametrize("style", ["house, no autotune", "pop without reverb", "never any vocoder"])
def test_a_style_that_names_what_it_does_not_want_is_refused(style):
    found = songs.problems(_song(style=style))
    assert found and "avoid" in found[0]


def test_a_style_of_only_what_it_wants_passes():
    assert songs.problems(_song(style="nocturnal, notably bright pads, nonstop groove")) == []


# ---------------------------------------------------------------- before spend


def _job(tmp_path, song=None, **extra):
    job = make_job(tmp_path, media=["song"], **extra)
    job.write("song", song or _song())
    return job


def test_a_rehearsal_writes_down_each_planned_take_and_sends_nothing(tmp_path, studio):
    job = _job(tmp_path)
    pinned = {"provider": "fal", "model": MUREKA}
    job.write("job", {**job.job, "providers": {**job.job["providers"], "song": ["fal"]},
                      "brief": {**job.job["brief"], "song_model": pinned}})  # fmt: skip
    report = rehearse.run(job, check=None)
    asked = [r for c in report["calls"] if c["capability"] == "song" for r in c["requests"]]
    assert len(asked) == songs.SAFE_TAKES["takes"], report["stopped"]
    assert {r["payload"]["gender"] for r in asked} == {"female"}
    assert not report["stopped"]
    assert not takes.load(job)["shots"]  # the real job made nothing


def test_a_rehearsal_stops_where_the_run_would(tmp_path, studio):
    job = _job(tmp_path, _song(style="house, no autotune"))
    assert "avoid" in rehearse.run(job, check=None)["stopped"]


def test_a_pin_sets_the_song_model_and_its_takes_by_command(tmp_path, studio, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    job = _job(tmp_path)
    assert main(["pin", job.id, "song", f"fal:{MUREKA}", "--takes", "3"]) == 0
    data = json.loads(job.path("job").read_text())
    assert data["brief"]["song_model"] == {"provider": "fal", "model": MUREKA}
    assert data["providers"]["song"] == ["fal"]
    assert data["brief"]["takes"] == data["brief"]["max_takes"] == 3
    assert main(["pin", job.id, "song", "nowhere"]) != 0
    assert main(["pin", job.id, "transcribe", "fal:some-model"]) != 0


# ---------------------------------------------------------------- the release


def _made(tmp_path):
    job = _job(tmp_path)
    songs.run(job)
    return job


def test_a_release_says_what_ai_made_part_by_part(tmp_path, studio):
    job = _made(tmp_path)
    record = json.loads((job.work / "release" / release.AI_USE).read_text())
    assert record["parts"]["lyrics"] == {"by": "a model", "ai": True}
    assert record["parts"]["music"]["ai"] and record["parts"]["vocals"]["ai"]
    assert record["parts"]["mastering"]["ai"] is False
    assert record["suggested_ai_credits"] == ["All of the audio", "The lyrics"]


def test_words_a_person_wrote_are_not_credited_to_ai():
    record = release.ai_use(_song(words_by="person"), "fake: m", None)
    assert record["parts"]["lyrics"]["ai"] is False
    assert record["suggested_ai_credits"] == ["All of the audio"]


def test_only_a_master_a_person_chose_is_released(tmp_path, studio):
    job = _made(tmp_path)
    with pytest.raises(ContractError, match="no master options"):
        song_master.release(job)
    made = song_master.make(job, vocal_db=[-1.0, 1.0])
    with pytest.raises(ContractError, match="no one has chosen"):
        song_master.release(job)
    takes.choose(job, "master", made[1]["n"])
    final = song_master.release(job)
    assert media.loudness(final)["integrated_lufs"] == pytest.approx(-14, abs=1)
    song = next(a for a in job.read("asset_manifest")["assets"] if a["role"] == "song")
    assert song["provenance"]["master"]["take"] == made[1]["n"]
    assert song["provenance"]["master"]["vocal_db"] == 1.0
    record = json.loads((job.work / "release" / release.AI_USE).read_text())
    assert record["parts"]["mastering"]["chosen_by"] == "a person"


def test_a_master_of_another_song_take_is_refused_until_that_take_stands(tmp_path, studio):
    job = _job(tmp_path)
    job.write("job", {**job.job, "brief": {**job.job["brief"], "takes": 2, "max_takes": 2}})
    songs.run(job)
    other = next(t["n"] for t in takes.load(job)["shots"]["song"]["takes"]
                 if t["n"] != takes.chosen(job, "song")["n"])  # fmt: skip
    (made,) = song_master.make(job, take_n=other)
    takes.choose(job, "master", made["n"])
    with pytest.raises(ContractError, match="the song stands on take"):
        song_master.release(job)
