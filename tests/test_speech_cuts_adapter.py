"""The speech-cuts seam: in-house by default, `auto-editor` by config, called as a command."""

from __future__ import annotations

import json
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
from fakes import make_job, needs_ffmpeg

from kalainova import config, opentools
from kalainova.editor import auto_editor, speech

V3 = {
    "version": "3",
    "timebase": "30/1",
    "v": [[{"offset": 15, "dur": 30, "start": 0}, {"offset": 90, "dur": 45, "start": 30}]],
    "a": [[]],
}


def _fake(tmp_path: Path, body: str, version: str = "29.3.1") -> str:
    """A stand-in `auto-editor`: $1 source, $2 --export, $3 v3, $4 -o, $5 output."""
    path = tmp_path / "bin" / "fake_auto_editor"
    path.parent.mkdir(exist_ok=True)
    path.write_text(
        f'#!/bin/sh\nif [ "$1" = "--version" ]; then echo {version}; exit 0; fi\n{body}'
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def _writes(doc: object) -> str:
    return f"cat > \"$5\" <<'EOF'\n{json.dumps(doc) if not isinstance(doc, str) else doc}\nEOF\n"


def _select(monkeypatch, command: str, **more) -> None:
    entry = {"use": "auto_editor", "command": command, **more}
    monkeypatch.setattr(config, "studio", lambda: {"adapters": {"speech_cuts": entry}})
    monkeypatch.setattr(speech, "transcript", lambda job, path: None)


def _take(tmp_path, monkeypatch):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    job = make_job(tmp_path)
    take = job.work / "take.wav"
    take.write_bytes(b"RIFF....WAVE")  # the fake never reads it
    return job, take


def test_the_default_does_not_call_the_tool(tmp_path, monkeypatch):
    job, take = _take(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "studio", lambda: {})
    monkeypatch.setattr(speech, "transcript", lambda job, path: None)
    monkeypatch.setattr(speech.media, "silencedetect", lambda *a, **k: [])
    spans, words = speech.keep_spans(job, take, 10.0)
    assert spans == [(0.0, 10.0)] and words == []
    assert not (job.work / opentools.LOG_NAME).exists()


def test_spans_come_from_the_command_in_seconds(tmp_path, monkeypatch):
    job, take = _take(tmp_path, monkeypatch)
    _select(monkeypatch, _fake(tmp_path, _writes(V3)), margin="0.3s")
    spans, words = speech.keep_spans(job, take, 5.0)
    assert spans == [(0.5, 1.5), (3.0, 4.5)] and words == []
    run = json.loads((job.work / opentools.LOG_NAME).read_text())[0]
    assert run["options"]["margin"] == "0.3s" and run["options"]["version"] == "29.3.1"
    assert run["argv"][2:4] == ["--export", "v3"] and "--margin" in run["argv"]
    assert "take.wav" in run["inputs"] and len(run["outputs"]) == 1


def test_words_are_laid_over_the_kept_spans(tmp_path, monkeypatch):
    job, take = _take(tmp_path, monkeypatch)
    _select(monkeypatch, _fake(tmp_path, _writes(V3)))
    said = [
        {"text": "hi", "start_sec": 0.6, "end_sec": 0.9},
        {"text": "x", "start_sec": 2, "end_sec": 2.4},
    ]
    monkeypatch.setattr(speech, "transcript", lambda job, path: said)
    _, words = speech.keep_spans(job, take, 5.0)
    assert [(w["text"], w["start_sec"]) for w in words] == [("hi", 0.1)]


def test_the_same_bytes_and_options_are_analysed_once(tmp_path, monkeypatch):
    job, take = _take(tmp_path, monkeypatch)
    _select(monkeypatch, _fake(tmp_path, _writes(V3)))
    speech.keep_spans(job, take, 5.0)
    speech.keep_spans(job, take, 5.0)
    assert len(json.loads((job.work / opentools.LOG_NAME).read_text())) == 1


def test_a_missing_tool_names_itself_and_the_way_out(tmp_path, monkeypatch):
    job, take = _take(tmp_path, monkeypatch)
    _select(monkeypatch, "no-such-auto-editor")
    with pytest.raises(opentools.ToolMissingError, match="no-such-auto-editor.*inhouse"):
        speech.keep_spans(job, take, 5.0)


def test_another_major_version_is_refused(tmp_path, monkeypatch):
    job, take = _take(tmp_path, monkeypatch)
    _select(monkeypatch, _fake(tmp_path, _writes(V3), version="28.1.0"))
    with pytest.raises(opentools.ToolMissingError, match=r"28\.1\.0.*expects 29"):
        speech.keep_spans(job, take, 5.0)


@pytest.mark.parametrize("name", ["missing.wav", "empty.wav"])
def test_a_bad_input_is_refused_before_the_tool_runs(tmp_path, monkeypatch, name):
    job, _ = _take(tmp_path, monkeypatch)
    _select(monkeypatch, "no-such-auto-editor")
    bad = job.work / name
    if name == "empty.wav":
        bad.write_bytes(b"")
    with pytest.raises(opentools.BadInputError, match="not a media file"):
        speech.keep_spans(job, bad, 5.0)


def test_a_file_outside_the_job_is_refused(tmp_path, monkeypatch):
    job, _ = _take(tmp_path, monkeypatch)
    _select(monkeypatch, "no-such-auto-editor")
    outside = tmp_path / "elsewhere.wav"
    outside.write_bytes(b"RIFF")
    with pytest.raises(opentools.BadInputError, match="outside"):
        speech.keep_spans(job, outside, 5.0)


def test_a_tool_failure_carries_what_it_printed(tmp_path, monkeypatch):
    job, take = _take(tmp_path, monkeypatch)
    _select(monkeypatch, _fake(tmp_path, "echo 'no audio stream' >&2\nexit 1\n"))
    with pytest.raises(opentools.ToolFailedError, match="no audio stream"):
        speech.keep_spans(job, take, 5.0)


def test_a_timeout_cancels_the_tool(tmp_path, monkeypatch):
    job, take = _take(tmp_path, monkeypatch)
    marker = tmp_path / "survived"
    _select(monkeypatch, _fake(tmp_path, f"sleep 5\ntouch {marker}\n"), timeout_sec=0.5)
    with pytest.raises(opentools.ToolTimeoutError):
        speech.keep_spans(job, take, 5.0)
    assert not marker.exists()


@pytest.mark.parametrize(
    "body",
    [
        "exit 0\n",
        _writes("not json"),
        _writes({"timebase": "30/1", "v": [[]], "a": [[]]}),
        _writes({**V3, "timebase": "0/1"}),
        _writes({**V3, "v": [[{"offset": 0, "dur": 9000}]]}),
        _writes({**V3, "v": [[{"offset": 90, "dur": 30}, {"offset": 15, "dur": 30}]]}),
        _writes({**V3, "v": [[{"offset": 0, "dur": 30, "speed": 2}]]}),
    ],
)
def test_output_that_is_not_a_cut_list_is_a_bad_output(tmp_path, monkeypatch, body):
    job, take = _take(tmp_path, monkeypatch)
    _select(monkeypatch, _fake(tmp_path, body))
    with pytest.raises(opentools.BadOutputError):
        speech.keep_spans(job, take, 5.0)


def test_an_unknown_adapter_is_refused(tmp_path, monkeypatch):
    job, take = _take(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "studio", lambda: {"adapters": {"speech_cuts": {"use": "x"}}})
    with pytest.raises(speech.ContractError, match="unknown adapter"):
        speech.keep_spans(job, take, 5.0)


# The real command, on a tiny synthetic clip (tone, silence, tone). Skipped without it.


def _real() -> bool:
    exe = shutil.which(auto_editor.COMMAND)
    if exe is None:
        return False
    try:
        opentools.require_version(
            exe, auto_editor.VERSION_PATTERN, auto_editor.EXPECTS, program="auto-editor"
        )
    except opentools.ToolError:
        return False
    return True


needs_auto_editor = pytest.mark.skipif(not _real(), reason="auto-editor 29 is not installed")


@needs_ffmpeg
@needs_auto_editor
def test_the_real_command_cuts_the_silence_out_of_a_clip(tmp_path, monkeypatch):
    job, _ = _take(tmp_path, monkeypatch)
    clip = job.work / "tone.mp4"
    graph = (
        "sine=f=440:d=2:r=44100[a];anullsrc=r=44100:cl=mono:d=3[s];sine=f=440:d=2:r=44100[b];"
        "[a][s][b]concat=n=3:v=0:a=1[out]"
    )
    video = "color=c=black:s=64x64:d=7:r=15"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", video]
    cmd += ["-filter_complex", graph, "-map", "0:v", "-map", "[out]", "-shortest", str(clip)]
    subprocess.run(cmd, check=True)
    _select(monkeypatch, auto_editor.COMMAND)
    spans, _ = speech.keep_spans(job, clip, 7.0)
    assert len(spans) == 2
    (a0, a1), (b0, b1) = spans
    assert a0 <= 0.3 and 2.0 <= a1 <= 2.6 and 4.4 <= b0 <= 5.0 and b1 >= 6.9
