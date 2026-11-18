"""The engine, not the person running it, decides where a singing short is sung.

The vocal stem says when there is a voice, and what was heard says which of the song's words. From
those the engine cuts a short's stretch, puts the shot list's singing shots on sung spans, pays for
no lip sync over silence, and reads whether the chorus can be picked out. Between takes of several
jobs it picks by the rule that chooses within one.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import numpy as np
import pytest
from fakes import make_job, needs_ffmpeg
from test_music_video import SR, _write

from kalainova import reviewpage, shotmake, songs, takes
from kalainova.bar import song as musicbar
from kalainova.editor import musicvideo, singing
from kalainova.jobfs import ContractError, Job

SONG = {
    "sections": [
        {"kind": "verse", "lines": ["folding paper boats again"]},
        {
            "kind": "chorus",
            "lines": ["hold the lantern over water", "count the windows one by one"],
        },
    ]
}


def _sung(seconds: float, sung: list[tuple[float, float]]) -> singing.Sung:
    fps = 1 / singing.FRAME_SEC
    at = np.arange(int(seconds * fps)) / fps
    return np.array([any(a <= t < b for a, b in sung) for t in at]), fps


def _stem(path, seconds: float, sung: list[tuple[float, float]]):
    x = np.zeros(int(seconds * SR), np.float32)
    for a, b in sung:
        i, j = int(a * SR), int(b * SR)
        x[i:j] = 0.4 * np.sin(2 * np.pi * 220 * np.arange(j - i) / SR)
    return _write(path, x)


def _words(at: float, text: str) -> list[dict]:
    return [
        {"start_sec": at + 0.5 * n, "end_sec": at + 0.5 * n + 0.4, "text": w}
        for n, w in enumerate(text.split())
    ]


@needs_ffmpeg
def test_the_vocal_stem_says_where_there_is_a_voice(tmp_path):
    sung = singing.voiced(_stem(tmp_path / "v.wav", 10.0, [(2.0, 6.0)]))
    assert singing.share(sung, 0.0, 2.0) == pytest.approx(0.0, abs=0.05)
    assert singing.share(sung, 2.0, 6.0) == pytest.approx(1.0, abs=0.05)
    assert singing.share(sung, 0.0, 4.0) == pytest.approx(0.5, abs=0.05)


def test_singing_lines_go_to_moving_shots_that_are_sung_and_the_rest_fill_in_order():
    spans = [{"start": 2.0 * n, "end": 2.0 * (n + 1), "text": ""} for n in range(5)]
    kinds = ["video", "video", "still", "video", "video"]
    listed = ["Sings: front, she sings", "B-roll: the faders", "B-roll: the crowd"]
    lines, chosen = singing.place(listed, kinds, spans, _sung(10.0, [(4.0, 10.0)]))
    assert chosen == [3, 4], "the still is sung too, and has no mouth to sync"
    assert lines == [
        "B-roll: the faders",
        "B-roll: the crowd",
        "B-roll: the faders",
        "Sings: front, she sings",
        "Sings: front, she sings",
    ]
    late = _sung(20.0, [(14.0, 20.0)])
    on_the_songs_clock = singing.place(listed, kinds, spans, late, offset=10.0)[1]
    assert on_the_songs_clock == [3, 4]
    few = singing.place(listed, kinds, spans, _sung(10.0, [(8.0, 10.0)]))[1]
    assert few == [4], "no more singing shots than there are sung spans"


def test_the_longest_sung_span_sings_first_and_a_list_with_no_singing_runs_as_written():
    spans = [{"start": 0.0, "end": 1.0}, {"start": 1.0, "end": 4.0}, {"start": 4.0, "end": 6.0}]
    listed = ["Sings: close", "B-roll: hands", "B-roll: lights"]
    whole = _sung(6.0, [(0.0, 6.0)])
    assert singing.place(listed, ["video"] * 3, spans, whole)[1] == [1]
    plain = ["B-roll: hands", "B-roll: lights"]
    assert singing.place(plain, ["video"] * 3, spans, whole) == (
        ["B-roll: hands", "B-roll: lights", "B-roll: hands"],
        [],
    )


def test_a_singing_short_is_cut_on_bars_where_the_songs_words_are_heard_sung():
    found = {"bars": [2.0 * n for n in range(21)], "end": 40.0}
    heard = _words(4.0, "folding paper boats again") + _words(24.0, "hold the lantern over water")
    sung = _sung(40.0, [(4.0, 7.0), (24.0, 28.0)])
    a, b = singing.best_window(found, 8.0, SONG, heard, sung)
    assert b - a == pytest.approx(8.0) and a <= 24.0 and b >= 26.0, "the chorus counts double"
    a, b = singing.best_window(found, 8.0, SONG, [], _sung(40.0, [(30.0, 38.0)]))
    assert (a, b) == (30.0, 38.0), "nothing heard: where the voice is on longest"
    with pytest.raises(ContractError, match="no bars"):
        singing.best_window({"bars": [0.0], "end": 4.0}, 8.0, SONG, heard, sung)


def test_the_chorus_is_heard_when_half_of_each_lines_long_words_are():
    heard = [{"text": w} for w in ("lantern", "water")]
    assert musicbar.chorus_heard(SONG, heard) == 0.5, "one of the two chorus lines"
    assert musicbar.chorus_heard({"sections": [{"kind": "verse", "lines": ["x"]}]}, heard) is None


def test_a_take_is_read_off_its_vocal_stem_once_that_was_heard(tmp_path):
    take = tmp_path / "take-01.wav"
    assert musicbar.saved_heard(take) is None
    take.with_suffix(musicbar.MIX_HEARD).write_text(json.dumps([{"text": "mix"}]))
    assert musicbar.saved_heard(take) == [{"text": "mix"}]
    take.with_suffix(musicbar.STEM_HEARD).write_text(json.dumps([{"text": "stem"}]))
    assert musicbar.saved_heard(take) == [{"text": "stem"}]


@needs_ffmpeg
def test_a_finished_song_hears_its_lyrics_again_off_the_vocal_stem(tmp_path, studio):
    from test_songs import _heard, _job

    studio.heard = _heard()
    job = _job(tmp_path)
    songs.run(job)
    take = job.work / takes.chosen(job, "song")["file"]
    assert take.with_suffix(musicbar.STEM_HEARD).exists()
    heard = sum(c["capability"] == "transcribe" for c in studio.calls)
    assert heard >= 2, "the take, then its stem"
    checks = {c["id"]: c for c in songs.checks(job)[0]}
    assert checks["song.lyrics_heard_from"] == {
        "id": "song.lyrics_heard_from",
        "status": "pass",
        "detail": "the vocal stem",
    }


def test_an_unsigned_stem_transcript_leaves_the_mixs_standing(tmp_path, monkeypatch, capsys):
    def refused(*a, **k):
        raise ContractError("allowance-x.json is not signed off; a person signs it off")

    monkeypatch.setattr(songs, "_heard", refused)
    job = make_job(tmp_path, media=["song"])
    songs._sung_words(job, tmp_path / "vocals.wav", tmp_path / "take-01.wav")
    assert "not heard off the vocal stem" in capsys.readouterr().err


def test_a_sung_shot_is_never_lip_synced_after_and_a_spoken_line_on_camera_still_is():
    sung = {"id": "s01", "on_camera": True, "sings": {"start_sec": 0.0, "end_sec": 3.0}}
    assert not shotmake.synced_after(sung), "it was sung in the call that made it"
    assert shotmake.synced_after({"id": "s02", "on_camera": True}), "a line spoken on camera"
    assert not shotmake.synced_after({"id": "s03"})


@needs_ffmpeg
def test_an_excerpt_opens_a_vertical_short_unless_a_profile_is_named(tmp_path, monkeypatch, studio):
    from test_songs import _heard, _job

    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    studio.heard = _heard()
    job = _job(tmp_path)
    songs.run(job)
    seen = []
    real = musicvideo.build
    monkeypatch.setattr(musicvideo, "build", lambda *a, **k: seen.append(k) or real(*a, **k))
    listed = tmp_path / "shots.txt"
    listed.write_text("Sings: front, she sings\nB-roll: the faders\n")
    songs.video_job(job, "p1-short", excerpt={"length": 6.0, "start": None}, shots=listed)
    songs.video_job(job, "p1-long")
    assert [k["profile"] for k in seen] == ["short-9x16", "landscape"]
    assert seen[0]["sung_words"], "the stretch is chosen from what was heard"
    assert Job(tmp_path / "jobs" / "p1-short").read("script_packet")["beats"]


def test_between_jobs_the_pick_follows_the_rule_within_one():
    def take(n: int, ok: bool, rank: float, score: float = 1.0, misses=()) -> dict:
        readings = {"score": score, "rank": rank, "misses": list(misses)}
        return {"n": n, "ok": ok, "model": f"m{n}", "readings": readings}

    a, b = SimpleNamespace(id="arm-a"), SimpleNamespace(id="arm-b")
    found = [(a, take(0, True, 4.2)), (b, take(0, False, 4.9)), (b, take(1, True, 4.5))]
    assert reviewpage._pick(found).startswith("pick: arm-b take 1 (m1), the judge's highest")
    none = [(a, take(0, False, 4.9, 0.5, ["song.words_found"])), (b, take(0, False, 3.0, 0.9))]
    told = reviewpage._pick(none)
    assert told.startswith("pick: none passes every reading; the closest is arm-b take 0")


@needs_ffmpeg
def test_a_short_with_no_one_singing_on_screen_is_still_cut_where_the_words_are_sung(
    tmp_path, monkeypatch, studio
):
    """A performance short of a sung song: the stretch comes from the vocal stem and the words, so
    a track whose energy has no clear peak still gets one, and no shot is made to sing."""
    from test_songs import _heard, _job

    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    studio.heard = _heard()
    job = _job(tmp_path)
    songs.run(job)
    listed = tmp_path / "shots.txt"
    listed.write_text("front, at the decks: she nods to the kick\nB-roll: the faders\n")
    said: list[str] = []
    real = musicvideo.build
    monkeypatch.setattr(musicvideo, "build", lambda *a, **k: real(*a, **{**k, "say": said.append}))
    child = Job(
        songs.video_job(job, "p1-perf", excerpt={"length": 6.0, "start": None}, shots=listed)
    )
    assert any("heard sung" in line for line in said)
    assert not any(b.get("sings") for b in child.read("script_packet")["beats"])


SAYS_IN_SYNC = """
import argparse, json, pathlib, subprocess
p = argparse.ArgumentParser()
p.add_argument("--out", required=True)
p.add_argument("files", nargs="+")
a = p.parse_args()
def has_sound(f):
    probe = ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
             "-of", "csv=p=0", f]
    return bool(subprocess.run(probe, capture_output=True, text=True).stdout.strip())
said = {f: {"confidence": 7.5, "offset": 0.0} for f in a.files if has_sound(f)}
pathlib.Path(a.out).write_text(json.dumps(said))
"""


@needs_ffmpeg
def test_a_sung_take_is_judged_with_its_own_line_laid_on_its_picture(tmp_path, monkeypatch):
    import sys

    from kalainova import config

    script = tmp_path / "syncnet.py"
    script.write_text(SAYS_IN_SYNC)
    judge = {"name": "syncnet", "command": [sys.executable, str(script)], "rank_by": "confidence"}
    monkeypatch.setitem(config.studio(), "judges", {"lipsync": [judge]})
    line = _stem(tmp_path / "s01.voice.wav", 3.0, [(0.0, 3.0)])
    clip = tmp_path / "s01.take-00.mp4"
    from kalainova import media

    media.run(
        ["-f", "lavfi", "-i", "testsrc2=s=320x180:d=3:r=24", "-pix_fmt", "yuv420p", str(clip)]
    )
    readings, ok = shotmake.judged_sung(lambda p: ({"shot_motion": 0.4}, True), line)(clip)
    assert ok and readings["shot_motion"] == 0.4
    assert readings["judged"] == {"syncnet.confidence": 7.5, "syncnet.offset": 0.0}
    assert readings["rank"] == 7.5, "the judge ranks sung takes; it never blocks one"
    assert clip.with_suffix(".sync.mp4").exists(), "a silent take is heard with the line on it"
    monkeypatch.setitem(config.studio(), "judges", {"lipsync": []})
    plain = shotmake.judged_sung(lambda p: ({}, True), line)
    assert plain(clip) == ({}, True), "with no judge set, nothing is judged"


def test_no_shot_is_cut_shorter_than_a_bar_unless_the_whole_piece_is():
    from kalainova.editor import musiccuts as mc

    found = {"beats": [0.48 * n for n in range(40)]}  # a bar is 1.92 s

    def spans(*lengths: float) -> list[dict]:
        out, at = [], 0.0
        for n, length in enumerate(lengths):
            out.append({"start": at, "end": at + length, "text": f"line {n}", "strong": False})
            at += length
        return out

    slivers = mc.merge_short(spans(0.96, 0.94, 0.96, 0.48, 0.48), found)
    assert [(s["start"], s["end"]) for s in slivers] == [(0.0, pytest.approx(3.82))]
    assert slivers[0]["text"] == "line 0 / line 1 / line 2 / line 3 / line 4"
    kept = mc.merge_short(spans(4.0, 1.0, 4.0), found)
    assert [round(s["end"] - s["start"], 2) for s in kept] == [5.0, 4.0], "it joins the one before"


def test_a_bench_rehearsal_names_its_shot_and_at_least_two_models():
    from kalainova import rehearse

    assert rehearse.bench_asked(None, None) is None, "the job's own run"
    assert rehearse.bench_asked("s00", "a,b") == ("s00", ["a", "b"])
    with pytest.raises(ContractError, match="--bench takes a shot"):
        rehearse.bench_asked("s00", None)
    with pytest.raises(ContractError, match="at least two models"):
        rehearse.bench_asked("s00", "a")


def test_a_singing_shot_starts_on_a_mouth_in_full_view_and_a_hidden_one_is_flagged(
    tmp_path, monkeypatch
):
    import json as _json

    from kalainova import preproduction, shots

    sings = {"start_sec": 0.0, "end_sec": 3.8}
    sung = {"id": "s00", "visual_cue": "front, chest up: she sings", "text": "", "sings": sings}
    told = shotmake.picture_prompt(None, {"beats": [sung]}, sung, {"brief": {}})
    assert told.endswith(shots.MOUTH_CLEAR)
    plain = {"id": "s01", "visual_cue": "hands on the faders", "text": ""}
    assert shots.MOUTH_CLEAR not in shotmake.picture_prompt(None, {"beats": [plain]}, plain, {})

    asked: list[str] = []

    def judged(_job, request, **_kw):
        asked.append(request.prompt)
        said = {"passed": True, "mouth_ok": False, "region": [0.3, 0.4, 0.5, 0.6],
                "note": "a microphone covers her mouth"}  # fmt: skip
        return None, type("Reply", (), {"text": _json.dumps(said)})()

    job = make_job(tmp_path)
    monkeypatch.setattr(preproduction.router, "available", lambda *_: True)
    monkeypatch.setattr(preproduction.router, "generate", judged)
    refusal = preproduction.still_judge_refusal(
        job, {**sung, "visual_kind": "video"}, tmp_path / "s00.png"
    )
    assert refusal and "microphone covers her mouth" in refusal
    assert "This shot sings, so the mouth must be in full view" in asked[0]
