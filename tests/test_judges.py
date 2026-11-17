"""Learned judges are commands named in config, so a stand-in judge reads its scores from a map.

These tests fix what the engine does with what judges say: scores kept per judge, a failing judge
skipped, the first judge ranking takes that pass, and song takes already made scored together.
The real commands (providers/runners/muqeval_run.py, aesthetics_run.py) need their models and are
run by hand, not in CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from fakes import needs_ffmpeg
from test_blind_listening import _two_song_jobs

from kalainova import config, reviewpage, takes
from kalainova.bar import judges
from kalainova.jobfs import ContractError, Job

FAKE_JUDGE = """
import argparse, json, pathlib
p = argparse.ArgumentParser()
p.add_argument("--map", required=True)
p.add_argument("--out", required=True)
p.add_argument("--fail", action="store_true")
p.add_argument("files", nargs="+")
a = p.parse_args()
if a.fail:
    raise SystemExit("the model would not load")
said = json.loads(pathlib.Path(a.map).read_text())
def told(f):
    return said.get(f) or said.get(pathlib.Path(f).name)
out = {f: told(f) for f in a.files if told(f)}
pathlib.Path(a.out).write_text(json.dumps(out))
"""


@pytest.fixture
def judge(tmp_path, monkeypatch):
    script = tmp_path / "judge.py"
    script.write_text(FAKE_JUDGE)

    def set_judges(*rows: tuple[str, dict, bool]) -> None:
        listed = []
        for name, said, fails in rows:
            told = tmp_path / f"{name}.json"
            told.write_text(json.dumps(said))
            command = [sys.executable, str(script), "--map", str(told)]
            listed.append(
                {"name": name, "command": command + (["--fail"] if fails else []), "rank_by": "mi"}
            )
        monkeypatch.setitem(config.studio(), "judges", {"song": listed})

    return set_judges


def _files(tmp_path, *names: str) -> list[Path]:
    for name in names:
        (tmp_path / name).write_bytes(b"x")
    return [tmp_path / n for n in names]


def test_each_judge_scores_every_file_and_a_failing_judge_is_skipped(tmp_path, judge):
    a, b = _files(tmp_path, "a.wav", "b.wav")
    judge(
        ("first", {"a.wav": {"mi": 4.2, "mi_min": 3.9}, "b.wav": {"mi": 3.1}}, False),
        ("broken", {}, True),
        ("quiet", {"a.wav": {"quality": 8.0}}, False),
    )
    scores, notes = judges.score("song", [a, b])
    assert scores[a] == {"first.mi": 4.2, "first.mi_min": 3.9, "quiet.quality": 8.0}
    assert scores[b] == {"first.mi": 3.1}
    assert any("broken failed" in n and "would not load" in n for n in notes)
    assert any("quiet said nothing of b.wav" in n for n in notes)
    assert judges.rank_key("song") == "first.mi"
    assert judges.rank_value("song", scores[a]) == 4.2


def test_with_no_judge_set_nothing_is_judged(tmp_path, monkeypatch):
    monkeypatch.setitem(config.studio(), "judges", {"song": []})
    (one,) = _files(tmp_path, "a.wav")
    assert judges.configured("song") == []
    assert judges.of_take("song", one) == {}
    assert judges.rank_key("song") is None


def test_a_take_keeps_its_scores_and_the_one_that_ranks_it(tmp_path, judge):
    (one,) = _files(tmp_path, "a.wav")
    judge(("first", {"a.wav": {"mi": 4.5}}, False))
    assert judges.of_take("song", one) == {"judged": {"first.mi": 4.5}, "rank": 4.5}


def test_the_judge_ranks_passing_takes_and_never_lifts_a_failing_one():
    def take(n: int, ok: bool, rank: float | None = None, score: float = 1.0) -> dict:
        return {"n": n, "ok": ok, "readings": {"score": score, "rank": rank}}

    ranked = [take(0, True, 3.9), take(1, True, 4.6), take(2, False, 4.9)]
    assert takes._best(ranked) == 1, "of the passing takes, the judge's favourite"
    assert takes._best([take(0, True), take(1, True)]) == 0, "unjudged: the first that passes"
    none_pass = [take(0, False, 4.9, score=0.5), take(1, False, 3.0, score=0.9)]
    assert takes._best(none_pass) == 1, "with none passing, the closest to passing, not the judge's"


@needs_ffmpeg
def test_song_takes_already_made_are_judged_together_and_kept(tmp_path, studio, judge):
    jobs = _two_song_jobs(tmp_path)
    said = {}
    for i, job in enumerate(jobs):
        for take in takes.load(job)["shots"]["song"]["takes"]:
            said[str((job.work / take["file"]).resolve())] = {"mi": 3.0 + i + take["n"] / 10}
    judge(("first", said, False))
    told = reviewpage.judged(jobs).splitlines()
    assert told[0].startswith("arm-b take "), "listed best first"
    kept = takes.load(Job(jobs[1].folder))["shots"]["song"]["takes"][0]["readings"]
    assert kept["judged"]["first.mi"] == kept["rank"] >= 4.0
    assert "misses" in told[0]


def test_judging_with_no_judge_set_says_how_to_set_one(tmp_path, studio, monkeypatch):
    monkeypatch.setitem(config.studio(), "judges", {})
    with pytest.raises(ContractError, match="no judges.song"):
        reviewpage.judged([])
