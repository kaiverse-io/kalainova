"""The AI label follows the assets, per platform; a platform with no documented field is refused;
a publish time is held only where the platform's own API takes one."""

from __future__ import annotations

import datetime as dt

import pytest
from test_gate_master import _approvable

from kalainova import publish, render
from kalainova.jobfs import ContractError
from kalainova.publish import aggregator, labels

NOW = dt.datetime(2026, 11, 12, tzinfo=dt.UTC)


def test_a_real_only_piece_is_not_labelled_on_any_platform():
    assert labels.aggregator_fields("linkedin", False) == {}
    assert labels.aggregator_fields("tiktok", False) == {}


@pytest.mark.parametrize("platform", ["tiktok", "instagram", "youtube", "x", "threads", "facebook"])
def test_a_synthetic_piece_carries_the_documented_label(platform):
    assert labels.aggregator_fields(platform, True)["is_ai_generated"] == "true"


def test_facebook_reels_also_get_their_own_field():
    assert labels.aggregator_fields("facebook", True)["facebook_is_ai_generated"] == "true"


def test_a_platform_the_guide_does_not_cover_is_refused_for_synthetic_media():
    with pytest.raises(ContractError, match="no documented AI-label field"):
        labels.aggregator_fields("linkedin", True)


class _Reply:
    def raise_for_status(self):
        pass

    def json(self):
        return {"ok": True}


def test_the_upload_sends_the_label_only_when_the_piece_is_synthetic(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(
        aggregator.requests, "post", lambda url, **kw: sent.append(kw["data"]) or _Reply()
    )
    monkeypatch.setenv("UPLOAD_POST_API_KEY", "k")
    monkeypatch.setenv("UPLOAD_POST_USER", "u")
    clip = tmp_path / "f.mp4"
    clip.write_bytes(b"x")
    aggregator.upload_post(clip, "tiktok", "t", "c", synthetic=True)
    aggregator.upload_post(clip, "tiktok", "t", "c", synthetic=False)
    assert sent[0]["is_ai_generated"] == "true" and "is_ai_generated" not in sent[1]


def test_no_environment_variable_is_needed_to_name_the_label_field(tmp_path, monkeypatch):
    monkeypatch.delenv("UPLOAD_POST_AI_LABEL_FIELD", raising=False)
    monkeypatch.setattr(aggregator.requests, "post", lambda url, **kw: _Reply())
    monkeypatch.setenv("UPLOAD_POST_API_KEY", "k")
    monkeypatch.setenv("UPLOAD_POST_USER", "u")
    clip = tmp_path / "f.mp4"
    clip.write_bytes(b"x")
    assert aggregator.upload_post(clip, "instagram", "t", "c")["status"] == "posted"


def test_a_publish_time_is_held_only_where_the_platform_takes_one():
    got = labels.parse_publish_at("youtube", "2026-12-01T18:00:00+01:00", NOW)
    assert got == "2026-12-01T17:00:00Z"
    assert labels.parse_publish_at("tiktok", None, NOW) is None
    with pytest.raises(ContractError, match="cannot hold a scheduled post"):
        labels.parse_publish_at("tiktok", "2026-12-01T18:00:00Z", NOW)


@pytest.mark.parametrize("bad", ["soon", "2026-12-01T18:00:00", "2026-01-01T00:00:00Z"])
def test_a_bad_publish_time_is_refused(bad):
    with pytest.raises(ContractError):
        labels.parse_publish_at("youtube", bad, NOW)


def _synthetic(job, final):
    manifest = job.read("asset_manifest")
    manifest["assets"][0]["synthetic"] = True
    job.write("asset_manifest", manifest)
    render.stamp(job, final)


def test_a_dry_run_refuses_a_synthetic_piece_for_an_uncovered_platform(tmp_path, monkeypatch):
    job, final, _ = _approvable(tmp_path, monkeypatch)
    _synthetic(job, final)
    publish.approve(job, "human", platforms=["linkedin"])
    with pytest.raises(ContractError, match="no documented AI-label field"):
        publish.publish(job, "linkedin", dry_run=True)


def test_a_dry_run_records_the_label_and_the_time(tmp_path, monkeypatch):
    job, final, _ = _approvable(tmp_path, monkeypatch)
    _synthetic(job, final)
    publish.approve(job, "human", platforms=["youtube"])
    entry = publish.publish(job, "youtube", dry_run=True, publish_at="2099-01-01T00:00:00Z")
    assert entry["ai_label"] is True and entry["scheduled_for"] == "2099-01-01T00:00:00Z"
