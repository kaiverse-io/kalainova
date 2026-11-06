"""Kits and streams: the same character, voice, and rules, on whichever channel is asked for."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from kalainova import assets, blobstore, consistency, kitrules, kits, media, streams
from kalainova import publish as pub
from kalainova.jobfs import ContractError, Job
from kalainova.providers import base, remote, router


class Stub(base.Provider):
    """Records what it was sent. Stands in for a paid model that takes references."""

    name = "stub"
    capabilities = ("voice", "image", "video", "music", "sfx")
    env_key = None
    free = True
    calls: list[dict] = []
    support = {"image": {"max_images": 4, "max_characters": 2}, "video": {"max_images": 3}}

    def reference_support(self, capability, model):
        return self.support.get(capability, {})

    def _note(self, capability, dst, prompt, kw):
        Stub.calls.append({"capability": capability, "prompt": prompt, **kw})
        dst.write_bytes(b"x")
        return base.Result(path=dst, model=kw.get("model") or f"stub-{capability}")

    def voice(self, text, dst, *, voice=None, **kw):
        return self._note("voice", dst, text, {"voice": voice, **kw})

    def image(self, prompt, dst, *, width, height, **kw):
        Stub.calls.append({"capability": "image", "prompt": prompt, **kw})
        Image.new("RGB", (width, height)).save(dst, format="PNG")
        return base.Result(path=dst, model=kw.get("model") or "stub-plain")

    def video(self, prompt, dst, *, duration, aspect, image=None, **kw):
        return self._note("video", dst, prompt, {"image": image, **kw})

    def music(self, prompt, dst, *, duration, **kw):
        return self._note("music", dst, prompt, kw)

    def sfx(self, prompt, dst, *, duration=1.0, **kw):
        return self._note("sfx", dst, prompt, kw)


base.register(Stub)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    monkeypatch.delenv("KALAINOVA_STORE_URI", raising=False)
    monkeypatch.delenv("KALAINOVA_STORE", raising=False)
    (tmp_path / "jobs").mkdir()
    (tmp_path / "streams").mkdir()
    Stub.calls = []
    return tmp_path


def picture(root, name, color=(10, 20, 30)):
    path = root / name
    Image.new("RGB", (32, 32), color).save(path, format="PNG")
    return path


CHARACTER = {
    "origin": {"invented": True, "real_person": False, "attested_by": "operator"},
    "person": {"fictional": True, "adult": True, "age": 31},
    "voice": {"provider": "stub", "voice_id": "voice-a", "model": "voice-model"},
    "persona": {"traits": ["dry"], "never_say": ["buy now"]},
}


def make_character(root, kit_id="lead", voice_id="voice-a", color=(10, 20, 30)):
    kits.new(root, kit_id)
    kits.merge(root, kit_id, {**CHARACTER, "voice": {**CHARACTER["voice"], "voice_id": voice_id}})
    kits.merge(root, kit_id, {"identity": {"description": "short dark hair"}})
    kits.add_file(
        root, kit_id, "identity", picture(root, f"{kit_id}-front.png", color), label="front"
    )
    kits.add_file(
        root, kit_id, "identity", picture(root, f"{kit_id}-side.png", (9, 9, 9)), label="side"
    )
    kits.add_file(root, kit_id, "looks.office", picture(root, f"{kit_id}-look.png", (7, 7, 7)))
    return kits.freeze(root, kit_id, by="operator")


def make_stream(root, stream_id="chan", *, roles=None, **over):
    data = {
        "schema_version": "0.1",
        "stream_id": stream_id,
        "strategy": "generated",
        "distribution_identity": f"{stream_id}-id",
        "rights": "owned",
        "media": ["video", "audio"],
        "max_per_day": 1,
        "cost_cap_per_job": 5,
        "kits": roles or {"lead": "lead@1"},
        "generators": {
            "image": {"provider": "stub", "model": "img-ref"},
            "video": {"provider": "stub", "model": "vid-ref"},
        },
        "accounts": {"youtube": "handle"},
        **over,
    }
    streams.create(root, data)
    return data


def packet(job_id, **beat):
    return {
        "schema_version": "0.1",
        "job_id": job_id,
        "hooks": ["one", "two", "three"],
        "chosen_hook": 0,
        "beats": [{"id": "b1", "role": "hook", "text": "line", "cast": ["lead"], **beat}],
    }


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


# ------------------------------------------------------------------ script
def test_script_cannot_invent_a_look_or_break_a_persona(root):
    make_character(root)
    make_stream(root)
    job = streams.request(root, "chan", "x")
    resolved, lock = consistency.for_job(job)
    good = packet(job.id, looks={"lead": "office"})
    assert consistency.script_problems(resolved, good, lock["cast"]) == []
    invented = packet(job.id, looks={"lead": "ballgown"})
    assert "no look named" in consistency.script_problems(resolved, invented, lock["cast"])[0]
    pushy = packet(job.id, text="Buy NOW, friends")
    assert "never say" in consistency.script_problems(resolved, pushy, lock["cast"])[0]
    two = {**good, "hooks": ["only one"]}
    assert any("three hooks" in p for p in consistency.script_problems(resolved, two, lock["cast"]))


def test_canon_reaches_the_writer_as_fiction(root):
    make_character(root)
    make_stream(root)
    streams.canon_add(root, "chan", "She left the city in spring", by="operator")
    resolved, lock = consistency.for_job(streams.request(root, "chan", "x"))
    context = json.loads(consistency.planner_context(resolved, lock["cast"]))
    assert context["canon_so_far_fiction"] == ["She left the city in spring"]
    assert context["cast"]["lead"]["persona"]["never_say"] == ["buy now"]


# ------------------------------------------------------------------- shots
def test_references_put_the_face_first_and_never_drop_it(root):
    make_character(root)
    make_stream(root)
    resolved, _ = consistency.for_job(streams.request(root, "chan", "x"))
    beat = {"id": "b1", "cast": ["lead"], "looks": {"lead": "office"}}
    refs = consistency.shot_refs(resolved, beat, 2)
    assert [r["label"] for r in refs] == ["lead, the character", "lead, wearing office"]
    with pytest.raises(ContractError, match="needs 2 references"):
        consistency.shot_refs(resolved, beat, 1, start=root / "frame.png")


def test_a_beat_without_people_says_so(root):
    make_character(root)
    make_stream(root)
    resolved, _ = consistency.for_job(streams.request(root, "chan", "x"))
    text = consistency.shot_prompt(resolved, {"id": "b1", "text": "a kettle"}, "soft light")
    assert text.endswith("No people in frame.")


@pytest.fixture
def fake_media(monkeypatch):
    """The asset stage without ffmpeg: file operations only, so this runs anywhere."""
    monkeypatch.setattr(media, "duration", lambda path: 2.0)
    monkeypatch.setattr(media, "summarize", lambda path: {})

    def run(args):
        open(args[-1], "wb").close()

    monkeypatch.setattr(media, "run", run)


def test_assets_send_the_lock_to_every_paid_call(root, fake_media):
    make_character(root)
    kits.new(root, "house")
    kits.merge(root, "house", {"style": {"text": "grainy film"}})
    kits.add_file(root, "house", "music.theme", _sound(root))
    kits.freeze(root, "house", by="operator")
    make_stream(root, roles={"lead": "lead@1", "house": "house@1"})
    job = streams.request(root, "chan", "x")
    script = packet(job.id, visual_kind="video")
    script["beats"].append({"id": "b2", "role": "body", "text": "line two", "cast": []})
    job.write("script_packet", script)

    manifest = assets.run(job)

    voice = [c for c in Stub.calls if c["capability"] == "voice"]
    assert {c["voice"] for c in voice} == {"voice-a"}
    assert {c["model"] for c in voice} == {"voice-model"}
    stills = [c for c in Stub.calls if c["capability"] == "image"]
    assert stills[0]["model"] == "img-ref"
    assert stills[0]["references"][0]["label"] == "lead, the character"
    assert "grainy film" in stills[0]["prompt"]
    assert "references" not in stills[1]  # nobody in frame, so the plain model takes it
    clip = next(c for c in Stub.calls if c["capability"] == "video")
    assert clip["model"] == "vid-ref"
    assert clip["references"][0]["label"] == "the start frame"
    assert clip["references"][1]["label"] == "lead, the character"
    assert not [c for c in Stub.calls if c["capability"] == "music"]  # the theme is reused
    by_id = {a["id"]: a for a in manifest["assets"]}
    assert by_id["music"]["provider"] == "kit"
    assert manifest["kit_lock_sha256"] == consistency.lock_sha256(job)

    resolved, lock = consistency.for_job(job)
    results = consistency.recorded_checks(resolved, lock, script, manifest)
    assert {c["status"] for c in results} == {"pass"}, results


def _sound(root):
    path = root / "theme.wav"
    path.write_bytes(b"RIFF")
    return path


def test_recorded_checks_catch_a_shot_made_without_references(root, fake_media):
    make_character(root)
    make_stream(root)
    job = streams.request(root, "chan", "x")
    script = packet(job.id)
    job.write("script_packet", script)
    manifest = assets.run(job)
    for asset in manifest["assets"]:
        asset.pop("provenance", None)
    resolved, lock = consistency.for_job(job)
    failed = {
        c["id"]
        for c in consistency.recorded_checks(resolved, lock, script, manifest)
        if c["status"] == "fail"
    }
    assert failed == {"consistency.voice", "consistency.references"}


def test_a_new_kit_version_does_not_move_a_locked_job(root):
    make_character(root)
    make_stream(root)
    job = streams.request(root, "chan", "x")
    kits.bump(root, "lead")
    kits.freeze(root, "lead", by="operator")
    resolved, lock = consistency.for_job(job)
    assert resolved.kits["lead"]["version"] == lock["kits"]["lead"]["version"] == 1


def test_a_changed_reference_forces_a_new_render(root):
    first = picture(root, "a.png", (1, 1, 1))
    key = {"references": [{"path": first, "label": "x"}]}
    before = router._request_key("image", "image", ("p", root / "o.png"), key)
    picture(root, "a.png", (2, 2, 2))
    after = router._request_key("image", "image", ("p", root / "o.png"), key)
    assert before != after


def test_judge_failures_block_and_uncertainty_warns():
    checks = consistency.judge_checks(
        {"same_character": False, "style_matches": None, "resembles_real_person": True}
    )
    status = {c["id"]: c["status"] for c in checks}
    assert status["consistency.character"] == "fail"
    assert status["consistency.style"] == "warn"
    assert status["consistency.real_person"] == "fail"


# ---------------------------------------------------------------- adapters
def test_fal_sends_references_in_each_model_shape(root, monkeypatch):
    sent = {}
    provider = remote.Fal()
    monkeypatch.setattr(
        provider,
        "_run",
        lambda model, payload, timeout=900: (
            sent.update(payload) or {"video": {"url": "u"}, "images": [{"url": "u"}]}
        ),
    )
    monkeypatch.setattr(remote, "_download", lambda url, dst: dst)
    face = {"path": picture(root, "f.png"), "label": "lead, the character", "group": "lead"}
    side = {"path": picture(root, "s.png"), "label": "lead, another angle", "group": "lead"}
    frame = {"path": picture(root, "k.png"), "label": "the start frame", "group": ""}

    provider.image(
        "shot",
        root / "o.png",
        width=9,
        height=16,
        model="google/nano-banana-2.1/edit",
        references=[face],
    )
    assert len(sent["image_urls"]) == 1
    assert "image 1 is lead, the character" in sent["prompt"]

    sent.clear()
    provider.video(
        "shot",
        root / "o.mp4",
        duration=4,
        aspect="9:16",
        model="alibaba/wan-3.0-prime/reference-to-video",
        references=[frame, face],
    )
    assert len(sent["reference_image_urls"]) == 2
    assert sent["audio"] is False
    assert sent["duration"] == 4  # the model takes any whole second, so a shot pays only for itself

    sent.clear()
    provider.video(
        "shot",
        root / "o.mp4",
        duration=4,
        aspect="9:16",
        model="fal-ai/kling-video/o3/pro/reference-to-video",
        references=[frame, face, side],
    )
    assert len(sent["elements"]) == 1
    assert len(sent["elements"][0]["reference_image_urls"]) == 1
    assert "@Element1 is lead" in sent["prompt"]
    assert "@Image1 is the start frame" in sent["prompt"]


def test_fal_refuses_references_for_an_unlisted_model(root):
    face = {"path": picture(root, "f.png"), "label": "x", "group": ""}
    with pytest.raises(ValueError, match="not listed"):
        remote.Fal()._with_references("image", "unknown/model", "p", [face])


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


# ------------------------------------------------------------------ gates
def _ready_to_publish(root, monkeypatch, **stream_over):
    make_character(root)
    make_stream(root, **stream_over)
    job = streams.request(root, "chan", "x")
    monkeypatch.setattr(pub, "_qa_bound", lambda job, final: {})
    monkeypatch.setattr(pub, "_not_placeholder", lambda job: None)
    final = job.artifact()
    final.write_bytes(b"video")
    job.write(
        "asset_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "assets": [{"id": "a", "kind": "video", "path": "final.mp4"}],
            "kit_lock_sha256": consistency.lock_sha256(job),
        },
    )
    return job


def test_approval_refuses_a_platform_this_stream_has_no_account_on(root, monkeypatch):
    job = _ready_to_publish(root, monkeypatch)
    with pytest.raises(ContractError, match="no account on tiktok"):
        pub.approve(job, "human", platforms=["tiktok"])
    assert pub.approve(job, "human", platforms=["youtube"])["reviewer"] == "human"


def test_approval_refuses_assets_made_under_another_lock(root, monkeypatch):
    job = _ready_to_publish(root, monkeypatch)
    manifest = job.read("asset_manifest")
    manifest["kit_lock_sha256"] = "0" * 64
    job.write("asset_manifest", manifest)
    with pytest.raises(ContractError, match="not made under this kit lock"):
        pub.approve(job, "human", platforms=["youtube"])


def test_restricted_tier_stream_never_posts(root, monkeypatch):
    job = _ready_to_publish(
        root, monkeypatch, accounts={}, restricted_tier={"enabled": True, "enabled_by": "human"}
    )
    with pytest.raises(ContractError, match="never posts it"):
        pub.publish(job, "youtube", dry_run=True)


def test_each_channel_uses_its_own_youtube_token(monkeypatch):
    assert pub._youtube_refresh_key("my-chan.id") == "YOUTUBE_REFRESH_TOKEN_MY_CHAN_ID"
    monkeypatch.setenv("YOUTUBE_ACCESS_TOKEN", "belongs-to-another-channel")
    monkeypatch.delenv("YOUTUBE_REFRESH_TOKEN_MY_CHAN", raising=False)
    with pytest.raises(ContractError, match="YOUTUBE_REFRESH_TOKEN_MY_CHAN"):
        pub._youtube_token("my-chan")


def test_daily_limit_counts_posts_across_the_stream(root, monkeypatch):
    job = _ready_to_publish(root, monkeypatch)
    today = pub._now()[:10]
    job.write(
        "publish_log",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "posts": [
                {
                    "platform": "youtube",
                    "identity": "chan-id",
                    "at": pub._now(),
                    "status": "posted",
                    "dry_run": False,
                    "title": "t",
                }
            ],
        },
    )
    assert streams.posted_on(root, "chan", today) == 1
    with pytest.raises(ContractError, match="daily limit"):
        pub._daily_limit(job, streams.load(root, "chan"))


def test_kit_rules_are_stdlib_only():
    assert kitrules.parse_pin("lead@3") == ("lead", 3)
    with pytest.raises(ValueError, match="must look like"):
        kitrules.parse_pin("lead")


def test_job_without_a_stream_is_unchanged(tmp_path):
    folder = tmp_path / "jobs" / "plain"
    folder.mkdir(parents=True)
    job = Job(folder)
    job.write(
        "job",
        {
            "schema_version": "0.1",
            "job_id": "plain",
            "strategy": "generated",
            "media": ["text"],
            "rights": "owned",
            "status": "draft",
        },
    )
    assert consistency.for_job(job) is None


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
