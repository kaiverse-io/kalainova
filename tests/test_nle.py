"""A cut an editor can open: the shapes other tools read, with times that do not drift."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from fractions import Fraction

import pytest
from fakes import make_job

from kalainova import nle
from kalainova.jobfs import ContractError


def _job(tmp_path, monkeypatch, *, fps=24.0, music=True):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path)
    job.write(
        "asset_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "assets": [
                {"id": "a", "kind": "video", "path": "beats/a.mp4"},
                {"id": "b", "kind": "video", "path": "beats/b & c.mp4"},
                {"id": "voice", "kind": "audio", "path": "voice.wav"},
                {"id": "music", "kind": "audio", "path": "music.wav"},
            ],
        },
    )
    job.write(
        "edit_manifest",
        {
            "schema_version": "0.1",
            "job_id": job.id,
            "runtime": "ffmpeg",
            "duration_sec": 9.0,
            "profile": {"aspect": "16:9", "width": 1920, "height": 1080, "fps": fps},
            "cuts": [
                {
                    "id": "cut-1",
                    "source": "a",
                    "in_sec": 0,
                    "out_sec": 4,
                    "role": "hook",
                    "start_sec": 0.0,
                },
                {
                    "id": "cut-2",
                    "source": "b",
                    "in_sec": 2,
                    "out_sec": 7,
                    "role": "body",
                    "start_sec": 4.0,
                },
            ],
            "audio": {"voice_asset_id": "voice", **({"music_asset_id": "music"} if music else {})},
        },
    )
    return job


@pytest.mark.parametrize(
    ("fps", "rate"),
    [
        (24.0, Fraction(24)),
        (23.976, Fraction(24000, 1001)),
        (29.97, Fraction(30000, 1001)),
        (25.0, Fraction(25)),
    ],
)
def test_a_frame_rate_is_exact_because_a_rounded_one_drifts(fps, rate):
    assert nle.rate_of(fps) == rate


def test_fcpxml_is_well_formed_and_places_each_clip_where_the_cut_does(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    root = ET.fromstring(nle.fcpxml(nle.build(job)))
    assert root.tag == "fcpxml" and root.get("version") == "1.11"
    clips = root.findall(".//spine/asset-clip")
    assert [c.get("offset") for c in clips] == ["0s", "4/1s"]
    assert clips[1].get("start") == "2/1s", "where it starts in its source"
    assert clips[1].get("duration") == "5/1s"
    fmt = root.find(".//format")
    assert fmt.get("frameDuration") == "1/24s" and fmt.get("width") == "1920"


def test_fcpxml_points_at_the_real_files_even_with_awkward_names(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    root = ET.fromstring(nle.fcpxml(nle.build(job)))
    sources = [m.get("src") for m in root.findall(".//media-rep")]
    assert all(s.startswith("file:///") for s in sources)
    assert any("b%20%26%20c.mp4" in s for s in sources)


def test_voice_and_music_connect_below_the_picture(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    root = ET.fromstring(nle.fcpxml(nle.build(job)))
    first = root.find(".//spine/asset-clip")
    connected = first.findall("asset-clip")
    assert [c.get("name") for c in connected] == ["voice", "music"]
    assert [c.get("lane") for c in connected] == ["-1", "-2"]


def test_every_clip_points_at_an_asset_that_exists_and_only_sound_lacks_a_picture(
    tmp_path, monkeypatch
):
    job = _job(tmp_path, monkeypatch)
    root = ET.fromstring(nle.fcpxml(nle.build(job)))
    assets = {asset.get("id"): asset for asset in root.findall(".//resources/asset")}
    clips = root.findall(".//spine/asset-clip")
    connected = clips[0].findall("asset-clip")
    assert all(clip.get("ref") in assets for clip in [*clips, *connected])
    assert all(assets[clip.get("ref")].get("hasVideo") == "1" for clip in clips)
    assert all(assets[clip.get("ref")].get("hasVideo") == "0" for clip in connected)
    assert "r1" not in assets, "the format holds that id"


def test_sound_connects_to_the_first_clip_alone(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    clips = ET.fromstring(nle.fcpxml(nle.build(job))).findall(".//spine/asset-clip")
    assert clips[0].findall("asset-clip")
    assert not any(clip.findall("asset-clip") for clip in clips[1:])


def test_otio_holds_a_track_for_picture_and_for_each_sound(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    document = json.loads(nle.otio(nle.build(job)))
    assert document["OTIO_SCHEMA"] == "Timeline.1"
    tracks = document["tracks"]["children"]
    assert [t["kind"] for t in tracks] == ["Video", "Audio", "Audio"]
    second = tracks[0]["children"][1]
    assert second["source_range"]["start_time"]["value"] == 48.0
    assert second["source_range"]["duration"]["value"] == 120.0
    assert second["media_reference"]["target_url"].startswith("file:///")


def test_an_edl_lists_each_event_with_source_and_record_times(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    text = nle.edl(nle.build(job))
    assert text.startswith(f"TITLE: {job.id}\nFCM: NON-DROP FRAME")
    assert "002  AX       V     C        00:00:02:00 00:00:07:00 00:00:04:00 00:00:09:00" in text
    assert "* FRAME RATE: 24.000 FPS" in text
    assert "* FROM CLIP NAME: a.mp4" in text


@pytest.mark.parametrize("fps", [24.0, 25.0, 30.0, 23.976, 29.97])
def test_the_reference_reader_accepts_an_edl_at_odd_cut_points(tmp_path, monkeypatch, fps):
    otio = pytest.importorskip("opentimelineio")
    job = _job(tmp_path, monkeypatch, fps=fps)
    em = job.read("edit_manifest")
    em["cuts"][1]["start_sec"] = 3.57
    em["cuts"][1]["in_sec"] = 2.33
    job.write("edit_manifest", em)
    timeline = otio.adapters.read_from_string(
        nle.edl(nle.build(job)), "cmx_3600", rate=float(nle.rate_of(fps))
    )
    assert len(list(timeline.find_clips())) == 2


def test_the_otio_export_loads_and_carries_each_sources_length(tmp_path, monkeypatch):
    otio = pytest.importorskip("opentimelineio")
    job = _job(tmp_path, monkeypatch)
    monkeypatch.setattr(nle, "_length", lambda path: 12.0)
    path = tmp_path / "t.otio"
    path.write_text(nle.otio(nle.build(job)))
    timeline = otio.adapters.read_from_file(str(path))
    clip = next(iter(timeline.find_clips()))
    assert clip.media_reference.available_range.duration.value == 288.0


def test_times_stay_on_whole_frames_at_ntsc_rates(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch, fps=23.976)
    root = ET.fromstring(nle.fcpxml(nle.build(job)))
    offset = Fraction(root.findall(".//spine/asset-clip")[1].get("offset")[:-1])
    assert (offset * Fraction(24000, 1001)).denominator == 1


@pytest.mark.parametrize("to", nle.FORMATS)
def test_an_export_lands_next_to_the_rendered_file(tmp_path, monkeypatch, to):
    job = _job(tmp_path, monkeypatch)
    dst = nle.export(job, to)
    assert dst == job.work / f"timeline.{to}" and dst.stat().st_size > 0


def test_a_format_nobody_knows_is_refused(tmp_path, monkeypatch):
    with pytest.raises(ContractError, match="no export"):
        nle.export(_job(tmp_path, monkeypatch), "aaf")


def test_a_piece_with_no_cuts_has_nothing_to_export(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    em = job.read("edit_manifest")
    em["cuts"] = []
    job.write("edit_manifest", em)
    with pytest.raises(ContractError, match="no cuts"):
        nle.build(job)


def test_the_fcpxml_export_loads_with_the_fcpx_adapter(tmp_path, monkeypatch):
    otio = pytest.importorskip("opentimelineio")
    job = _job(tmp_path, monkeypatch)
    timeline = otio.adapters.read_from_string(nle.fcpxml(nle.build(job)), "fcpx_xml")
    assert len(list(timeline.find_clips())) >= 2
