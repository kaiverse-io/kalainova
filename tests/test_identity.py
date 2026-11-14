"""Identity is measured face by face, by a configured command, and is a gap without one.

A stand-in face command reads the faces of each picture from a map, so these tests fix what the
engine does with a crowd, an empty frame, a faceless reference, and a command that fails. The
real command (providers/runners/face_run.py) needs OpenCV and is run by hand, not in CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from kalainova.bar import identity, identity_readings
from kalainova.jobfs import ContractError

FAKE_COMMAND = """
import argparse, json, pathlib
p = argparse.ArgumentParser()
p.add_argument("--map", required=True)
p.add_argument("--out", required=True)
p.add_argument("--fail", action="store_true")
p.add_argument("images", nargs="+")
a = p.parse_args()
if a.fail:
    raise SystemExit("the model would not load")
faces = json.loads(pathlib.Path(a.map).read_text())
def face(f):
    return {"box": [0, 0, f[1], f[1]], "score": 0.9, "embedding": f[0]}
out = {i: [face(f) for f in faces[pathlib.Path(i).name]] for i in a.images}
pathlib.Path(a.out).write_text(json.dumps(out))
"""

ALICE, BORIS, CLARA = [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.6, 0.0, 0.8]  # Alice.Clara = 0.6


@pytest.fixture
def faces(tmp_path, monkeypatch):
    """Pictures whose faces are given by name: {file name: [(embedding, size), ...]}."""
    script = tmp_path / "fake_faces.py"
    script.write_text(FAKE_COMMAND)
    table = tmp_path / "faces.json"

    def make(spec: dict[str, list], *, fail: bool = False) -> dict[str, Path]:
        table.write_text(json.dumps(spec))
        command = [sys.executable, str(script), "--map", str(table), *(["--fail"] if fail else [])]
        monkeypatch.setattr(
            identity, "_settings", lambda: {"face_command": command, "same_face_min": 0.5}
        )
        paths = {}
        for name in spec:
            paths[name] = tmp_path / name
            paths[name].write_bytes(b"picture")
        return paths

    return make


def test_with_no_face_command_identity_is_not_measured(tmp_path, monkeypatch):
    monkeypatch.setattr(identity, "_settings", lambda: {})
    picture = tmp_path / "still.png"
    picture.write_bytes(b"picture")
    assert not identity.configured()
    assert identity.face_reading(picture, [picture]) is None
    assert identity_readings(picture, [picture]) == []


def test_the_character_alone_reads_as_the_same_face(faces):
    p = faces({"still.png": [(ALICE, 100)], "ref.png": [(ALICE, 200)]})
    reading = identity.face_reading(p["still.png"], [p["ref.png"]])
    assert reading is not None and reading.ok and reading.value == pytest.approx(1.0)
    assert reading.id == "identity.face_match" and not reading.blocks


def test_someone_else_alone_does_not(faces):
    p = faces({"still.png": [(BORIS, 100)], "ref.png": [(ALICE, 200)]})
    reading = identity.face_reading(p["still.png"], [p["ref.png"]])
    assert reading is not None and not reading.ok and reading.value == pytest.approx(0.0)


def test_in_a_crowd_each_face_is_compared_and_the_character_is_found(faces):
    p = faces(
        {
            "crowd.png": [(BORIS, 300), (ALICE, 80), (CLARA, 120)],
            "ref.png": [(ALICE, 200)],
        }
    )
    found = identity.faces([p["crowd.png"], p["ref.png"]])
    result = identity.match(
        found[p["crowd.png"]], identity.reference_faces(found, [p["ref.png"]]), 0.5
    )
    assert result.faces == 3
    assert result.best == pytest.approx(1.0)
    assert result.matching == 2  # Alice, and Clara at 0.6 over a 0.5 limit
    assert "3 face(s)" in result.detail(0.5)


def test_a_picture_with_no_face_reads_zero_against_the_character(faces):
    p = faces({"empty.png": [], "ref.png": [(ALICE, 200)]})
    reading = identity.face_reading(p["empty.png"], [p["ref.png"]])
    assert reading is not None and not reading.ok and reading.value == 0.0
    assert identity.match([], [], 0.5).detail(0.5) == "no face found"


def test_the_largest_face_in_a_reference_is_the_character(faces):
    p = faces({"still.png": [(ALICE, 100)], "ref.png": [(BORIS, 20), (ALICE, 400)]})
    reading = identity.face_reading(p["still.png"], [p["ref.png"]])
    assert reading is not None and reading.ok


def test_references_with_no_face_are_refused(faces):
    p = faces({"still.png": [(ALICE, 100)], "ref.png": []})
    with pytest.raises(ContractError, match="no face found in any reference"):
        identity.face_reading(p["still.png"], [p["ref.png"]])


def test_a_command_that_fails_is_an_error_not_a_pass(faces):
    p = faces({"still.png": [(ALICE, 100)], "ref.png": [(ALICE, 200)]}, fail=True)
    with pytest.raises(ContractError, match="the face command failed"):
        identity.face_reading(p["still.png"], [p["ref.png"]])


def test_a_command_that_leaves_a_picture_out_is_an_error(faces, monkeypatch):
    p = faces({"still.png": [(ALICE, 100)], "ref.png": [(ALICE, 200)]})
    real = identity.opentools.run

    def drop_one(argv, **kw):
        ran = real(argv[:-1], **kw)  # the last picture is never passed on
        return ran

    monkeypatch.setattr(identity.opentools, "run", drop_one)
    with pytest.raises(ContractError, match="said nothing about"):
        identity.face_reading(p["still.png"], [p["ref.png"]])


# ---- a video, frame by frame -------------------------------------------------------------------
@pytest.fixture
def clip_limits(monkeypatch):
    monkeypatch.setattr(
        identity,
        "_settings",
        lambda: {"face_command": ["x"], "same_face_min": 0.57, "clip_median_min": 0.5,
                 "lost_below": 0.45},
    )  # fmt: skip


def test_a_clip_that_keeps_her_through_lighting_dips_holds(clip_limits):
    # her own clip under haze and pulsing light: every frame between 0.51 and 0.62
    r = identity.summarise_clip([0.55, 0.59, 0.51, 0.58, 0.62, 0.54], 1.0)
    assert r["ok"] and r["lost_at"] == [] and r["median_closest"] == pytest.approx(0.565)


def test_a_clip_that_drifts_away_from_her_does_not_hold_and_says_where(clip_limits):
    r = identity.summarise_clip([0.50, 0.28, 0.24, 0.13, 0.55, 0.17], 0.5)
    assert not r["ok"]
    assert r["lost_at"] == [(0.5, 1.5), (2.5, 2.5)]


def test_frames_with_no_face_are_their_own_stretch_and_do_not_count_as_lost(clip_limits):
    r = identity.summarise_clip([0.6, None, None, 0.58, None], 1.0)
    assert r["ok"] and r["lost_at"] == []
    assert r["no_face_at"] == [(1.0, 2.0), (4.0, 4.0)]


def test_a_clip_with_no_face_anywhere_does_not_hold(clip_limits):
    assert not identity.summarise_clip([None, None], 1.0)["ok"]


def test_a_video_is_read_by_its_frames_and_a_picture_by_its_faces(
    clip_limits, tmp_path, monkeypatch
):
    seen = {}
    monkeypatch.setattr(
        identity, "clip_report",
        lambda clip, refs: seen.setdefault("clip", identity.summarise_clip([0.6, 0.6, 0.2], 1.0)),
    )  # fmt: skip
    line = identity.kit_line(tmp_path / "set.mp4", [tmp_path / "ref.png"], "lead@1")
    assert (
        "clip" in seen and "the character holds" in line and "lost (below 0.45) at 0:02.0" in line
    )


# ---- the animatic's character stills ------------------------------------------------------------
def test_each_animatic_still_is_checked_against_the_characters_its_shot_names(faces, tmp_path):
    from types import SimpleNamespace

    p = faces(
        {
            "b1.still.png": [(BORIS, 300), (ALICE, 90)],
            "b2.still.png": [(BORIS, 300)],
            "b3.still.png": [],
            "alice.png": [(ALICE, 200)],
        }
    )
    work = tmp_path
    (work / "beats").mkdir()
    for name in ("b1", "b2", "b3"):
        p[f"{name}.still.png"].rename(work / "beats" / f"{name}.still.png")
    resolved = SimpleNamespace(root=tmp_path, characters={"lead": {"identity": {"refs": ["a"]}}})
    import kalainova.kits as kits

    real_blob = kits.blob_path
    kits.blob_path = lambda root, entry: p["alice.png"]
    try:
        beats = [{"id": "b1", "cast": ["lead"]}, {"id": "b2", "cast": ["lead"]},
                 {"id": "b3", "cast": ["lead"]}, {"id": "b4"}]  # fmt: skip
        rows = [{"beat_id": b, "still": f"beats/{b}.still.png"} for b in ("b1", "b2", "b3", "b4")]
        results = identity.check_cast(work, resolved, beats, rows)
    finally:
        kits.blob_path = real_blob

    assert [(r["beat_id"], r["found"]) for r in results] == [
        ("b1", True),
        ("b2", False),
        ("b3", False),
    ]
    lines = identity.cast_lines(work)
    assert "face check on b1, lead: found" in lines[0]
    assert "NOT found" in lines[1] and "no face found" in lines[2]


def test_with_no_face_check_the_animatic_records_nothing_and_clears_an_old_result(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(identity, "_settings", lambda: {})
    (tmp_path / identity.CAST_FILE).write_text("[]")
    assert identity.check_cast(tmp_path, object(), [], []) == []
    assert not (tmp_path / identity.CAST_FILE).exists()
    assert identity.cast_lines(tmp_path) == []
