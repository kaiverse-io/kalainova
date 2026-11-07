"""Kits and streams at work: a locked job holds what its kits promise, from script to publish."""

from __future__ import annotations

import json

import pytest
from kit_fixtures import Stub, make_character, make_stream, packet, picture

from kalainova import assets, consistency, kitchecks, kits, media, streams
from kalainova import publish as pub
from kalainova.jobfs import ContractError, Job
from kalainova.providers import fal, router


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
    monkeypatch.setattr(media, "has_picture", lambda path: True)
    monkeypatch.setattr(media, "has_sound", lambda path: True)

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
    results = kitchecks.recorded_checks(resolved, lock, script, manifest)
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
        for c in kitchecks.recorded_checks(resolved, lock, script, manifest)
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
    checks = kitchecks.judge_checks(
        {"same_character": False, "style_matches": None, "resembles_real_person": True}
    )
    status = {c["id"]: c["status"] for c in checks}
    assert status["consistency.character"] == "fail"
    assert status["consistency.style"] == "warn"
    assert status["consistency.real_person"] == "fail"


# ---------------------------------------------------------------- adapters
def test_fal_sends_references_in_each_model_shape(root, monkeypatch):
    sent = {}
    provider = fal.Fal()
    monkeypatch.setattr(
        provider,
        "_run",
        lambda model, payload, timeout=900: (
            sent.update(payload) or {"video": {"url": "u"}, "images": [{"url": "u"}]}
        ),
    )
    monkeypatch.setattr(fal, "_download", lambda url, dst: dst)
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
        fal.Fal()._with_references("image", "unknown/model", "p", [face])


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
