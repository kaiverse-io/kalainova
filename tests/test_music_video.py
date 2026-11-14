"""A video cut to a track with no lyrics: bars, sections, an excerpt, the character, the cost."""

from __future__ import annotations

import json
import subprocess

import numpy as np
import pytest
from fakes import make_job, needs_ffmpeg
from kit_fixtures import Stub, make_character, make_stream

from kalainova import assets, media, qachecks, songs
from kalainova.editor import musiccuts as mc
from kalainova.editor import musicvideo
from kalainova.jobfs import ContractError, Job
from kalainova.providers import router

pytestmark = needs_ffmpeg
SR = 48000
BPM = 120.0  # a bar is 2 seconds; the numbers below follow from it


def _write(path, x):
    subprocess.run(
        [media.FFMPEG, "-y", "-loglevel", "error", "-f", "f32le", "-ar", str(SR), "-ac", "1",
         "-i", "-", "-ac", "2", str(path)],
        input=x.astype(np.float32).tobytes(),
        check=True,
    )  # fmt: skip
    return path


def _track(path, seconds=48.0, loud_from=24.0, steady=True):
    """A pulse with an accent on each bar, much louder from loud_from on."""
    x = np.zeros(int(seconds * SR), np.float32)
    beat = 60.0 / BPM
    rng = np.random.default_rng(3)
    for n in range(int(seconds / beat)):
        at = n * beat
        loud = at >= loud_from
        amp = (0.9 if loud else 0.25) * (1.0 if n % 4 == 0 else 0.7)
        i = int(at * SR)
        x[i : i + 900] += np.hanning(900) * amp
    return _write(path, x if steady else rng.standard_normal(x.size).astype(np.float32) * 0.05)


def _song(**extra):
    return {
        "schema_version": "0.1",
        "job_id": "p1",
        "title": "An Instrumental",
        "style": "an instrumental with a steady pulse",
        "instrumental": True,
        "sections": [{"kind": "intro"}, {"kind": "chorus"}],
        **extra,
    }


def _parent(tmp_path, **extra):
    job = make_job(tmp_path, media=["song"], **extra)
    return job


def _build(tmp_path, job, track, *, song=None, **kw):
    manifest = {"assets": [{"model": "a finished track"}]}
    return musicvideo.build(
        job, "p1-video", song=song or _song(), cues=[], words=[], final=track,
        manifest=manifest, profile=kw.pop("profile", "square"),
        still_only=kw.pop("still_only", False), say=lambda _: None, **kw,
    )  # fmt: skip


def _starts(child):
    packet = Job(child).read("script_packet")
    at, out = 0.0, []
    for beat in packet["beats"]:
        out.append(round(at, 3))
        at += beat["duration_sec"]
    return out, packet


def test_an_instrumental_track_with_a_steady_pulse_is_cut_on_bar_lines(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    track = _track(tmp_path / "t.wav")
    child = _build(tmp_path, _parent(tmp_path), track)
    starts, packet = _starts(child)
    assert len(starts) > 2
    bar = 60 / BPM * 4
    found = mc.analyse(track, 48.0)
    assert found["bars"][1] - found["bars"][0] == pytest.approx(bar, abs=0.05)
    for at in starts[1:]:
        assert min(abs(at - b) for b in found["bars"]) < 0.06
    assert sum(b["duration_sec"] for b in packet["beats"]) == pytest.approx(48.0, abs=0.1)


def test_the_biggest_rise_in_energy_gets_a_cut_where_the_drop_lands(tmp_path):
    found = mc.analyse(_track(tmp_path / "t.wav"), 48.0)
    assert found["rise"] is not None
    assert found["bars"][found["rise"][0]] == pytest.approx(24.0, abs=0.3)
    spans = mc.music_spans(found, 48.0, _song(), phrase_bars=100)
    assert [s["start"] for s in spans][1] == pytest.approx(24.0, abs=0.3)
    assert spans[1]["strong"]


def test_a_section_list_with_bars_starts_a_shot_at_each_section(tmp_path):
    track = _track(tmp_path / "t.wav")
    found = mc.analyse(track, 48.0)
    song = _song(
        sections=[
            {"kind": "intro", "bars": 5},
            {"kind": "verse", "bars": 3},
            {"kind": "chorus", "bars": 16},
        ]
    )
    spans = mc.music_spans(found, 48.0, song, phrase_bars=100)
    starts = [s["start"] for s in spans]
    for bar_no in (5, 8):
        assert any(abs(s - found["bars"][bar_no]) < 0.01 for s in starts)


def test_an_excerpt_starts_and_ends_on_bar_lines_and_is_within_a_bar_of_its_length(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    track = _track(tmp_path / "t.wav")
    child = _build(tmp_path, _parent(tmp_path), track, excerpt={"length": 19.0, "start": None})
    record = json.loads((Job(child).work / "music_cuts.json").read_text())
    a, b = record["window"]
    bars = mc.analyse(track, 48.0)["bars"]
    assert min(abs(a - x) for x in bars) < 0.01
    assert min(abs(b - x) for x in [*bars, 48.0]) < 0.01
    assert abs((b - a) - 19.0) <= 2.0 + 0.01
    assert a < 24.0 < b, "the drop sits inside the strongest stretch"
    assert media.duration(Job(child).work / "track.wav") == pytest.approx(b - a, abs=0.1)
    assert record["loudness"]["integrated_lufs"] is not None


def test_a_track_with_no_clear_pulse_is_reported_not_cut_on_a_guess(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    track = _track(tmp_path / "noise.wav", steady=False)
    with pytest.raises(ContractError, match="no steady pulse"):
        _build(tmp_path, _parent(tmp_path), track)
    with pytest.raises(ContractError, match="strongest stretch|cannot cut"):
        _build(
            tmp_path, _parent(tmp_path, job_id="p2"), track, excerpt={"length": 10.0, "start": None}
        )


def test_a_flat_steady_track_has_no_peak_to_anchor_a_short(tmp_path):
    flat = _track(tmp_path / "flat.wav", loud_from=999.0)
    found = mc.analyse(flat, 48.0)
    assert found["rise"] is None and "no clear energy peak" in " ".join(found["notes"])
    with pytest.raises(ContractError, match="no clear energy peak"):
        mc.window(found, 10.0)
    a, b = mc.window(found, 10.0, start=8.0)
    assert min(abs(a - x) for x in found["bars"]) < 0.01 and abs(a - 8.0) < 2.0


def _locked_parent(tmp_path):
    job = _parent(tmp_path, stream="chan", cast=["lead"], distribution_identity="id-1")
    job.write(
        "kit_lock",
        {
            "schema_version": "0.1",
            "job_id": "p1",
            "stream": "chan",
            "distribution_identity": "id-1",
            "cast": ["lead"],
            "generators": {},
            "kits": {},
            "canon": {"lines": 0, "sha256": "0" * 64},
        },
    )
    return job


def test_the_child_carries_the_stream_the_identity_and_the_kit_lock(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    child = Job(_build(tmp_path, _locked_parent(tmp_path), _track(tmp_path / "t.wav")))
    assert child.job["stream"] == "chan" and child.job["distribution_identity"] == "id-1"
    assert child.job["cast"] == ["lead"]
    assert child.read("kit_lock")["job_id"] == "p1-video"
    assert child.read("kit_lock")["stream"] == "chan"


def test_a_character_shot_never_runs_past_the_ceiling_and_changes_angle(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    track = _track(tmp_path / "t.wav")
    child = _build(tmp_path, _locked_parent(tmp_path), track, profile="short-9x16")
    packet = Job(child).read("script_packet")
    assert max(b["duration_sec"] for b in packet["beats"]) <= 3.2 + 1e-6
    sizes = [b["shot"]["size"] for b in packet["beats"] if "shot" in b]
    assert {"wide", "close", "medium"} <= set(sizes), "cutaways, not one long take"
    # without a character the phrase length stands
    plain = _build_plain(tmp_path, track)
    assert max(b["duration_sec"] for b in Job(plain).read("script_packet")["beats"]) > 3.2


def _build_plain(tmp_path, track):
    job = make_job(tmp_path, media=["song"], job_id="plain")
    return musicvideo.build(
        job, "plain-video", song=_song(), cues=[], words=[], final=track,
        manifest={"assets": [{}]}, profile="short-9x16", still_only=False, say=lambda _: None,
    )  # fmt: skip


def test_cuts_on_beat_reads_one_for_cuts_on_the_grid_and_lower_off_it():
    beats = [i * 0.5 for i in range(40)]
    assert mc.share_on_beat([2.0, 4.0, 8.5], beats) == 1.0
    assert mc.share_on_beat([2.13, 4.2, 8.25], beats) < 0.5


def test_qa_warns_when_the_cuts_of_a_track_video_are_off_the_grid(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    child = Job(_build(tmp_path, _parent(tmp_path), _track(tmp_path / "t.wav")))
    packet = child.read("script_packet")
    at, cuts = 0.0, []
    for beat in packet["beats"]:
        cuts.append({"start_sec": at})
        at += beat["duration_sec"]
    (on,) = qachecks.cuts_on_beat_checks(child, {"cuts": cuts})
    assert on["id"] == "edit.cuts_on_beat" and on["status"] == "pass"
    shifted = [{"start_sec": c["start_sec"] + 0.21} for c in cuts]
    (off,) = qachecks.cuts_on_beat_checks(child, {"cuts": shifted})
    assert off["status"] == "warn"


def test_the_estimate_is_said_before_any_call_and_a_costly_plan_is_refused(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    monkeypatch.setattr(router, "quote", lambda *a, **k: ("fake", 1.0))
    track = _track(tmp_path / "t.wav")
    said: list[str] = []
    job = _parent(tmp_path, cost_cap=2.0)
    with pytest.raises(ContractError, match="over the .* cap"):
        musicvideo.build(
            job, "p1-video", song=_song(), cues=[], words=[], final=track,
            manifest={"assets": [{}]}, profile="square", still_only=False, say=said.append,
        )  # fmt: skip
    assert any("shots" in line and "$" in line for line in said)
    assert not (tmp_path / "jobs" / "p1-video").exists(), "refused before a child was opened"


def test_a_full_length_track_defaults_to_stills_with_a_few_moving_shots(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    track = _track(tmp_path / "long.wav", seconds=120.0, loud_from=60.0)
    said: list[str] = []
    manifest = {"assets": [{}]}
    child = musicvideo.build(
        _parent(tmp_path), "long-video", song=_song(), cues=[], words=[], final=track,
        manifest=manifest, profile="square", still_only=False, say=said.append,
    )  # fmt: skip
    kinds = [b["visual_kind"] for b in Job(child).read("script_packet")["beats"]]
    assert kinds.count("video") == musicvideo.FULL_LENGTH_MOVING and "still" in kinds
    assert any("stills with camera moves" in line for line in said)
    assert songs  # the public entry point lives there


def _song_manifest(job_id: str) -> dict:
    return {
        "schema_version": "0.1",
        "job_id": job_id,
        "assets": [{"id": "a1", "kind": "audio", "path": "final.wav", "model": "fake-song"}],
    }


def test_song_video_opened_with_stream_has_stream_cast_and_kit_lock_and_shots_receive_refs(
    tmp_path, monkeypatch
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

    child_folder = songs.video_job(song_job, "s1-video", stream="chan", profile="short-9x16")
    child = Job(child_folder)

    assert child.job["stream"] == "chan"
    assert child.job["cast"] == ["lead"]
    assert child.has("kit_lock")
    lock = child.read("kit_lock")
    assert lock["stream"] == "chan"
    assert lock["cast"] == ["lead"]

    packet = child.read("script_packet")
    assert all(b.get("cast") == ["lead"] for b in packet["beats"])

    # Generating the assets passes character references to the video provider
    assets.run(child)
    vid_calls = [c for c in Stub.calls if c["capability"] == "video"]
    assert len(vid_calls) > 0
    assert all(c.get("references") for c in vid_calls)


def test_song_video_stream_with_video_model_taking_no_reference_images_refuses(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "streams").mkdir(parents=True, exist_ok=True)
    Stub.calls = []

    make_character(tmp_path)
    make_stream(
        tmp_path,
        "chan-no-ref",
        silent=True,
        generators={
            "image": {"provider": "stub", "model": "img-ref"},
            "video": {"provider": "stub", "model": "plain-vid"},
        },
    )

    # stub only supports reference on vid-ref or when in support dict
    monkeypatch.setattr(
        Stub,
        "reference_support",
        lambda self, cap, model: (
            {"max_images": 4}
            if cap == "image"
            else ({"max_images": 3} if model == "vid-ref" else {})
        ),
    )

    song_job = make_job(tmp_path, media=["song"], job_id="s2")
    song_job.write("song", _song())
    song_job.write("asset_manifest", _song_manifest("s2"))
    _track(song_job.work / "final.wav", seconds=12.0)

    with pytest.raises(ContractError, match="takes no reference images for video"):
        songs.video_job(song_job, "s2-video", stream="chan-no-ref")


def test_song_video_without_stream_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    song_job = make_job(tmp_path, media=["song"], job_id="s3")
    song_job.write("song", _song())
    song_job.write("asset_manifest", _song_manifest("s3"))
    _track(song_job.work / "final.wav", seconds=12.0)

    child_folder = songs.video_job(song_job, "s3-video")
    child = Job(child_folder)

    assert "stream" not in child.job
    assert "cast" not in child.job
    assert not child.has("kit_lock")


def test_song_video_refuses_if_track_rights_do_not_cover_stream_strategy(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "streams").mkdir(parents=True, exist_ok=True)

    make_character(tmp_path)
    make_stream(tmp_path, "chan", silent=True, strategy="generated")

    song_job = make_job(tmp_path, media=["song"], rights="funded-brief", job_id="s4")
    song_job.write("song", _song())
    song_job.write("asset_manifest", _song_manifest("s4"))
    _track(song_job.work / "final.wav", seconds=12.0)

    with pytest.raises(ContractError, match="cannot be used on strategy 'generated'"):
        songs.video_job(song_job, "s4-video", stream="chan")


def test_song_video_stream_without_video_media_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "streams").mkdir(parents=True, exist_ok=True)

    make_character(tmp_path)
    make_stream(tmp_path, "audio-only", silent=True, media=["audio"])

    song_job = make_job(tmp_path, media=["song"], job_id="s5")
    song_job.write("song", _song())
    song_job.write("asset_manifest", _song_manifest("s5"))
    _track(song_job.work / "final.wav", seconds=12.0)

    with pytest.raises(ContractError, match="does not make video"):
        songs.video_job(song_job, "s5-video", stream="audio-only")


def test_song_video_stream_pinned_model_passed_to_estimate(tmp_path, monkeypatch):
    from unittest.mock import patch

    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "streams").mkdir(parents=True, exist_ok=True)

    make_character(tmp_path)
    make_stream(
        tmp_path,
        "chan-pin",
        silent=True,
        generators={
            "image": {"provider": "stub", "model": "img-custom"},
            "video": {"provider": "stub", "model": "vid-pinned"},
        },
    )

    song_job = make_job(tmp_path, media=["song"], job_id="s6")
    song_job.write("song", _song())
    song_job.write("asset_manifest", _song_manifest("s6"))
    _track(song_job.work / "final.wav", seconds=12.0)

    quoted_models = []
    real_quote = router.quote

    def spy_quote(job, cap, *args, **kwargs):
        if cap == "video":
            quoted_models.append(kwargs.get("model"))
        return real_quote(job, cap, *args, **kwargs)

    with patch("kalainova.providers.router.quote", side_effect=spy_quote):
        songs.video_job(song_job, "s6-video", stream="chan-pin")

    assert "vid-pinned" in quoted_models


def test_song_video_stream_preserves_licensed_rights(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    (tmp_path / "jobs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "streams").mkdir(parents=True, exist_ok=True)

    make_character(tmp_path)
    make_stream(tmp_path, "owned-stream", silent=True, strategy="owned-derivative", rights="owned")

    song_job = make_job(tmp_path, media=["song"], rights="licensed", job_id="s7")
    song_job.write("song", _song())
    song_job.write("asset_manifest", _song_manifest("s7"))
    _track(song_job.work / "final.wav", seconds=12.0)

    child_folder = songs.video_job(song_job, "s7-video", stream="owned-stream")
    child = Job(child_folder)
    assert child.job.get("rights") == "licensed"
