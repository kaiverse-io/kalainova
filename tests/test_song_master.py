"""A song take's master as options a person hears blind: the vocal moved, a reference matched, a
level set, each read again once encoded, and each kept as a take of the master shot."""

from __future__ import annotations

import json
import stat
import subprocess

import numpy as np
import pytest
from fakes import make_job, needs_ffmpeg

from kalainova import media, reviewpage, song_master, songs, takes
from kalainova.__main__ import main
from kalainova.jobfs import ContractError
from kalainova.providers import base, mac, separator
from kalainova.providers.contract import SeparateRequest
from kalainova.providers.results import Context

pytestmark = needs_ffmpeg
VERSE = ["Paper boats on the kitchen floor", "Pencil marks beside the door"]
CHORUS = ["Hold the ladder steady now", "Hand me down the garden hose"]


def _song():
    return {
        "schema_version": "0.1",
        "job_id": "p1",
        "title": "A Song",
        "style": "warm indie pop, acoustic guitar, clear lead vocal",
        "duration_sec": 12,
        "bpm": 120,
        "sections": [
            {"kind": "verse", "lines": VERSE, "bars": 3},
            {"kind": "chorus", "lines": CHORUS, "bars": 3},
        ],
    }


def _ready(tmp_path):
    job = make_job(tmp_path, media=["song"])
    job.write("song", _song())
    songs.run(job)
    return job


def _tone(path, freq, seconds=4.0, amp=0.25, sr=48000):
    t = np.arange(int(seconds * sr)) / sr
    x = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    return song_master._write(np.stack([x, x], axis=1), sr, path)


def _stereo(path):
    left, right, _ = media.decode_stereo(path)
    return np.stack([left, right], axis=1)


# ---------------------------------------------------------------- what is asked


def test_every_vocal_level_is_offered_dry_and_with_each_reference(tmp_path):
    refs = [tmp_path / "a.flac", tmp_path / "b.flac"]
    for ref in refs:
        ref.write_bytes(b"x")
    options = song_master.plan([1.5, -1.5, 0, 1.5], refs)
    assert [(o.vocal_db, o.reference) for o in options[:3]] == [
        (-1.5, None),
        (-1.5, refs[0]),
        (-1.5, refs[1]),
    ]
    assert len(options) == 9  # three distinct levels, each dry and with two references
    assert options[3].label() == "vocal as made, no reference"
    assert options[1].label() == "vocal -1.5 dB, matched to a.flac"


def test_a_vocal_move_past_what_a_separated_vocal_stands_is_refused(tmp_path):
    with pytest.raises(ContractError, match="past 3 dB"):
        song_master.plan([0, 4.0], [])


def test_too_many_options_to_hear_at_once_and_a_missing_reference_are_refused(tmp_path):
    with pytest.raises(ContractError, match="no reference file"):
        song_master.plan([0], [tmp_path / "missing.wav"])
    refs = []
    for name in "abc":
        refs.append(tmp_path / f"{name}.wav")
        refs[-1].write_bytes(b"x")
    with pytest.raises(ContractError, match="more than 12"):
        song_master.plan([-2, -1, 1, 2], refs)


# ---------------------------------------------------------------- the vocal, moved


def test_a_vocal_left_alone_leaves_the_mix_sample_for_sample(tmp_path):
    mix, vocal = _tone(tmp_path / "mix.wav", 220), _tone(tmp_path / "v.wav", 440)
    out = song_master.balanced(mix, vocal, 0.0, tmp_path / "out.wav")
    assert np.array_equal(_stereo(out), _stereo(mix))


def test_a_moved_vocal_adds_only_its_change_to_the_mix(tmp_path):
    band, vocal = _tone(tmp_path / "band.wav", 220), _tone(tmp_path / "v.wav", 440)
    mix = song_master._write(_stereo(band) + _stereo(vocal), 48000, tmp_path / "mix.wav")
    out = _stereo(song_master.balanced(mix, vocal, 6.0, tmp_path / "out.wav"))
    gain = 10 ** (6 / 20)
    assert np.allclose(out, _stereo(band) + gain * _stereo(vocal), atol=1e-5)


# ---------------------------------------------------------------- the options, made


def test_each_option_is_a_master_take_at_its_level_and_read_once_encoded(tmp_path, studio):
    job = _ready(tmp_path)
    before = sum(1 for c in studio.calls if c["capability"] == "separate")
    made = song_master.make(job, vocal_db=[-1.5, 0, 1.5])
    shot = takes.load(job)["shots"]["master"]
    assert [t["n"] for t in shot["takes"]] == [0, 1, 2]
    assert [t["master"]["vocal_db"] for t in made] == [-1.5, 0.0, 1.5]
    for take in made:
        read = {r["id"]: r for r in take["readings"]["readings"]}
        assert abs(read["song.loudness"]["value"] - (-14)) <= 1
        assert set(take["master"]["encoded"]) == {"aac", "mp3"}
        assert "master.encoded_true_peak" in read
        assert take["master"]["stems"]["by"] == "fake"
        assert (job.work / take["file"]).is_file()
    assert sum(1 for c in studio.calls if c["capability"] == "separate") - before == 1  # once


def test_the_stems_are_split_once_and_split_again_for_another_model(tmp_path, studio, monkeypatch):
    job = _ready(tmp_path)

    def split():
        return sum(1 for c in studio.calls if c["capability"] == "separate")

    before = split()
    song_master.make(job, vocal_db=[1.0])
    song_master.make(job, vocal_db=[-1.0])
    assert split() - before == 1
    monkeypatch.setattr(song_master.config, "model_for", lambda *_: "another-model")
    song_master.make(job, vocal_db=[2.0])
    assert split() - before == 2


def test_a_level_sets_the_options_loudness_and_its_ceiling(tmp_path, studio):
    job = _ready(tmp_path)
    (take,) = song_master.make(job, level="song-loud")
    read = {r["id"]: r for r in take["readings"]["readings"]}
    assert abs(read["song.loudness"]["value"] - (-9)) <= 1
    assert read["song.true_peak"]["limit"] == "<= -2"
    with pytest.raises(ContractError, match="no profile"):
        song_master.make(job, level="nowhere")


def test_options_are_heard_by_a_free_transcriber_and_never_by_a_paid_one(tmp_path, studio):
    job = _ready(tmp_path)
    studio.heard = [{"start_sec": 1.0, "end_sec": 1.3, "text": w} for w in "hold ladder".split()]
    (take,) = song_master.make(job, hear=True)
    assert take["master"]["heard_by"] == "fake"
    assert "song.words_found" in {r["id"] for r in take["readings"]["readings"]}
    studio.free = False
    try:
        with pytest.raises(ContractError, match="costs nothing"):
            song_master.make(job, hear=True)
        with pytest.raises(ContractError, match="stem split on this machine"):
            song_master.make(job, vocal_db=[1.0])
    finally:
        studio.free = True


def _fake_python(tmp_path):
    """A stand-in for Matchering's environment: it copies the target and reports one warning."""
    script = tmp_path / "python"
    script.write_text(
        "#!/bin/sh\n"
        'while [ $# -gt 0 ]; do case "$1" in --target) t="$2";; --out) o="$2";; '
        '--report) r="$2";; esac; shift; done\n'
        'cp "$t" "$o"\n'
        'echo \'{"warnings": ["3003: resampled"], "info": []}\' > "$r"\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_a_reference_is_matched_by_matchering_and_what_it_said_is_kept(
    tmp_path, studio, monkeypatch
):
    job = _ready(tmp_path)
    ref = _tone(tmp_path / "reference.wav", 330)
    with pytest.raises(ContractError, match="needs Matchering"):
        song_master.make(job, references=[ref])
    fake, adapter = _fake_python(tmp_path), song_master.config.adapter
    monkeypatch.setattr(
        song_master.config,
        "adapter",
        lambda name: (
            {"use": "matchering", "python": str(fake)}
            if name == "reference_master"
            else adapter(name)
        ),
    )
    dry, matched = song_master.make(job, references=[ref])
    assert dry["master"]["reference"] is None
    assert matched["master"]["reference"]["name"] == "reference.wav"
    assert matched["master"]["matchering"]["warnings"] == ["3003: resampled"]


def test_master_options_are_heard_blind_and_ranked_like_song_takes(tmp_path, studio):
    job = _ready(tmp_path)
    song_master.make(job, vocal_db=[-1.0, 1.0])
    page = reviewpage.blind([job], "master")
    key = json.loads(reviewpage._key_path(page.parent).read_text())["takes"]
    assert {k["shot"] for k in key} == {"master"} and len(key) == 2
    told = reviewpage.rank(page.parent, "B,A", "a reviewer")
    assert "vocal" in told


def test_the_command_lists_each_option_and_how_to_hear_them(tmp_path, studio, capsys, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    job = _ready(tmp_path)
    assert main(["song", "master", job.id, "--vocal-db=-1,1"]) == 0
    out = capsys.readouterr().out
    assert "master take 0: vocal -1 dB" in out and "--blind --shot master" in out


# ---------------------------------------------------------------- the separator on this machine


def _fake_separator(tmp_path):
    """A stand-in for audio-separator: it writes a vocal and an other stem at 44.1 kHz."""
    script = tmp_path / "audio-separator"
    script.write_text(
        "#!/bin/sh\n"
        'src="$1"; shift\n'
        'while [ $# -gt 0 ]; do case "$1" in --output_dir) d="$2";; esac; shift; done\n'
        f'{media.FFMPEG} -loglevel error -y -i "$src" -ar 44100 "$d/x_(Vocals)_m.wav"\n'
        f'{media.FFMPEG} -loglevel error -y -i "$src" -ar 44100 "$d/x_(Other)_m.wav"\n'
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_the_separator_is_ready_only_when_its_command_is_there(tmp_path, monkeypatch):
    found = base.get("separator")
    monkeypatch.delenv(separator.COMMAND_ENV, raising=False)
    assert separator.COMMAND_ENV in found.missing_env("separate")
    monkeypatch.setenv(separator.COMMAND_ENV, str(tmp_path / "nothing"))
    assert any("names no file" in m for m in found.missing_env("separate"))
    monkeypatch.setenv(separator.COMMAND_ENV, str(_fake_separator(tmp_path)))
    assert found.available("separate") and found.free


def test_the_separators_stems_come_back_at_the_sources_own_rate(tmp_path, monkeypatch):
    monkeypatch.setenv(separator.COMMAND_ENV, str(_fake_separator(tmp_path)))
    src = _tone(tmp_path / "mix.wav", 220)
    req = SeparateRequest(src=src, vocals=tmp_path / "v.wav", rest=tmp_path / "r.wav")
    got = base.get("separator").separate(req, Context(deadline_sec=60))
    assert got.model.startswith("audio-separator:")
    for stem in (req.vocals, req.rest):
        assert media.stream_info(stem, "audio")["sample_rate"] == "48000"


def test_a_separator_that_leaves_no_vocal_says_what_it_left(tmp_path):
    (tmp_path / "only_(Instrumental)_m.wav").write_bytes(b"")
    with pytest.raises(RuntimeError, match="not a vocal and a rest"):
        separator.stems_in(tmp_path)


def test_the_mac_provider_does_not_offer_stems_without_the_tool(tmp_path, monkeypatch):
    python = tmp_path / "bin" / "python"
    python.parent.mkdir()
    python.write_text("")
    monkeypatch.setenv(mac.PYTHON_ENV, str(python))
    assert not base.get("mac").available("separate")
    (python.parent / "audio-separator").write_text("")
    assert base.get("mac").available("separate")


def test_the_matchering_runner_imports_nothing_from_the_engine():
    runner = song_master.RUNNERS / "matchering_run.py"
    text = runner.read_text()
    assert "kalainova" not in text.split('"""', 2)[2]
    assert subprocess.run(["python3", "-c", f"compile(open({str(runner)!r}).read(), 'r', 'exec')"],
                          check=False).returncode == 0  # fmt: skip
