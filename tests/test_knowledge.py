"""What the engine knows ships with it and is read the same way anywhere (ADR 0027): its own files
from the package, the studio's folder never inside it, directions by id and version, limits as
claims with sources, judges ready or not on this machine, and every take saying what made it."""

from __future__ import annotations

import hashlib
import json

import pytest
from fakes import make_job

from kalainova import (
    config,
    fingerprint,
    jobfs,
    judging_cli,
    knowledge,
    knowledge_cli,
    prompts,
    resources,
    takes,
)
from kalainova.bar import judges
from kalainova.jobfs import ContractError


def test_an_installed_copy_reads_its_own_files_from_the_package(tmp_path, monkeypatch):
    shipped = tmp_path / "_data"
    (shipped / "prompts").mkdir(parents=True)
    (shipped / "prompts" / "hello.md").write_text("from the package\n")
    monkeypatch.setattr(resources, "_packaged", lambda: shipped)
    assert resources.root() == shipped and not resources.in_checkout()
    assert prompts.load("hello") == "from the package\n"


def test_a_checkout_reads_its_own_files_from_its_root():
    assert resources.in_checkout()
    assert (resources.path("prompts") / "directions.yaml").is_file()


def test_an_unset_studio_folder_is_the_users_own_never_the_engines(monkeypatch):
    monkeypatch.delenv("KALAINOVA_HOME", raising=False)
    assert jobfs.home() == jobfs.default_home()
    assert resources.root() not in jobfs.home().parents and jobfs.home() != resources.root()


def test_an_installed_copy_never_asks_git_which_commit_it_is(monkeypatch):
    monkeypatch.setattr(resources, "in_checkout", lambda: False)
    fingerprint.code_stamp.cache_clear()
    try:
        assert fingerprint.git_sha() == "untracked"
        assert fingerprint.code_stamp() == f"v{fingerprint.engine_version()}"
    finally:
        fingerprint.code_stamp.cache_clear()


def test_a_judge_names_its_runner_wherever_the_engine_is_installed():
    named = judges.part("{runners}/syncnet_run.py")
    assert named == str(judges.RUNNERS / "syncnet_run.py") and judges.RUNNERS.is_dir()


def test_a_judge_is_ready_only_when_this_machine_has_what_it_names(tmp_path):
    script = tmp_path / "run.py"
    script.write_text("")
    ready = judges.Judge("ok", ("python3", str(script), "--model", "org/model-name"))
    assert judges.missing(ready) == []  # a model's name is not a file
    gone = judges.Judge("gone", (str(tmp_path / "no-python"), str(tmp_path / "no-weights.bin")))
    assert len(judges.missing(gone)) == 2


def test_every_kind_of_judge_says_whether_any_is_configured(monkeypatch):
    lines = judging_cli.judges_on_this_machine()
    assert lines == [f"{kind}: none configured" for kind in judges.KINDS]


def test_engine_agreement_returns_empty_when_no_preferences(tmp_path):
    assert judging_cli.engine_agreement(tmp_path) == {}


def test_judge_line_reports_missing_components(tmp_path):
    judge = judges.Judge("test_judge", (str(tmp_path / "missing"),))
    assert "missing" in judging_cli._judge_line("sync", judge)


def test_every_released_direction_is_pinned_so_its_text_cannot_change_under_its_version():
    assert knowledge.unpinned() == [], (
        "a direction's text changed under its version: give it a new version in "
        "prompts/directions.yaml and add that version's sha256 to prompts/directions.lock"
    )


def test_a_changed_text_under_an_old_version_is_caught(tmp_path, monkeypatch):
    shipped = tmp_path / "_data" / "prompts"
    shipped.mkdir(parents=True)
    (shipped / "directions.yaml").write_text('perform.sing:\n  version: 1\n  text: "changed"\n')
    pinned = hashlib.sha256(b"the original").hexdigest()
    (shipped / "directions.lock").write_text(json.dumps({"perform.sing@1": pinned}))
    monkeypatch.setattr(resources, "_packaged", lambda: tmp_path / "_data")
    assert knowledge.unpinned() == ["perform.sing@1"]


def test_a_studio_overrides_a_direction_under_its_own_version(monkeypatch):
    studio = {**config.studio(), "directions": {"perform.sing": {"version": 2, "text": "calm"}}}
    monkeypatch.setattr(knowledge.config, "studio", lambda: studio)
    found = knowledge.direction("perform.sing")
    assert (found.ref, found.text, found.layer) == ("perform.sing@studio-2", "calm", "studio")
    studio["directions"] = {"perform.sing": {"text": "no version"}}
    with pytest.raises(ContractError, match="version"):
        knowledge.directions()


def test_a_limit_no_source_states_is_unknown_never_safe():
    assert knowledge.limit({}, "prompt_chars") is None
    assert knowledge.claim_text(None).startswith("unknown")
    shown = knowledge_cli.guide_lines("fal-ai/wan/v2.7/image-to-video")
    assert any("unknown" in line for line in shown)


def test_the_guide_prints_a_kind_of_shot_and_a_models_limits_with_their_source():
    sung = knowledge_cli.guide_lines("sing")
    assert (
        sung[0].startswith("perform.sing@") and sung[1] == knowledge.direction("perform.sing").text
    )
    omni = knowledge_cli.guide_lines("bytedance/omnihuman/v2")
    assert any("at most 300" in line and "provisional" in line for line in omni)
    with pytest.raises(ContractError):
        knowledge_cli.guide_lines("no-such-thing")


def test_a_refresh_reports_drift_and_changes_nothing():
    schemas = {
        "bytedance/omnihuman/v2": {"prompt": {"type": "string", "maxLength": 250}},
        "heygen/avatar-6/image-to-video": {"motion_prompt": {"anyOf": [{"maxLength": 1200}]}},
        "fal-ai/kling-video/v3/pro/image-to-video": {"prompt": {"maxLength": 2500}},
    }
    before = json.dumps(config.studio(), sort_keys=True, default=str)
    found = {line.split(":")[0]: line for line in knowledge.refresh(lambda m: schemas.get(m, {}))}
    assert "DIFFERS" in found["bytedance/omnihuman/v2"]
    assert "agrees" in found["heygen/avatar-6/image-to-video"]
    assert "not recorded" in found["fal-ai/kling-video/v3/pro/image-to-video"]
    assert "unknown" in found["fal-ai/wan/v2.7/image-to-video"]
    assert json.dumps(config.studio(), sort_keys=True, default=str) == before


def test_a_take_records_what_made_it(tmp_path, studio):
    job = make_job(tmp_path)
    clip = tmp_path / "made.mp4"

    def make(seed, dst):
        dst.write_bytes(b"a take")
        return studio(), type("Res", (), {"seed": seed, "model": "m", "cost": 0, "meta": {},
                                          "words": []})()  # fmt: skip

    beat = {"id": "s00", "sings": {"start_sec": 0, "end_sec": 2}}
    made_with = knowledge.stamp(beat, {"still": "aa", "line": "bb"})
    take = takes.attempt(job, "s00", 0, suffix=".mp4", make=make,
                         assess=lambda p: ({}, True), made_with=made_with)  # fmt: skip
    found = take["made_with"]
    assert found["directions"] == [knowledge.direction("perform.sing").ref]
    assert found["inputs"] == {"still": "aa", "line": "bb"}
    assert found["engine"] and len(found["knowledge"]) == 12 and len(found["judges"]) == 12
    plain = takes.attempt(job, "s01", 0, suffix=".mp4", make=make, assess=lambda p: ({}, True))
    assert plain["made_with"]["directions"] == [] and clip.parent.is_dir()


def test_a_limit_the_vendor_publishes_is_checked_before_sending(monkeypatch):
    from kalainova.providers import fal_catalog

    stated = ({"prompt": {"type": "string", "maxLength": 10}}, frozenset({"prompt"}))
    monkeypatch.setattr(fal_catalog, "_inputs", lambda model: stated)
    assert fal_catalog.schema_problems("m", {"prompt": "x" * 10}) == []
    assert "11 characters" in fal_catalog.schema_problems("m", {"prompt": "x" * 11})[0]
