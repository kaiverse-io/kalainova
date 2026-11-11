"""What people said, which readings predicted it, and the record of how a piece was made."""

from __future__ import annotations

import json

import pytest
from fakes import make_job

from kalainova import provenance, takes, verdicts
from kalainova.jobfs import ContractError


def _job(tmp_path, monkeypatch, job_id="p1", **extra):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    return make_job(tmp_path, job_id=job_id, **extra)


def test_a_verdict_names_the_person_who_gave_it(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    entry = verdicts.record(job, "reject", reviewer="someone", shot="b3", note="door opens wrong")
    assert entry["reviewer"] == "someone" and entry["shot"] == "b3"
    assert verdicts.load(job.folder) == [entry]
    with pytest.raises(ContractError, match="names the person"):
        verdicts.record(job, "accept", reviewer="  ")


def test_a_verdict_is_one_of_three_things(tmp_path, monkeypatch):
    with pytest.raises(ContractError, match="one of"):
        verdicts.record(_job(tmp_path, monkeypatch), "maybe", reviewer="someone")


def test_a_verdict_is_not_an_approval(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    verdicts.record(job, "accept", reviewer="someone")
    assert not job.has("approval")


@pytest.mark.parametrize(
    ("good", "bad", "expected"),
    [
        ([3.0, 4.0], [1.0, 2.0], 1.0),
        ([1.0, 2.0], [3.0, 4.0], 0.0),
        ([1.0, 2.0], [1.0, 2.0], 0.5),
        ([], [1.0], 0.5),
    ],
)
def test_separation_says_how_often_a_good_sample_reads_higher(good, bad, expected):
    assert verdicts.separation(good, bad) == expected


@pytest.mark.parametrize(
    ("auc", "says"),
    [
        (verdicts.SEPARATES_AT, "higher is better"),
        (1 - verdicts.SEPARATES_AT, "lower is better"),
        (0.5, "does not separate: ADR 0011 says delete it"),
    ],
)
def test_a_reading_right_at_the_limit_counts_as_separating(auc, says):
    assert verdicts._verdict_on(auc, True) == says


def test_plenty_of_one_verdict_and_few_of_the_other_is_still_too_few(monkeypatch, tmp_path):
    points = [(1.0, "accept")] * 5 + [(0.0, "reject")]
    monkeypatch.setattr(verdicts, "_gather", lambda root: {"a.reading": points})
    assert verdicts.signals(tmp_path)[0]["reads"] == "too few verdicts"


def _reading(rid, value):
    return {"id": rid, "value": value, "limit": "x", "ok": True, "blocks": False}


def _piece(tmp_path, monkeypatch, job_id, verdict, value, text_value="0.5 b1"):
    job = _job(tmp_path, monkeypatch, job_id=job_id)
    job.write(
        "qa",
        {
            "schema_version": "0.1",
            "job_id": job_id,
            "passed": True,
            "checks": [],
            "bar": {
                "readings": [
                    _reading("picture.detail", value),
                    _reading("source.shot_motion", text_value),
                ]
            },
        },
    )
    verdicts.record(job, verdict, reviewer="someone")
    return job


def test_a_reading_that_tracks_the_verdicts_is_named_and_one_that_does_not_is_condemned(
    tmp_path, monkeypatch
):
    for n, (verdict, detail) in enumerate(
        [
            ("accept", 0.9),
            ("fix", 0.2),
            ("accept", 0.7),
            ("accept", 0.85),
            ("reject", 0.1),
            ("reject", 0.2),
            ("reject", 0.3),
        ]
    ):
        _piece(tmp_path, monkeypatch, f"p{n}", verdict, detail)
    rows = {r["signal"]: r for r in verdicts.signals(tmp_path / "jobs")}
    assert rows["picture.detail"]["reads"] == "higher is better"
    assert rows["source.shot_motion"]["reads"].startswith("does not separate")


def test_a_reading_with_too_few_verdicts_says_nothing_yet(tmp_path, monkeypatch):
    _piece(tmp_path, monkeypatch, "p0", "accept", 0.9)
    _piece(tmp_path, monkeypatch, "p1", "reject", 0.1)
    rows = {r["signal"]: r for r in verdicts.signals(tmp_path / "jobs")}
    assert rows["picture.detail"]["reads"] == "too few verdicts"


def test_a_shot_verdict_is_held_against_the_take_the_piece_used(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    takes.record(
        job,
        "b1",
        {
            "n": 0,
            "seed": 1,
            "file": "x",
            "ok": True,
            "readings": {"score": 0.3, "shot_motion": 0.3},
        },
    )
    verdicts.record(job, "reject", reviewer="someone", shot="b1")
    rows = {r["signal"]: r for r in verdicts.signals(tmp_path / "jobs")}
    assert rows["shot.shot_motion"]["bad"] == 1
    assert "shot.score" not in rows, "a score is made of readings, not a reading"


def test_no_verdicts_means_nothing_to_say(tmp_path, monkeypatch):
    _job(tmp_path, monkeypatch)
    assert verdicts.signals(tmp_path / "jobs") == []


def _manifest(job, *assets):
    job.write(
        "asset_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "assets": [{"kind": "video", "path": "x", **a} for a in assets],
        },
    )


def test_each_asset_says_what_made_it_and_what_its_terms_ask(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    _manifest(
        job,
        {
            "id": "b1.video",
            "provider": "mac",
            "model": "notapalindrome/ltx2-mlx-av",
            "rights": "owned",
            "synthetic": True,
            "prompt": "Waves roll",
            "provenance": {"seed": 7, "weights_revision": "abc", "take": 1},
        },
    )
    report = provenance.report(job)
    line = report["assets"][0]
    assert line["seed"] == 7 and line["weights_revision"] == "abc" and line["take"] == 1
    assert line["licence"] == "LTX-2 Community" and line["prompt"] == "Waves roll"
    assert any("$10M" in owed for owed in report["obligations"])


def test_a_model_nobody_has_read_is_called_out(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    _manifest(job, {"id": "v", "provider": "mac", "model": "brand-new"})
    assert provenance.report(job)["unknown_licences"] == ["v"]


def test_what_people_decided_is_kept_beside_what_the_models_did(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    _manifest(job, {"id": "v", "provider": "operator"})
    (job.folder / "direction.json").write_text(
        json.dumps({"notes": [{"at": "t", "text": "slower opening"}]})
    )
    verdicts.record(job, "fix", reviewer="someone", note="warmer")
    takes.record(job, "b1", {"n": 0, "seed": 1, "file": "x", "ok": True})
    takes.choose(job, "b1", 0)
    kinds = [d["kind"] for d in provenance.report(job)["human_decisions"]]
    assert kinds == ["direction", "verdict", "chose a take"]


def test_the_record_holds_the_hashes_of_the_files_it_is_about(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    _manifest(job, {"id": "v", "provider": "operator"})
    (job.work / "final.mp4").write_bytes(b"film")
    (job.work / "final.master.mov").write_bytes(b"master")
    files = provenance.report(job)["files"]
    assert set(files) == {"final.mp4", "final.master.mov"}


def test_the_record_totals_the_ledger_by_provider(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    _manifest(job, {"id": "v", "provider": "operator"})
    job.charge("fal", "video", 1.5)
    job.charge("fal", "image", 0.5)
    job.charge("elevenlabs", "voice", 0.25)
    ledger = provenance.report(job)["ledger"]
    assert ledger["by_provider"] == {"fal": 2.0, "elevenlabs": 0.25}
    assert ledger["total_estimated"] == 2.25


def test_the_record_is_written_with_the_job(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    _manifest(job, {"id": "v", "provider": "operator"})
    assert json.loads(provenance.write(job).read_text())["job_id"] == "p1"


def test_only_an_accept_counts_as_acceptance():
    assert verdicts.GOOD == {"accept"}
    assert "fix" in verdicts.CHOICES and "fix" not in verdicts.GOOD
