"""Kits and streams: the same character, voice, and rules, on whichever channel is asked for."""

from __future__ import annotations

import json

import pytest
from kit_fixtures import CHARACTER, make_character, make_stream, picture

from kalainova import blobstore, kitrules, kits, streams
from kalainova.jobfs import ContractError


# ------------------------------------------------------------------- kits
def test_freeze_makes_a_version_and_detects_later_edits(root):
    kit = make_character(root)
    assert kit["version"] == 1
    path = root / "kits/lead/v1/kit.json"
    edited = json.loads(path.read_text())
    edited["persona"]["traits"] = ["different"]
    path.write_text(json.dumps(edited))
    with pytest.raises(ContractError, match="was edited"):
        kits.load(root, "lead", 1)


def test_bump_leaves_the_old_version_alone(root):
    make_character(root)
    kits.bump(root, "lead")
    kits.merge(root, "lead", {"persona": {"traits": ["warmer"]}})
    assert kits.freeze(root, "lead", by="operator")["version"] == 2
    assert kits.load(root, "lead", 1)["persona"]["traits"] == ["dry"]


@pytest.mark.parametrize(
    "change, message",
    [
        ({"origin": {"invented": True, "real_person": True, "attested_by": "o"}}, "real person"),
        ({"origin": {"invented": True, "real_person": False, "attested_by": ""}}, "attested_by"),
        ({"person": {"fictional": True, "adult": True, "age": 17}}, "at least 18"),
        ({"person": {"fictional": True, "adult": False, "age": 30}}, "adult"),
    ],
)
def test_a_kit_that_breaks_the_likeness_or_age_rule_cannot_freeze(root, change, message):
    kits.new(root, "bad")
    kits.merge(root, "bad", CHARACTER)
    kits.add_file(root, "bad", "identity", picture(root, "f.png"))
    draft = kits.read_draft(root, "bad")
    draft.update(change)
    kits.write_draft(root, "bad", draft)
    with pytest.raises(ContractError, match=message):
        kits.freeze(root, "bad", by="operator")


def test_changed_store_bytes_are_caught(root):
    kit = make_character(root)
    entry = kit["identity"]["refs"][0]
    kits.blob_path(root, entry).write_bytes(b"another face")
    assert any("changed on disk" in p for p in kits.verify_files(root, kit))


# ----------------------------------------------------------------- request
def test_request_resolves_channel_identity_generators_and_lock(root):
    make_character(root)
    make_stream(root)
    job = streams.request(root, "chan", "a piece about mornings")
    record = job.job
    assert record["distribution_identity"] == "chan-id"
    assert record["providers"] == {"image": ["stub"], "video": ["stub"]}
    assert record["cast"] == ["lead"]
    lock = job.read("kit_lock")
    assert lock["kits"]["lead"]["version"] == 1


def test_one_character_on_two_channels_keeps_one_kit(root):
    make_character(root)
    make_stream(root, "one")
    make_stream(root, "two")
    a = streams.request(root, "one", "x").read("kit_lock")["kits"]["lead"]
    b = streams.request(root, "two", "y").read("kit_lock")["kits"]["lead"]
    assert a == b


def test_several_characters_means_the_request_must_choose(root):
    make_character(root, "lead")
    make_character(root, "guest", voice_id="voice-b")
    make_stream(root, roles={"lead": "lead@1", "guest": "guest@1"})
    with pytest.raises(ContractError, match="choose with --cast"):
        streams.request(root, "chan", "x")
    assert streams.request(root, "chan", "x", cast=["guest"]).job["cast"] == ["guest"]
    with pytest.raises(ContractError, match="not on this stream"):
        streams.request(root, "chan", "x", cast=["stranger"])


def test_two_kits_cannot_fill_one_slot(root):
    for kit_id in ("a", "b"):
        kits.new(root, kit_id)
        kits.merge(root, kit_id, {"style": {"text": kit_id}})
        kits.freeze(root, kit_id, by="operator")
    with pytest.raises(ContractError, match="both fill style"):
        make_stream(root, roles={"a": "a@1", "b": "b@1"})


def test_a_generator_that_cannot_hold_a_face_stops_before_spending(root):
    make_character(root)
    make_stream(
        root,
        generators={
            "image": {"provider": "stub", "model": "img-ref"},
            "video": {"provider": "local", "model": "x"},
        },
    )
    with pytest.raises(ContractError, match="takes no reference images for video"):
        streams.request(root, "chan", "x")
    assert not list((root / "jobs").iterdir())


def test_no_voice_stops_the_request(root):
    kits.new(root, "mute")
    kits.merge(root, "mute", {k: v for k, v in CHARACTER.items() if k != "voice"})
    kits.add_file(root, "mute", "identity", picture(root, "m.png"))
    kits.freeze(root, "mute", by="operator")
    make_stream(root, roles={"mute": "mute@1"})
    with pytest.raises(ContractError, match="default voice"):
        streams.request(root, "chan", "x")


def test_identity_belongs_to_one_stream(root):
    make_character(root)
    make_stream(root, "one", distribution_identity="same")
    with pytest.raises(ContractError, match="one identity, one stream"):
        make_stream(root, "two", distribution_identity="same")


def test_amplification_is_off_until_the_operator_opens_it(root):
    make_character(root)
    make_stream(root)
    with pytest.raises(ContractError, match="is off"):
        streams.request(root, "chan", "x", amplify="noticed a thing")


# ---------------------------------------------------------------- schedule
def test_schedule_keeps_the_daily_limit_and_renders_nothing(root):
    make_character(root)
    make_stream(root)
    streams.schedule_add(root, "chan", "2026-12-01", "first")
    with pytest.raises(ContractError, match="daily limit"):
        streams.schedule_add(root, "chan", "2026-12-01", "second")
    assert not list((root / "jobs").iterdir())
    job = streams.request(root, "chan", slot="2026-12-01")
    assert job.job["brief"]["subject"] == "first"
    slot = streams.read_schedule(root, "chan")["slots"][0]
    assert slot == {
        "date": "2026-12-01",
        "brief": "first",
        "status": "requested",
        "job_id": job.id,
    }


def test_schedule_stops_at_thirty_open_slots(root):
    make_character(root)
    make_stream(root, max_per_day=2)
    days = [f"2026-12-{d:02d}" for d in range(1, 16)]
    for day in days:
        streams.schedule_add(root, "chan", day, "a")
        streams.schedule_add(root, "chan", day, "b")
    with pytest.raises(ContractError, match="30 open slots"):
        streams.schedule_add(root, "chan", "2027-01-01", "c")


# -------------------------------------------------------------- blob store
class FakeS3:
    def __init__(self):
        self.objects = {}
        self.extra = None

    def upload_file(self, path, bucket, key, ExtraArgs=None):  # noqa: N803  # boto3's name
        self.objects[(bucket, key)] = open(path, "rb").read()
        self.extra = ExtraArgs

    def download_file(self, bucket, key, path):
        with open(path, "wb") as fh:
            fh.write(self.objects[(bucket, key)])


def test_store_pushes_encrypted_and_fetches_by_hash(root, monkeypatch):
    monkeypatch.setenv("KALAINOVA_STORE_URI", "s3://bucket/kits")
    monkeypatch.setenv("KALAINOVA_KMS_KEY", "key-1")
    s3 = FakeS3()
    monkeypatch.setattr(blobstore, "_client", lambda: s3)
    entry = kits.put(root, picture(root, "f.png"))
    assert s3.extra == {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": "key-1"}
    sha = entry["sha256"]
    assert ("bucket", f"kits/{sha[:2]}/{sha}.png") in s3.objects

    (root / "store" / sha[:2] / f"{sha}.png").unlink()
    assert kits.sha256_file(kits.blob_path(root, entry)) == sha


def test_store_refuses_bytes_that_do_not_match_their_hash(root, monkeypatch):
    monkeypatch.setenv("KALAINOVA_STORE_URI", "s3://bucket/kits")
    s3 = FakeS3()
    monkeypatch.setattr(blobstore, "_client", lambda: s3)
    entry = kits.put(root, picture(root, "f.png"))
    sha = entry["sha256"]
    s3.objects[("bucket", f"kits/{sha[:2]}/{sha}.png")] = b"tampered"
    (root / "store" / sha[:2] / f"{sha}.png").unlink()
    with pytest.raises(ContractError, match="do not match"):
        kits.blob_path(root, entry)
    assert not (root / "store" / sha[:2] / f"{sha}.png").exists()


def test_kit_rules_are_stdlib_only():
    assert kitrules.parse_pin("lead@3") == ("lead", 3)
    with pytest.raises(ValueError, match="must look like"):
        kitrules.parse_pin("lead")


# ----------------------------------------------------------------- the CLI
def test_the_commands_take_a_character_from_files_to_a_locked_job(root, tmp_path, capsys):
    from kalainova.__main__ import main

    fields = tmp_path / "fields.json"
    fields.write_text(json.dumps(CHARACTER))
    face = picture(root, "front.png")
    steps = [
        ["kit", "new", "lead"],
        ["kit", "set", "lead", str(fields)],
        ["kit", "add", "lead", "identity", str(face), "--label", "front"],
        ["kit", "freeze", "lead", "--by", "operator"],
        ["kit", "show", "lead"],
        [
            "stream", "new", "chan", "--identity", "chan-id", "--kit", "lead=lead@1",
            "--image", "stub:img", "--video", "stub:vid", "--account", "youtube=handle",
            "--cost-cap", "5",
        ],
        ["stream", "canon", "chan", "A fact", "--by", "operator"],
        ["schedule", "chan", "2026-12-01", "A dated brief"],
        ["stream", "show", "chan"],
        ["request", "chan", "A brief"],
    ]  # fmt: skip
    for step in steps:
        assert main(step) == 0, step
    out = capsys.readouterr().out
    assert "lead@1" in out
    assert "what stays fixed, and how:" in out
    assert "reference files sent with every still and video" in out
    assert "kalainova make" in out
    assert main(["request", "chan", "x", "--cast", "stranger"]) == 1
    assert "not on this stream" in capsys.readouterr().err


def test_a_stream_pinned_to_a_draft_or_unnumbered_kit_is_refused_cleanly(tmp_path):
    from kalainova import consistency
    from kalainova.jobfs import ContractError

    for pin in ("lead@draft", "lead"):
        with pytest.raises(ContractError, match="frozen, numbered version"):
            consistency.resolve(tmp_path, {"kits": {"lead": pin}})
