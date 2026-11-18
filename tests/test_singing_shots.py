"""A character who sings: the shot list marks the shot, and the song's vocal stem sings it, in the
one call that makes the clip. Nothing is lip-synced afterwards."""

from __future__ import annotations

import json

import numpy as np
import pytest
from fakes import make_job, needs_ffmpeg
from kit_fixtures import Stub, make_character, make_stream
from test_music_video import SR, _parent, _song, _song_manifest, _track, _write

from kalainova import assets, media, songs
from kalainova.editor import musicvideo
from kalainova.jobfs import ContractError, Job
from kalainova.providers import router

pytestmark = needs_ffmpeg


def test_a_singing_shot_is_lip_synced_over_its_own_span_of_the_piece(tmp_path):
    listed = tmp_path / "shots.txt"
    listed.write_text(
        "Sings: front, waist up, she sings\nB-roll: hands on the faders\nSings: close\n"
    )
    spans = [{"start": 1.5 * i, "end": 1.5 * (i + 1), "text": ""} for i in range(4)]
    beats = musicvideo.beats_for(
        _song(), spans, ["video", "video", "still", "video"], cast=["lead"],
        shot_list=musicvideo.read_shots(listed),
    )  # fmt: skip
    assert beats[0]["visual_cue"] == "front, waist up, she sings"
    assert beats[0]["on_camera"] and beats[0]["sings"] == {"start_sec": 0.0, "end_sec": 1.5}
    assert "on_camera" not in beats[1] and "sings" not in beats[1], "B-roll has no one to sing"
    assert "sings" not in beats[2], "a still has no mouth to sync"
    assert beats[3]["sings"] == {"start_sec": 4.5, "end_sec": 6.0}
    with pytest.raises(ContractError, match="needs a character"):
        musicvideo.beats_for(
            _song(), spans, ["video"] * 4, cast=None, shot_list=musicvideo.read_shots(listed)
        )


def test_the_estimate_prices_a_singing_shot_as_one_sung_call(tmp_path, monkeypatch):
    prices = {"video": 1.0, "sing": 0.25}
    monkeypatch.setattr(
        router, "price", lambda job, asked, **k: ("fake", prices[asked.capability], [])
    )
    spans = [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 4.0}]
    said: list[str] = []
    total = musicvideo.estimate(
        _parent(tmp_path), spans, ["video", "video"], 0.5, said.append, takes_each=1,
        sings=[True, False],
    )  # fmt: skip
    assert total == pytest.approx(1.25), "the singing shot is one sung call, not a clip and a sync"
    assert "$0.25 of it for 1 singing shot(s), each sung in one call" in said[0]


def test_a_song_video_sings_each_singing_shot_from_its_line_in_one_call(
    tmp_path, monkeypatch, studio
):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "streams").mkdir(parents=True, exist_ok=True)
    Stub.calls = []
    make_character(tmp_path)
    make_stream(tmp_path, "chan", silent=True)
    song_job = make_job(tmp_path, media=["song"], job_id="s1")
    song_job.write("song", _song())
    song_job.write("asset_manifest", _song_manifest("s1"))
    _track(song_job.work / "final.wav", seconds=12.0)
    listed = tmp_path / "shots.txt"
    listed.write_text("Sings: front, she sings to the crowd\nB-roll: the faders\n")

    with pytest.raises(ContractError, match="no vocal\\s+stem"):
        songs.video_job(song_job, "s1-video", stream="chan", profile="short-9x16", shots=listed)
    assert not (tmp_path / "jobs" / "s1-video").exists(), "refused before a child was opened"

    # a stem whose level rises with time, so a slice says where in the song it was cut from
    _write(song_job.work / "vocals.wav", np.linspace(0.0, 0.6, int(12.0 * SR)))
    child = Job(
        songs.video_job(song_job, "s1-video", stream="chan", profile="short-9x16", shots=listed)
    )
    assert media.duration(child.work / "vocals.wav") == pytest.approx(12.0, abs=0.05)
    sung = [b for b in child.read("script_packet")["beats"] if b.get("sings")]
    assert sung and all(b["on_camera"] and b["cast"] == ["lead"] for b in sung)

    data = json.loads((child.folder / "job.json").read_text())
    data["providers"] = {**(data.get("providers") or {}), "sing": ["fake"]}
    (child.folder / "job.json").write_text(json.dumps(data))
    assets.run(Job(child.folder))
    sang = [c for c in studio.calls if c["capability"] == "sing"]
    ids = {b["id"] for b in sung}
    assert {c["audio"].name.split(".")[0] for c in sang} == ids, "each sung from its own line"
    assert all(c["still"].name == c["audio"].name.replace("voice.wav", "still.png") for c in sang)
    plain = [c for c in studio.calls if c["capability"] == "video"]
    assert not [c for c in plain if c["image"].name.split(".")[0] in ids], "none made unsung"
    assert not [c for c in studio.calls if c["capability"] == "lipsync"], "no mouth repainted"
    stem, _, rate = media.decode_stereo(child.work / "vocals.wav")
    for beat in sung:  # each line is cut from where its shot sits on the piece's clock
        start, end = beat["sings"]["start_sec"], beat["sings"]["end_sec"]
        line = child.work / "beats" / f"{beat['id']}.voice.wav"
        assert media.duration(line) == pytest.approx(end - start, abs=0.05)
        left, _, _ = media.decode_stereo(line)
        at = int(start * rate)  # the rising stem's level there, read the same way
        expected = float(np.mean(stem[at : at + rate // 100]))
        assert float(np.mean(left[: rate // 100])) == pytest.approx(expected, abs=0.005)
    assert any(b["sings"]["start_sec"] > 0 for b in sung), "a shot after the first is checked"


def test_a_planned_singing_shot_is_sung_unless_its_line_is_silent(tmp_path, monkeypatch, studio):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "streams").mkdir(parents=True, exist_ok=True)
    make_character(tmp_path)
    make_stream(tmp_path, "chan", silent=True)
    song_job = make_job(tmp_path, media=["song"], job_id="s1")
    song_job.write("song", _song())
    song_job.write("asset_manifest", _song_manifest("s1"))
    _track(song_job.work / "final.wav", seconds=12.0)
    _write(song_job.work / "vocals.wav", np.full(int(12.0 * SR), 0.5))
    listed = tmp_path / "shots.txt"
    listed.write_text("Sings: front, she sings\nSings: close, she sings\nB-roll: the faders\n")
    child = Job(
        songs.video_job(song_job, "s1-video", stream="chan", profile="short-9x16", shots=listed)
    )
    sung = [b for b in child.read("script_packet")["beats"] if b.get("sings")]
    assert len(sung) >= 2
    voice = np.full(int(12.0 * SR), 0.5)  # the excerpt's stem: one line part sung, one silent
    part, quiet = sung[0]["sings"], sung[1]["sings"]
    a, b = int(part["start_sec"] * SR), int(part["end_sec"] * SR)
    voice[a : a + int((b - a) * 0.7)] = 0.0
    voice[int(quiet["start_sec"] * SR) : int(quiet["end_sec"] * SR)] = 0.0
    _write(child.work / "vocals.wav", voice)
    data = json.loads((child.folder / "job.json").read_text())
    data["providers"] = {**(data.get("providers") or {}), "sing": ["fake"]}
    (child.folder / "job.json").write_text(json.dumps(data))
    assets.run(Job(child.folder))
    sang = {c["audio"].name.split(".")[0] for c in studio.calls if c["capability"] == "sing"}
    assert sung[0]["id"] in sang, "sung under half the way, as the plan chose: still sung"
    assert sung[1]["id"] not in sang, "a silent line has nothing to sing, so it is a plain clip"


def test_a_singing_span_that_ends_before_it_starts_fails_the_plan():
    from kalainova import shots

    beat = {
        "id": "s1",
        "on_camera": True,
        "cast": ["lead"],
        "sings": {"start_sec": 2.0, "end_sec": 1.0},
    }
    assert [p["id"] for p in shots._structure_problems([beat])] == ["plan.sings"]


def test_a_shot_that_says_she_sings_states_its_motion():
    from kalainova import shots

    beat = {"id": "s03", "visual_cue": "three-quarter, chest up: she sings with her eyes closed"}
    assert not [p for p in shots._moving_shot_problems(beat) if p["id"] == "motion_stated"]


def test_a_rehearsed_clip_is_as_long_as_the_vendor_was_asked_for():
    """A model that makes set lengths is asked for the next one up; the stand-in matches it, so a
    lip sync rehearsed on it is priced on the length the real clip comes back at."""
    from kalainova.providers import rehearsal

    assert rehearsal._sent_length({"duration": "3"}) == 3.0
    assert rehearsal._sent_length({"duration": 5}) == 5.0
    assert rehearsal._sent_length({"duration": "10s"}) == 10.0
    assert rehearsal._sent_length({}) is None
    assert rehearsal._sent_length({"duration": "auto"}) is None
