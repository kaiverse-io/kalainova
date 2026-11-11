"""Release files, stems and length for a song, with the model faked and the audio real."""

from __future__ import annotations

import pytest
from fakes import make_job, needs_ffmpeg
from PIL import Image

from kalainova import media, songs
from kalainova.jobfs import ContractError
from kalainova.render import release

pytestmark = needs_ffmpeg
LINES = ["Paper boats on the kitchen floor", "Pencil marks beside the door"]


def _song(**extra):
    return {
        "schema_version": "0.1",
        "job_id": "p1",
        "title": "A Song",
        "style": "warm indie pop, acoustic guitar, clear lead vocal",
        "duration_sec": 12,
        "sections": [{"kind": "verse", "lines": LINES}],
        **extra,
    }


def _job(tmp_path, song=None):
    job = make_job(tmp_path, media=["song"])
    job.write("song", song or _song())
    return job


def _tags_of(path):
    info = media.probe(path)
    tags = dict(info["format"].get("tags") or {})
    for stream in info["streams"]:
        tags.update(stream.get("tags") or {})
    return {k.lower(): v for k, v in tags.items()}


def _cover(path, size):
    Image.new("RGB", size, (30, 60, 90)).save(path)


def test_a_song_leaves_release_files_with_tags_and_lyrics(tmp_path, studio):
    song = _song(byline="An Artist", release={"album": "An Album", "year": 2026, "track": 3})
    job = _job(tmp_path, song)
    songs.run(job)
    out = job.work / "release"
    wav = media.probe(out / "final.wav")["streams"][0]
    assert (wav["sample_rate"], wav["bits_per_sample"]) == ("44100", 16)
    flac = media.probe(out / "final.flac")["streams"][0]
    assert (flac["sample_rate"], flac["bits_per_raw_sample"]) == ("44100", "16")
    mp3 = media.probe(out / "final.mp3")
    assert mp3["streams"][0]["sample_rate"] == "44100"
    assert 300_000 <= int(mp3["format"]["bit_rate"]) <= 330_000
    for name in ("final.flac", "final.mp3"):
        tags = _tags_of(out / name)
        assert (tags["title"], tags["artist"], tags["album"]) == ("A Song", "An Artist", "An Album")
        assert tags["date"] == "2026"
        assert tags["track"].split("/")[0] == "3"
    assert (out / "lyrics.txt").read_text().startswith("[Verse]")
    assert (out / "lyrics.lrc").exists()
    assert "release" in job.read("asset_manifest")["assets"][0]["provenance"]


def test_a_cover_is_embedded_and_a_small_one_warns(tmp_path, studio, capsys):
    job = _job(tmp_path, _song(release={"cover": "cover.png"}))
    _cover(job.folder / "cover.png", (600, 400))
    songs.run(job)
    streams = media.probe(job.work / "release" / "final.mp3")["streams"]
    assert any(s["codec_type"] == "video" for s in streams)
    said = capsys.readouterr().out
    assert "square" in said
    assert "3000" in said
    made = job.read("asset_manifest")["assets"][0]["provenance"]["release"]
    assert made["cover"] is True
    assert len(made["warnings"]) == 2


def test_a_full_size_cover_does_not_warn(tmp_path):
    cover = tmp_path / "c.png"
    _cover(cover, (3000, 3000))
    assert release.cover_warnings(cover) == []


def test_a_cover_named_but_missing_is_refused(tmp_path, studio):
    job = _job(tmp_path, _song(release={"cover": "nope.png"}))
    with pytest.raises(ContractError, match="not in the job folder"):
        songs.run(job)


def test_a_cover_cannot_leave_the_job_folder(tmp_path, studio):
    job = _job(tmp_path, _song(release={"cover": "../../elsewhere.png"}))
    with pytest.raises(ContractError, match="escapes"):
        songs.run(job)


def test_stems_go_through_a_separate_provider_and_are_recorded(tmp_path, studio):
    job = _job(tmp_path)
    songs.run(job)
    asked = [c for c in studio.calls if c["capability"] == "separate"]
    assert len(asked) == 1
    assert (job.work / "vocals.wav").exists()
    assert (job.work / "instrumental.wav").exists()
    stems = job.read("asset_manifest")["assets"][0]["provenance"]["stems"]
    assert stems == {"vocals": "vocals.wav", "instrumental": "instrumental.wav"}


def test_a_song_longer_than_the_model_makes_is_refused_before_any_call(
    tmp_path, studio, monkeypatch
):
    monkeypatch.setattr("kalainova.config.audio_spec", lambda provider, model: {"max_sec": 10})
    job = _job(tmp_path, _song(duration_sec=30))
    with pytest.raises(ContractError, match="at most 10s"):
        songs.run(job)
    assert studio.calls == []
