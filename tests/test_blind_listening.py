"""Song takes from several jobs heard blind: shuffled, at one loudness, ranked once."""

from __future__ import annotations

import json

import pytest
from fakes import needs_ffmpeg
from test_songs import _job

from kalainova import media, reviewpage, songs
from kalainova.jobfs import ContractError, Job

pytestmark = needs_ffmpeg


def _two_song_jobs(tmp_path):
    jobs = []
    for name in ("arm-a", "arm-b"):
        job = _job(tmp_path, job_id=name)
        songs.run(job)
        jobs.append(Job(job.folder))
    return jobs


def test_takes_are_heard_blind_at_one_loudness_and_ranked_once(tmp_path, studio):
    jobs = _two_song_jobs(tmp_path)
    page = reviewpage.blind(jobs)
    folder = page.parent
    text = page.read_text()
    assert "arm-a" not in text and "arm-b" not in text, "the page names no job or model"
    assert {f.name for f in folder.iterdir()} <= {"listen.html", *(f"{c}.wav" for c in "ABCDEFGH")}
    key = json.loads(reviewpage._key_path(folder).read_text())["takes"]
    assert len(key) >= 4 and {k["job"] for k in key} == {"arm-a", "arm-b"}
    levels = [media.loudness(folder / f"{k['letter']}.wav")["integrated_lufs"] for k in key]
    assert max(levels) - min(levels) < 1.0, "louder sounds better, so every take is at one level"
    letters = [k["letter"] for k in key]
    with pytest.raises(ContractError, match="rank every letter once"):
        reviewpage.rank(folder, ",".join(letters[:-1]), "the operator")
    told = reviewpage.rank(folder, ",".join(reversed(letters)), "the operator")
    assert told.splitlines()[0].startswith(f"1. {letters[-1]}: ")
    with pytest.raises(ContractError, match="ranked already"):
        reviewpage.rank(folder, ",".join(letters), "the operator")


def test_one_job_cannot_be_heard_blind_against_nothing(tmp_path, studio):
    with pytest.raises(ContractError, match="no song takes"):
        reviewpage.blind([_job(tmp_path, job_id="empty")])
