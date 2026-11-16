"""What a take's record can and cannot claim: unread is not a pass, passing is not a ranking,
a verdict names the bytes it judged, and a bench says what each model was given."""

from __future__ import annotations

from fakes import make_job, needs_ffmpeg

from kalainova import media, qachecks, shotmake, takes, verdicts


def _take(job, n, sha, *, ok=True, motion=0.3, **extra):
    return {
        "n": n,
        "seed": n + 1,
        "file": f"takes/b1/take-{n:02d}.mp4",
        "sha256": sha,
        "ok": ok,
        "readings": {"score": motion, "shot_motion": motion},
        **extra,
    }


def test_a_clip_that_cannot_be_decoded_is_unmeasurable_not_a_pass(tmp_path):
    junk = tmp_path / "broken.mp4"
    junk.write_bytes(b"not a video")
    readings, ok = takes.assess_clip(junk)
    assert ok is False
    assert readings["unmeasurable"] == "the clip could not be decoded"


@needs_ffmpeg
def test_a_clip_too_short_to_read_is_unmeasurable_not_a_pass(tmp_path):
    clip = tmp_path / "blink.mp4"
    media.run(
        ["-f", "lavfi", "-i", "testsrc2=s=160x90:d=0.05:r=24", "-pix_fmt", "yuv420p", str(clip)]
    )
    readings, ok = takes.assess_clip(clip)
    assert ok is False
    assert readings["unmeasurable"] == "too short to read its motion"


def test_passing_is_a_floor_so_more_motion_does_not_win(tmp_path):
    job = make_job(tmp_path)
    takes.record(job, "b1", _take(job, 0, "a", motion=0.2))
    entry = takes.record(job, "b1", _take(job, 1, "b", motion=0.9))
    assert entry["chosen"] == 0, "both pass; the readings do not rank them"


def test_with_none_passing_the_one_closest_to_passing_is_kept(tmp_path):
    job = make_job(tmp_path)
    takes.record(job, "b1", _take(job, 0, "a", ok=False, motion=0.01))
    entry = takes.record(job, "b1", _take(job, 1, "b", ok=False, motion=0.05))
    assert entry["chosen"] == 1


def test_an_unmeasurable_take_breaks_its_promise_and_says_it_could_not_be_read(tmp_path):
    job = make_job(tmp_path)
    take = _take(job, 0, "a", ok=False)
    take["readings"] = {"score": 0.0, "unmeasurable": "the clip could not be decoded"}
    broken = shotmake.motion_break(job, "b1", take, allow_stills=False)
    assert broken and "could not be measured" in broken["reason"]


def test_a_verdict_names_the_bytes_and_a_forced_rerun_cannot_inherit_it(tmp_path):
    job = make_job(tmp_path)
    takes.record(job, "b1", _take(job, 0, "first-bytes", motion=0.3))
    entry = verdicts.record(job, "reject", reviewer="Ana", shot="b1", take=0)
    assert entry["take_sha256"] == "first-bytes"
    rows = verdicts.samples(job.folder.parent)
    assert any(r["reading"] == "shot.shot_motion" and r["value"] == 0.3 for r in rows)

    takes.forget(job)  # what `assets --force` does: the numbering starts again
    takes.record(job, "b1", _take(job, 0, "new-bytes", motion=0.9))
    rows = verdicts.samples(job.folder.parent)
    assert not any(r["reading"] == "shot.shot_motion" for r in rows), (
        "the verdict judged other bytes, so it is not paired with the new take 0"
    )


def test_a_verdict_without_a_take_names_the_chosen_takes_bytes(tmp_path):
    job = make_job(tmp_path)
    takes.record(job, "b1", _take(job, 0, "chosen-bytes"))
    assert (
        verdicts.record(job, "accept", reviewer="Ana", shot="b1")["take_sha256"] == "chosen-bytes"
    )


def test_the_judges_time_and_region_reach_the_findings():
    found = qachecks.findings_from_judge(
        "p1",
        {
            "shots": [
                {"id": "b1", "warping": True, "time": 2.4, "region": "left hand", "note": "melts"},
                {"id": "b2", "flicker": True, "timestamp": "1.0-1.6", "note": "pulses"},
            ]
        },
    )
    assert found
    first, second = found["shots"]
    assert (first["time"], first["region"]) == (2.4, "left hand")
    assert second["time"] == "1.0-1.6" and "region" not in second


@needs_ffmpeg
def test_every_take_records_the_size_its_model_made(tmp_path):
    clip = tmp_path / "clip.mp4"
    media.run(
        ["-f", "lavfi", "-i", "testsrc2=s=320x180:d=2:r=24", "-pix_fmt", "yuv420p", str(clip)]
    )
    readings, _ = takes.assess_clip(clip)
    assert (readings["width"], readings["height"]) == (320, 180)


def test_a_character_take_under_the_source_size_does_not_pass(tmp_path, monkeypatch):
    made = {"score": 0.3, "shot_motion": 0.3, "width": 1280, "height": 720}
    monkeypatch.setattr(takes, "assess_clip", lambda path: (dict(made), True))
    readings, ok = takes.held_to(1080)(tmp_path / "clip.mp4")
    assert ok is False
    assert readings["below_source_floor"] == "1280x720, under 1080px a side"
    made.update(width=1080, height=1920)
    assert takes.held_to(1080)(tmp_path / "clip.mp4")[1] is True


def test_a_small_take_breaks_the_promise_even_where_stills_are_allowed(tmp_path):
    job = make_job(tmp_path)
    take = _take(job, 0, "a", ok=False)
    take["readings"]["below_source_floor"] = "1280x720, under 1080px a side"
    takes.record(job, "b1", take)
    broken = shotmake.motion_break(job, "b1", take, allow_stills=True)
    assert broken["reason"].startswith(shotmake.SOURCE_REASON)
    assert "1280x720" in broken["reason"]
    takes.choose(job, "b1", 0)  # a person keeps it anyway
    assert shotmake.motion_break(job, "b1", take, allow_stills=True) is None
