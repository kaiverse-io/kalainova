"""The review set: every verdict beside the readings it can be held against."""

from __future__ import annotations

import json

from fakes import make_job, needs_ffmpeg

from kalainova import media, verdicts


def _piece(tmp_path, monkeypatch, job_id, verdict, detail):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path, job_id=job_id)
    reading = {"id": "picture.detail", "value": detail, "limit": "x", "ok": True, "blocks": False}
    job.write(
        "qa",
        {
            "schema_version": "0.1",
            "job_id": job_id,
            "passed": True,
            "checks": [],
            "bar": {"readings": [reading]},
        },
    )
    verdicts.record(job, verdict, reviewer="someone")
    return job


def _shot_job(tmp_path, monkeypatch, path):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path, job_id="p1")
    asset = {"id": "b1.video", "kind": "video", "synthetic": True, "path": path}
    job.path("asset_manifest").write_text(json.dumps({"assets": [asset]}))
    cut = {"source": "b1.video", "in_sec": 0, "out_sec": 2}
    job.path("edit_manifest").write_text(json.dumps({"cuts": [cut]}))
    return job


def test_the_set_lists_every_sample_and_will_not_conclude_from_two(tmp_path, monkeypatch):
    _piece(tmp_path, monkeypatch, "p1", "accept", 0.9)
    _piece(tmp_path, monkeypatch, "p2", "reject", 0.1)
    text = verdicts.review_set(tmp_path / "jobs")
    assert "p1" in text and "p2" in text and "picture.detail" in text
    assert "accept" in text and "reject" in text
    assert verdicts.NOT_ENOUGH in text
    assert "higher is better" not in text


def test_an_empty_set_says_so(tmp_path):
    (tmp_path / "jobs").mkdir()
    assert "nothing can be said" in verdicts.review_set(tmp_path / "jobs")


@needs_ffmpeg
def test_a_shot_verdict_meets_what_its_own_source_clip_reads(tmp_path, monkeypatch):
    job = _shot_job(tmp_path, monkeypatch, "b1.mp4")
    media.run(
        ["-f", "lavfi", "-i", "testsrc2=s=320x180:d=2:r=24", "-pix_fmt", "yuv420p",
         str(job.work / "b1.mp4")]
    )  # fmt: skip
    verdicts.record(job, "reject", reviewer="someone", shot="b1")
    rows = verdicts.samples(tmp_path / "jobs")
    found = [r for r in rows if r["reading"] == "shot.source_motion"]
    assert len(found) == 1
    assert found[0]["shot"] == "b1" and found[0]["verdict"] == "reject" and found[0]["value"] > 0


def test_a_shot_verdict_with_the_media_gone_leaves_the_sample_out(tmp_path, monkeypatch):
    job = _shot_job(tmp_path, monkeypatch, "gone.mp4")
    verdicts.record(job, "reject", reviewer="someone", shot="b1")
    assert verdicts.samples(tmp_path / "jobs") == []


def test_a_preference_between_two_takes_round_trips_and_appears_in_review_set(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path, job_id="p1")
    job.path("takes").write_text(json.dumps({"shots": {"b1": {"takes": [{"n": 1}, {"n": 2}]}}}))
    verdicts.record(
        job, "accept", reviewer="someone", shot="b1", preferred=2, over=1, note="better rhythm"
    )
    text = verdicts.review_set(tmp_path / "jobs")
    assert "preferred 2 over 1" in text
    assert "note: better rhythm" in text
    assert "p1" in text


def test_a_preference_naming_a_take_that_does_not_exist_is_refused(tmp_path, monkeypatch):
    import pytest

    from kalainova.jobfs import ContractError

    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path, job_id="p1")
    job.path("takes").write_text(json.dumps({"shots": {"b1": {"takes": [{"n": 1}, {"n": 2}]}}}))
    with pytest.raises(ContractError, match="has no take 3"):
        verdicts.record(job, "accept", reviewer="someone", shot="b1", preferred=3, over=1)
    with pytest.raises(ContractError, match="has no take 4"):
        verdicts.record(job, "accept", reviewer="someone", shot="b1", preferred=1, over=4)
    with pytest.raises(ContractError, match="both --preferred and --over"):
        verdicts.record(job, "accept", reviewer="someone", shot="b1", preferred=1)
    with pytest.raises(ContractError, match="cannot be preferred over itself"):
        verdicts.record(job, "accept", reviewer="someone", shot="b1", preferred=1, over=1)


@needs_ffmpeg
def test_kalainova_song_command_ends_with_verdict_prompt(tmp_path, studio, capsys):
    from kalainova.__main__ import main

    job = make_job(tmp_path, job_id="song-1", media=["song"])
    job.write(
        "song",
        {
            "schema_version": "0.1",
            "job_id": "song-1",
            "title": "A Song",
            "style": "acoustic indie ballad",
            "duration_sec": 12,
            "sections": [
                {"kind": "verse", "lines": ["line one of words here", "line two of words here"]}
            ],
        },
    )
    assert main(["song", str(job.folder)]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert out[-1].startswith(
        "record verdict: kalainova verdict song-1 accept|fix|reject --reviewer NAME --note"
    )
