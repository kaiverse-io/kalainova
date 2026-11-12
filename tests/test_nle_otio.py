"""The timeline seam: in-house by default, `otioconvert` by config, called as a command."""

from __future__ import annotations

import json
import shutil
import stat
from pathlib import Path

import pytest
from test_nle import _job

from kalainova import config, nle, nle_otio, opentools

VERSION = 'if [ "$1" = "--version" ]; then echo "OpenTimelineIO version: {v}"; exit 0; fi\n'
CLIP = '<asset-clip name="c" ref="r2" offset="0s" duration="1s"/>'
FCPXML = f'<fcpxml version="1.8"><resources/>{CLIP}</fcpxml>'
EDL = "TITLE: t\n\n001  AX V C 00:00:00:00 00:00:01:00 00:00:00:00 00:00:01:00\n"
OTIO = {
    "OTIO_SCHEMA": "Timeline.1",
    "name": "t",
    "tracks": {
        "children": [
            {
                "name": "V",
                "kind": "Video",
                "children": [
                    {
                        "OTIO_SCHEMA": "Gap.1",
                        "source_range": {"duration": {"value": 24, "rate": 24}},
                    },
                    {
                        "OTIO_SCHEMA": "Clip.1",
                        "name": "c",
                        "source_range": {
                            "start_time": {"value": 48, "rate": 24},
                            "duration": {"value": 24, "rate": 24},
                        },
                        "media_reference": {"target_url": "file:///x.mp4"},
                    },
                ],
            }
        ]
    },
}


def _fake(tmp_path: Path, body: str, version: str = "0.18.1") -> str:
    """A stand-in `otioconvert`: $1 -i, $2 input, $3 -o, $4 output, $5 -O or -I, $6 adapter."""
    path = tmp_path / "bin" / "fake_otioconvert"
    path.parent.mkdir(exist_ok=True)
    path.write_text("#!/bin/sh\n" + VERSION.format(v=version) + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def _writes(text: str) -> str:
    return f"cat > \"$4\" <<'EOF'\n{text}\nEOF\n"


def _select(monkeypatch, command: str, **more) -> None:
    entry = {"use": "otio", "command": command, **more}
    monkeypatch.setattr(config, "studio", lambda: {"adapters": {"timeline": entry}})


def test_the_default_is_the_in_house_writer(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "studio", lambda: {})
    job = _job(tmp_path, monkeypatch)
    nle.export(job, "fcpxml")
    assert 'version="1.11"' in (job.work / "timeline.fcpxml").read_text()
    assert not (job.work / opentools.LOG_NAME).exists()


def test_fcpxml_and_edl_come_from_the_command(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    _select(monkeypatch, _fake(tmp_path, _writes(FCPXML)))
    assert nle.export(job, "fcpxml").read_text().strip() == FCPXML
    _select(monkeypatch, _fake(tmp_path, _writes(EDL)))
    assert nle.export(job, "edl").read_text() == EDL + "\n"
    runs = json.loads((job.work / opentools.LOG_NAME).read_text())
    assert [r["options"]["adapter"] for r in runs] == ["fcpx_xml", "cmx_3600"]
    assert runs[0]["argv"][1:] == [
        "-i",
        str(job.work / "timeline.otio"),
        "-o",
        str(job.work / "timeline.fcpxml"),
        "-O",
        "fcpx_xml",
    ]
    assert len(runs[0]["inputs"]["timeline.otio"]) == 64 and "timeline.fcpxml" in runs[0]["outputs"]


def test_otio_needs_no_conversion(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    _select(monkeypatch, "no-such-otioconvert")  # never called
    assert nle.export(job, "otio").read_text().startswith("{")


def test_a_missing_tool_names_itself_and_the_way_out(tmp_path, monkeypatch):
    _select(monkeypatch, "no-such-otioconvert")
    with pytest.raises(opentools.ToolMissingError, match="no-such-otioconvert.*inhouse"):
        nle.export(_job(tmp_path, monkeypatch), "edl")


def test_another_version_is_not_taken_for_the_one_expected(tmp_path, monkeypatch):
    _select(monkeypatch, _fake(tmp_path, _writes(EDL), version="0.17.0"))
    with pytest.raises(opentools.ToolMissingError, match=r"0\.17\.0.*expects 0\.18"):
        nle.export(_job(tmp_path, monkeypatch), "edl")


def test_a_tool_failure_carries_what_it_printed(tmp_path, monkeypatch):
    _select(monkeypatch, _fake(tmp_path, "echo 'adapter exploded' >&2\nexit 3\n"))
    job = _job(tmp_path, monkeypatch)
    with pytest.raises(opentools.ToolFailedError, match="adapter exploded"):
        nle.export(job, "edl")
    assert json.loads((job.work / opentools.LOG_NAME).read_text())[0]["returncode"] == 3


def test_a_timeout_cancels_the_tool(tmp_path, monkeypatch):
    marker = tmp_path / "survived"
    _select(monkeypatch, _fake(tmp_path, f"sleep 5\ntouch {marker}\n"), timeout_sec=0.5)
    with pytest.raises(opentools.ToolTimeoutError, match="cancelled"):
        nle.export(_job(tmp_path, monkeypatch), "edl")
    assert not marker.exists()


@pytest.mark.parametrize(
    ("body", "to", "message"),
    [
        ("exit 0\n", "edl", "wrote nothing"),
        (_writes("not xml"), "fcpxml", "not a readable fcpxml"),
        (_writes("<fcpxml/>"), "fcpxml", "not a readable fcpxml"),
        (_writes("a list of words"), "edl", "not a readable edl"),
    ],
)
def test_output_that_is_not_the_format_is_a_bad_output(tmp_path, monkeypatch, body, to, message):
    _select(monkeypatch, _fake(tmp_path, body))
    with pytest.raises(opentools.BadOutputError, match=message):
        nle.export(_job(tmp_path, monkeypatch), to)


def test_a_stale_output_does_not_pass_for_a_new_one(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    (job.work / "timeline.edl").write_text(EDL)
    _select(monkeypatch, _fake(tmp_path, "exit 0\n"))
    with pytest.raises(opentools.BadOutputError, match="wrote nothing"):
        nle.export(job, "edl")


def test_a_symlink_in_the_job_folder_is_not_written_through(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    target = tmp_path / "elsewhere.edl"
    (job.work / "timeline.edl").symlink_to(target)
    _select(monkeypatch, _fake(tmp_path, _writes(EDL)))
    with pytest.raises(opentools.BadInputError, match="symlink"):
        nle.export(job, "edl")
    assert not target.exists()


def test_reading_back_summarises_the_clips(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    source = tmp_path / "edited.fcpxml"
    source.write_text(FCPXML)
    _select(monkeypatch, _fake(tmp_path, _writes(json.dumps(OTIO))))
    out = nle.read_back(job, source)
    assert out == job.work / "imports" / "edited.fcpxml.json"
    got = json.loads(out.read_text())
    assert got["clips"] == [
        {
            "track": "V",
            "kind": "Video",
            "name": "c",
            "target": "file:///x.mp4",
            "start_sec": 1.0,
            "duration_sec": 1.0,
            "source_in_sec": 2.0,
        }
    ]
    assert got["source"]["file"] == "edited.fcpxml" and len(got["source"]["sha256"]) == 64


@pytest.mark.parametrize(
    ("name", "content", "match"),
    [
        ("missing.edl", None, "not a file"),
        ("empty.edl", "", "is empty"),
        ("notes.txt", "x", "not a timeline format"),
    ],
)
def test_a_bad_input_is_refused_before_the_tool_runs(tmp_path, monkeypatch, name, content, match):
    source = tmp_path / name
    if content is not None:
        source.write_text(content)
    _select(monkeypatch, "no-such-otioconvert")  # a bad input outranks a missing tool
    with pytest.raises(opentools.BadInputError, match=match):
        nle.read_back(_job(tmp_path, monkeypatch), source)


def test_a_converted_file_that_is_not_a_timeline_is_a_bad_output(tmp_path, monkeypatch):
    source = tmp_path / "edited.edl"
    source.write_text(EDL)
    _select(monkeypatch, _fake(tmp_path, _writes("[1, 2]")))
    with pytest.raises(opentools.BadOutputError, match="not an OTIO timeline"):
        nle.read_back(_job(tmp_path, monkeypatch), source)


def test_an_unknown_adapter_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "studio", lambda: {"adapters": {"timeline": {"use": "aaf"}}})
    with pytest.raises(nle.ContractError, match="unknown adapter"):
        nle.export(_job(tmp_path, monkeypatch), "edl")


# The real command. Skipped where `otioconvert` is not installed at the version expected.


def _real() -> bool:
    exe = shutil.which(nle_otio.COMMAND)
    if exe is None:
        return False
    try:
        opentools.require_version(
            exe, nle_otio.VERSION_PATTERN, nle_otio.EXPECTS, program=nle_otio.PROGRAM
        )
    except opentools.ToolError:
        return False
    return True


needs_otio = pytest.mark.skipif(not _real(), reason="otioconvert 0.18 is not installed")


@needs_otio
@pytest.mark.parametrize("to", ["fcpxml", "edl"])
def test_the_real_command_writes_and_reads_back_the_cut(tmp_path, monkeypatch, to):
    job = _job(tmp_path, monkeypatch)
    monkeypatch.setattr(nle, "_length", lambda path: 12.0)  # no media on disk: say how long it is
    _select(monkeypatch, nle_otio.COMMAND)
    written = nle.export(job, to)
    summary = json.loads(nle.read_back(job, written).read_text())
    picture = [
        c for c in summary["clips"] if c["kind"] != "Audio" and c["track"] not in ("-1", "-2")
    ]
    assert [
        (c["name"], c["start_sec"], c["duration_sec"], c["source_in_sec"]) for c in picture
    ] == [
        ("cut-1", 0.0, 4.0, 0.0),
        ("cut-2", 4.0, 5.0, 2.0),
    ]


@needs_otio
def test_the_real_command_reads_back_the_in_house_fcpxml(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "studio", lambda: {})
    written = nle.export(job, "fcpxml")
    _select(monkeypatch, nle_otio.COMMAND)
    summary = json.loads(nle.read_back(job, written).read_text())
    assert summary["picture_clips"] >= 2


@needs_otio
def test_the_real_command_refuses_a_file_that_is_not_a_timeline(tmp_path, monkeypatch):
    bad = tmp_path / "broken.edl"
    bad.write_text("this is not an edit decision list\n")
    _select(monkeypatch, nle_otio.COMMAND)
    with pytest.raises((opentools.ToolFailedError, opentools.BadOutputError)):
        nle.read_back(_job(tmp_path, monkeypatch), bad)


def test_a_path_outside_the_job_or_with_dots_is_refused(tmp_path):
    root = tmp_path / "job"
    root.mkdir()
    with pytest.raises(opentools.BadInputError, match="outside"):
        opentools.inside(tmp_path / "other.edl", root)
    with pytest.raises(opentools.BadInputError, match=r"\.\."):
        opentools.inside(root / ".." / "other.edl", root)
    assert opentools.inside(root / "a" / "b.edl", root) == root.resolve() / "a" / "b.edl"
