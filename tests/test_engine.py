"""Engine units plus one fast end-to-end render with local providers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kalainova import edit, media, render
from kalainova.jobfs import ContractError, Job
from kalainova.plan import extract_json
from kalainova.providers import base
from kalainova.providers.local import estimate_words
from kalainova.providers.remote import chars_to_words

HAVE_FFMPEG = shutil.which("ffmpeg") is not None


def test_estimate_words_monotonic_and_bounded():
    ws = estimate_words("Air scatters blue light, far more than red.", 3.0)
    assert len(ws) == 8
    assert all(a["end_sec"] <= b["start_sec"] + 1e-6 for a, b in zip(ws, ws[1:]))
    assert ws[-1]["end_sec"] <= 3.0


def test_chars_to_words_from_elevenlabs_alignment():
    al = {"characters": list("Hi you"), "character_start_times_seconds": [0, .1, .2, .3, .4, .5],
          "character_end_times_seconds": [.1, .2, .3, .4, .5, .6]}
    assert [w["text"] for w in chars_to_words(al)] == ["Hi", "you"]


def test_caption_cards_break_on_punctuation_and_width():
    words = [{"text": t, "start_sec": i * .3, "end_sec": i * .3 + .25} for i, t in
             enumerate("The sky is blue. Sunsets are red because".split())]
    cards = edit.caption_cards(words, {"blue"})
    assert cards[0]["text"].endswith("blue.") or "blue." in " ".join(c["text"] for c in cards)
    assert all(len(c["text"]) <= 20 for c in cards)
    assert any("emphasis" in c for c in cards)


def test_extract_json_from_fenced_reply():
    assert extract_json('Sure:\n```json\n{"a": 1}\n```') == {"a": 1}


def test_resolve_falls_back_to_local(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    assert base.resolve("voice", ["elevenlabs", "local"]).name == "local"


def test_executor_rejects_path_escape(tmp_path):
    with pytest.raises(ContractError):
        render._safe(tmp_path, "../../etc/passwd")


def test_executor_rejects_unknown_op(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    folder = tmp_path / "j"
    folder.mkdir()
    (folder / "job.json").write_text("{}")
    with pytest.raises(ContractError):
        render.execute(Job(folder), {"steps": [{"op": "shell", "args": {"cmd": "rm -rf /"}}]})


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_end_to_end_local_render(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    for k in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY"):
        monkeypatch.delenv(k, raising=False)
    folder = tmp_path / "jobs" / "e2e"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(json.dumps({
        "schema_version": "0.1", "job_id": "e2e", "strategy": "generated", "media": ["video", "audio"],
        "rights": "owned", "distribution_identity": "test", "status": "draft", "skip_funded": True, "cost_cap": 0,
        "brief": {"subject": "test", "duration_sec": 6}}))
    (folder / "script_packet.json").write_text(json.dumps({
        "schema_version": "0.1", "job_id": "e2e",
        "beats": [{"id": "b1", "role": "hook", "text": "Short test line one.", "on_screen": "Test"},
                  {"id": "b2", "role": "payoff", "text": "And line two lands.", "on_screen": "Done"}]}))
    from kalainova import assets, qa
    job = Job(folder)
    assets.run(job)
    edit.run(job)
    render.compile_plan(job)
    out = render.execute(job)
    report = qa.run(job)
    info = media.summarize(out)
    assert (info["width"], info["height"]) == (1080, 1920)
    assert report["passed"], [c for c in report["checks"] if c["status"] == "fail"]
    assert abs(report["metrics"]["integrated_lufs"] + 14) <= 1.0


# ---- regressions from the independent review -------------------------------------------
def _job(tmp_path, cap=None, **extra):
    folder = tmp_path / "jobs" / "r1"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(json.dumps({
        "schema_version": "0.1", "job_id": "r1", "strategy": "generated", "media": ["video", "audio"],
        "rights": "owned", "distribution_identity": "test", "status": "draft", "skip_funded": True,
        "cost_cap": cap, **extra}))
    return Job(folder)


def test_numeric_args_cannot_carry_filtergraph_text(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = _job(tmp_path)
    evil = {"steps": [{"op": "cut", "args": {"source": "a.png", "kind": "still", "in_sec": 0, "out_sec": 1,
                                             "fps": "30[in0];movie=/etc/passwd[m];[in0][m]overlay", "out": "x.mp4"}}]}
    with pytest.raises(ContractError, match="fps"):
        render.execute(job, evil)


def test_unknown_op_args_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = _job(tmp_path)
    plan = {"steps": [{"op": "loudnorm", "args": {"input": "a.wav", "out": "b.wav", "target_lufs": -14,
                                                  "true_peak_dbtp_max": -1, "extra": "-f lavfi"}}]}
    with pytest.raises(ContractError, match="unknown args"):
        render.execute(job, plan)


def test_cost_cap_refuses_before_the_call(tmp_path, monkeypatch):
    from kalainova.jobfs import CostCapExceeded
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = _job(tmp_path, cap=0.5)
    with pytest.raises(CostCapExceeded):
        job.reserve("fal", "video", 1.0)
    assert job.spent() == 0
    assert not issubclass(CostCapExceeded, RuntimeError)


def test_charge_records_then_stops_over_cap(tmp_path, monkeypatch):
    from kalainova.jobfs import CostCapExceeded
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = _job(tmp_path, cap=0.5)
    with pytest.raises(CostCapExceeded):
        job.charge("fal", "video", 0.9)
    assert job.spent() == pytest.approx(0.9)  # money already spent is never lost from the ledger


def test_ass_backslash_stays_literal():
    from kalainova.captions import esc
    out = esc("a\\Nb{\\b1}")
    assert "\\" not in out and "{" not in out


def test_render_plan_goes_stale_when_edit_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = _job(tmp_path)
    (job.folder / "edit_manifest.json").write_text('{"changed": true}')
    with pytest.raises(ContractError, match="stale"):
        render.execute(job, {"edit_manifest_sha256": "0" * 64, "steps": []})


@pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")
def test_approve_and_publish_are_bound_to_qa_bytes(tmp_path, monkeypatch):
    from kalainova import publish
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = _job(tmp_path, cap=1)
    final = job.work / "final.mp4"
    media.run(["-f", "lavfi", "-i", "color=c=black:s=64x64:d=0.5", str(final)])
    job.write("qa", {"schema_version": "0.1", "job_id": "r1", "passed": True, "checks": [],
                     "artifacts_sha256": {"video": publish.sha256_file(final)}})
    (job.folder / "script_packet.json").write_text(json.dumps({"schema_version": "0.1", "job_id": "r1",
                                                               "beats": [{"id": "b", "role": "hook", "text": "x"}]}))
    publish.approve(job, "human", platforms=["youtube"])
    assert publish.publish(job, "youtube", dry_run=True)["status"] == "dry_run"
    with open(final, "ab") as fh:
        fh.write(b"x")  # bytes change after approval
    with pytest.raises(ContractError, match="changed after approval"):
        publish.publish(job, "youtube", dry_run=True)


def test_measure_refuses_before_48h(tmp_path, monkeypatch):
    import datetime as dt
    from kalainova import publish
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    monkeypatch.setenv("YOUTUBE_ACCESS_TOKEN", "t")
    job = _job(tmp_path)
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    job.write("publish_log", {"schema_version": "0.1", "job_id": "r1",
                              "posts": [{"platform": "youtube", "at": now, "status": "posted", "post_id": "v"}]})

    class R:
        ok = True
        def raise_for_status(self): pass
        def json(self): return {"items": [{"statistics": {"viewCount": "10"}}]}
    monkeypatch.setattr(publish.requests, "get", lambda *a, **k: R())
    with pytest.raises(ContractError, match="48h"):
        publish.measure(job)
    snap = publish.measure(job, force=True)
    assert snap["views"] == 10 and "views_48h" not in snap
