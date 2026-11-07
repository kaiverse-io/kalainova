"""What the new adapter paths send and keep, against the vendors' published shapes. No network."""

from __future__ import annotations

import base64
import subprocess
import sys
import types
from pathlib import Path

import pytest
from fakes import Reply, needs_ffmpeg

from kalainova import media
from kalainova.providers import base, fal, hyperframes, mac, remote, search, spaces


@pytest.fixture
def eleven(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "k")
    sent = []
    made = []

    def post(url, **kw):
        sent.append({"url": url, **kw})
        return replies.pop(0)

    replies: list[Reply] = []
    monkeypatch.setattr(remote.requests, "post", post)
    monkeypatch.setattr(media, "run", lambda args, **k: made.append(args))
    return remote.ElevenLabs(), sent, replies, made


def _speech(blob=b"pcm"):
    return Reply(body={"audio_base64": base64.b64encode(blob).decode(), "alignment": {}})


def test_speech_is_asked_for_losslessly_and_read_as_raw_samples(eleven, tmp_path):
    provider, sent, replies, made = eleven
    replies.append(_speech())
    res = provider.voice("A line.", tmp_path / "v.wav")
    assert "output_format=pcm_48000" in sent[0]["url"]
    assert res.meta["audio_format"] == "pcm_48000"
    assert made[0][:6] == ["-f", "s16le", "-ar", "48000", "-ac", "1"]


def test_a_plan_without_lossless_audio_falls_back_and_the_record_says_so(eleven, tmp_path):
    provider, sent, replies, made = eleven
    replies += [Reply(status=403, text="output_format not allowed on this tier"), _speech()]
    res = provider.voice("A line.", tmp_path / "v.wav")
    assert "mp3_44100_128" in sent[1]["url"]
    assert res.meta["audio_format"] == "mp3_44100_128"
    assert made[0][0] == "-i", "an mp3 needs no raw format"


def test_some_other_failure_is_not_mistaken_for_a_plan_limit(eleven, tmp_path):
    provider, sent, replies, _ = eleven
    replies.append(Reply(status=401, text="bad key"))
    with pytest.raises(OSError):
        provider.voice("A line.", tmp_path / "v.wav")
    assert len(sent) == 1


def test_a_song_goes_as_a_chunked_composition_plan(eleven, tmp_path):
    provider, sent, replies, _ = eleven
    replies.append(Reply(content=b"pcm"))
    sections = [
        {"kind": "verse", "lines": ["One", "Two"], "style": "soft"},
        {"kind": "chorus", "lines": ["Three", "Four", "Five", "Six"]},
    ]
    provider.song(
        "ignored", tmp_path / "s.wav", style="pop", duration=60, sections=sections, avoid="dark"
    )
    body = sent[0]["json"]
    assert body["model_id"] == "music_v2_5" and "prompt" not in body
    chunks = body["composition_plan"]["chunks"]
    assert chunks[0]["text"] == "[Verse]\nOne\nTwo"
    assert chunks[0]["positive_styles"] == ["pop", "soft"] and chunks[1]["negative_styles"] == [
        "dark"
    ]
    assert chunks[1]["duration_ms"] == 2 * chunks[0]["duration_ms"], "time follows the lines"


def test_a_song_plan_stays_inside_the_apis_limits():
    many = [{"kind": "verse", "lines": ["x"]} for _ in range(50)]
    chunks = remote.song_chunks(many, "pop", 10)
    assert len(chunks) == remote.SONG_MOST_CHUNKS
    assert all(c["duration_ms"] >= remote.SONG_LEAST_CHUNK_MS for c in chunks)


def test_a_song_with_no_sections_goes_as_a_prompt(eleven, tmp_path):
    provider, sent, replies, _ = eleven
    replies.append(Reply(content=b"pcm"))
    provider.song("The words", tmp_path / "s.wav", style="pop", duration=30)
    assert sent[0]["json"]["prompt"] == "pop\nThe words"


@pytest.fixture
def falapi(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "k")
    sent = {}

    def run(self, model, payload, timeout=900):
        sent.update(model=model, payload=payload)
        return {"video": {"url": "u"}, "audio": {"url": "u"}, "images": [{"url": "u"}], "seed": 77}

    monkeypatch.setattr(fal.Fal, "_run", run)
    monkeypatch.setattr(fal, "_download", lambda url, dst: Path(dst).write_bytes(b"x"))
    monkeypatch.setattr(media, "run", lambda *a, **k: None)
    return fal.Fal(), sent, tmp_path


def test_a_seed_is_sent_and_the_seed_used_is_kept(falapi):
    provider, sent, tmp = falapi
    res = provider.video("p", tmp / "a.mp4", duration=5, aspect="16:9", seed=42)
    assert sent["payload"]["seed"] == 42 and res.meta["seed"] == 77


def test_with_no_seed_asked_none_is_sent(falapi):
    provider, sent, tmp = falapi
    provider.video("p", tmp / "a.mp4", duration=5, aspect="16:9")
    assert "seed" not in sent["payload"]


def test_a_big_input_goes_through_storage_and_a_small_one_stays_inline(falapi, monkeypatch):
    provider, _, tmp = falapi
    small = tmp / "small.png"
    small.write_bytes(b"x" * 100)
    assert provider._upload(small).startswith("data:image/png")
    calls = {}

    def post(url, **kw):
        calls["init"] = (url, kw["json"])
        return Reply(
            body={"upload_url": "https://put.example", "file_url": "https://cdn.example/f"}
        )

    def put(url, **kw):
        calls["put"] = url
        return Reply()

    monkeypatch.setattr(fal.requests, "post", post)
    monkeypatch.setattr(fal.requests, "put", put)
    big = tmp / "big.png"
    big.write_bytes(b"x" * (fal.INLINE_MOST_BYTES + 1))
    assert provider._upload(big) == "https://cdn.example/f"
    assert calls["init"][1]["content_type"] == "image/png" and calls["put"] == "https://put.example"


def test_a_lost_file_after_the_vendor_finished_is_still_billed(monkeypatch, tmp_path):
    def gone(url, dst):
        raise OSError("connection reset")

    monkeypatch.setattr(fal, "_download", gone)
    with pytest.raises(base.BilledError) as caught:
        fal.Fal._fetch("u", tmp_path / "a.mp4", 1.68)
    assert caught.value.billed == 1.68


def test_a_lip_sync_sends_the_clip_and_the_line(falapi):
    provider, sent, tmp = falapi
    clip, line = tmp / "c.mp4", tmp / "v.wav"
    clip.write_bytes(b"c")
    line.write_bytes(b"v")
    monkey = (
        provider  # the duration of a fake file cannot be read, so the price is not checked here
    )
    media_duration = media.duration
    try:
        media.duration = lambda p: 6.0
        res = monkey.lipsync(clip, line, tmp / "o.mp4")
    finally:
        media.duration = media_duration
    assert sent["model"] == "fal-ai/sync-lipsync/v2"
    assert set(sent["payload"]) == {"video_url", "audio_url", "sync_mode"}
    assert res.cost == pytest.approx(0.3)


def test_a_fal_song_sends_style_and_words_apart(falapi):
    provider, sent, tmp = falapi
    provider.song("[verse]\nWords", tmp / "s.wav", style="pop", duration=90)
    assert sent["model"] == "minimax/music-3"
    assert sent["payload"] == {"prompt": "pop", "lyrics": "[verse]\nWords", "duration": 90}


# ---- on this machine --------------------------------------------------------------------
@pytest.fixture
def machine(monkeypatch, tmp_path):
    monkeypatch.setenv(mac.PYTHON_ENV, str(tmp_path / "env" / "bin" / "python"))
    monkeypatch.setenv(mac.SONG_PYTHON_ENV, "/song/env/python")
    monkeypatch.setenv(mac.SONG_CHECKPOINT_ENV, "/song/checkpoints")
    monkeypatch.setenv("HF_HOME", str(tmp_path / "hf"))
    seen = {}

    def fake(cmd, timeout=None):
        seen.update(cmd=cmd, timeout=timeout)
        out = Path(cmd[cmd.index("--out") + 1]) if "--out" in cmd else None
        if out:
            seen["lyrics"] = Path(cmd[cmd.index("--lyrics") + 1]).read_text()
            out.write_bytes(b"sung")
        elif "--output-path" in cmd:
            Path(cmd[cmd.index("--output-path") + 1]).write_bytes(b"frames")
        return ""

    monkeypatch.setattr(mac, "_run", fake)
    monkeypatch.setattr(media, "run", lambda args, **k: Path(args[-1]).write_bytes(b"w"))
    return seen


def test_a_song_runs_in_its_own_environment_with_its_own_seed(machine, tmp_path):
    res = mac.Mac().song(
        "[Verse]\nWords", tmp_path / "s.wav", style="pop", duration=60, seed=7, bpm=96
    )
    cmd = machine["cmd"]
    assert cmd[0] == "/song/env/python" and Path(cmd[1]) == mac.SONG_RUNNERS["heartmula"]
    assert cmd[cmd.index("--seed") + 1] == "7" and cmd[cmd.index("--bpm") + 1] == "96"
    assert machine["lyrics"] == "[Verse]\nWords"
    assert res.meta["seed"] == 7 and res.model == "heartmula"


def test_each_song_engine_has_its_runner_on_disk():
    assert all(path.is_file() for path in mac.SONG_RUNNERS.values())


def test_a_song_with_no_engine_set_up_is_a_provider_failure(machine, tmp_path, monkeypatch):
    monkeypatch.delenv(mac.SONG_PYTHON_ENV)
    with pytest.raises(RuntimeError, match=mac.SONG_PYTHON_ENV):
        mac.Mac().song("Words", tmp_path / "s.wav")


def test_a_take_asks_a_clip_for_its_own_seed(machine, tmp_path):
    res = mac.Mac().video("waves", tmp_path / "c.mp4", duration=2.0, aspect="16:9", seed=123)
    assert machine["cmd"][machine["cmd"].index("--seed") + 1] == "123"
    assert res.meta["seed"] == 123


def test_sound_is_only_asked_for_when_a_job_wants_it(machine, tmp_path):
    mac.Mac().video("waves", tmp_path / "c.mp4", duration=2.0, aspect="16:9")
    assert "--no-audio" in machine["cmd"]
    mac.Mac().video("waves", tmp_path / "d.mp4", duration=2.0, aspect="16:9", audio=True)
    assert "--no-audio" not in machine["cmd"]


def test_a_long_shot_gets_the_time_it_needs_past_a_flat_deadline(machine, tmp_path):
    mac.Mac().video("waves", tmp_path / "c.mp4", duration=30.0, aspect="16:9", deadline_sec=1900)
    assert machine["timeout"] > 30 * 24 * mac.SECONDS_PER_VIDEO_FRAME


def test_the_exact_weights_are_read_from_the_local_cache(machine, tmp_path):
    ref = tmp_path / "hf" / "hub" / "models--someone--weights" / "refs" / "main"
    ref.parent.mkdir(parents=True)
    ref.write_text("abc123\n")
    assert mac._weights_revision("someone/weights") == "abc123"
    assert mac._weights_revision("someone/other") is None


def test_a_call_that_runs_out_is_really_stopped_with_everything_it_started(tmp_path, monkeypatch):
    monkeypatch.setenv(mac.PYTHON_ENV, str(tmp_path / "env" / "bin" / "python"))
    if not Path("/usr/bin/caffeinate").exists():
        pytest.skip("needs macOS")
    marker = tmp_path / "survived"
    child = f"import time, pathlib; time.sleep(3); pathlib.Path({str(marker)!r}).write_text('x')"
    with pytest.raises(TimeoutError, match="no result"):
        mac._run([sys.executable, "-c", child], timeout=0.5)
    import time

    time.sleep(3.5)
    assert not marker.exists(), "the model process was left running"


def test_a_queued_call_does_not_lose_its_deadline_to_the_queue():
    assert mac.Mac.self_timed is True


# ---- hosted apps and compositions -------------------------------------------------------
def test_a_hosted_app_gets_only_the_fields_it_takes(monkeypatch, tmp_path):
    sent = {}

    class Client:
        def __init__(self, space, verbose=False):
            sent["space"] = space

        def predict(self, **kw):
            sent.update(kw)
            return {"path": "/tmp/made.wav"}

    module = types.SimpleNamespace(Client=Client)
    monkeypatch.setitem(sys.modules, "gradio_client", module)
    monkeypatch.setattr(media, "run", lambda args, **k: sent.setdefault("made", args[1]))
    res = spaces.Spaces().song("Words", tmp_path / "s.wav", style="pop", duration=45, seed=9)
    assert sent["space"] == "mrfakename/HeartMuLa" and sent["api_name"] == "/generate_music"
    assert (
        sent["lyrics"] == "Words" and sent["tags"] == "pop" and sent["max_duration_seconds"] == 45
    )
    assert "seed" not in sent, "this app has no seed field"
    assert sent["made"] == "/tmp/made.wav" and res.meta["seed"] == 9


def test_a_hosted_app_that_takes_a_seed_gets_it_and_one_with_no_length_gets_none():
    spec = {"lyrics_param": "words", "style_param": "tags", "seed_param": "seed", "extra": {"x": 1}}
    request = spaces._song_request(spec, "Words", "pop", 45, 9)
    assert request == {"words": "Words", "tags": "pop", "seed": 9, "x": 1}
    assert "seed" not in spaces._song_request(spec, "Words", "pop", None, None)


def test_a_hosted_song_needs_an_app_named_in_config(monkeypatch, tmp_path):
    monkeypatch.setattr(spaces.config, "space_spec", lambda name: {})
    with pytest.raises(ValueError, match="names no app"):
        spaces.Spaces().song("Words", tmp_path / "s.wav")


@pytest.mark.parametrize(
    "output",
    ["/tmp/a.wav", {"path": "/tmp/a.wav"}, ("/tmp/a.wav", "notes"), [{"path": "/tmp/a.wav"}, 3]],
)
def test_a_hosted_apps_output_is_found_in_whatever_shape_it_comes(output):
    assert spaces._first_path(output) == "/tmp/a.wav"


def test_a_hosted_app_that_returned_no_file_is_a_provider_failure():
    with pytest.raises(ValueError, match="no file"):
        spaces._first_path(3)


def test_a_hosted_app_needs_its_extra_installed(monkeypatch):
    monkeypatch.setattr(spaces.importlib.util, "find_spec", lambda name: None)
    assert "spaces extra" in spaces.Spaces().missing_env()[0]


def test_a_music_model_that_finished_without_a_file_is_still_billed(falapi, monkeypatch):
    provider, _, folder = falapi
    monkeypatch.setattr(fal.Fal, "_run", lambda self, m, p, timeout=900: {})

    def no_url(url, dst):
        raise OSError(f"bad url: {url!r}")

    monkeypatch.setattr(fal, "_download", no_url)
    with pytest.raises(base.BilledError):
        provider.music("a theme", folder / "m.wav", duration=5)


def test_a_song_engine_is_told_only_what_was_asked():
    asked = {"bpm": 96, "key": "C major", "language": "", "instrumental": True}
    assert mac._song_options(asked) == ["--bpm", "96", "--key", "C major", "--instrumental"]
    assert mac._song_options({}) == []


def test_the_scholarly_search_skips_a_work_with_nowhere_to_read_it(monkeypatch):
    works = {
        "results": [
            {"title": "No link"},
            {
                "doi": "https://doi.org/10.1/x",
                "title": "A paper",
                "publication_date": "2001-01-01",
                "primary_location": {"source": {"display_name": "A Journal"}},
                "abstract_inverted_index": {"Short": [0], "abstract": [1]},
            },
        ]
    }
    monkeypatch.setattr(search.requests, "get", lambda url, **kw: Reply(body=works))
    hits = search.OpenAlex().search("a question").meta["hits"]
    assert [h["title"] for h in hits] == ["A paper"]
    assert hits[0]["publisher"] == "A Journal" and hits[0]["text"] == "Short abstract"


def _stems(tmp, names):
    for name in names:
        (Path(tmp) / name).write_bytes(b"x")


def test_a_mix_splits_into_vocals_and_the_rest_at_the_mix_rate(monkeypatch, tmp_path):
    monkeypatch.setenv(mac.PYTHON_ENV, str(tmp_path / "bin" / "python"))
    ran = []

    def split(cmd, timeout=None):
        _stems(cmd[cmd.index("--output_dir") + 1], ["x_(Vocals).wav", "x_(Instrumental).wav"])
        return ""

    monkeypatch.setattr(mac, "_run", split)
    monkeypatch.setattr(media, "run", lambda args, **k: ran.append(args))
    mix, sung, rest = (tmp_path / n for n in ("mix.wav", "sung.wav", "rest.wav"))
    result = mac.Mac().separate(mix, sung, rest)
    assert result.path == sung
    assert [args[-1] for args in ran] == [str(sung), str(rest)]
    assert all("48000" in args for args in ran)


def test_a_split_that_left_no_stems_is_a_provider_failure(monkeypatch, tmp_path):
    monkeypatch.setenv(mac.PYTHON_ENV, str(tmp_path / "bin" / "python"))

    def nothing(cmd, timeout=None):
        _stems(cmd[cmd.index("--output_dir") + 1], ["other.wav"])
        return ""

    monkeypatch.setattr(mac, "_run", nothing)
    with pytest.raises(RuntimeError, match=r"other\.wav"):
        mac.Mac().separate(tmp_path / "m.wav", tmp_path / "a.wav", tmp_path / "b.wav")


def test_a_composition_renders_in_its_own_folder_to_the_right_format(monkeypatch, tmp_path):
    seen = {}

    def run(cmd, **kw):
        seen.update(cmd=cmd, cwd=kw["cwd"])
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(hyperframes.shutil, "which", lambda name: "/bin/npx")
    monkeypatch.setattr(hyperframes.subprocess, "run", run)
    hyperframes.HyperFrames().graphics(tmp_path, tmp_path / "o.mov")
    assert seen["cwd"] == tmp_path
    assert seen["cmd"][seen["cmd"].index("--format") + 1] == "mov"


def test_a_failed_composition_is_a_provider_failure(monkeypatch, tmp_path):
    failed = subprocess.CompletedProcess([], 1, "", "a chart broke")
    monkeypatch.setattr(hyperframes.shutil, "which", lambda name: "/bin/npx")
    monkeypatch.setattr(hyperframes.subprocess, "run", lambda *a, **k: failed)
    with pytest.raises(RuntimeError, match="a chart broke"):
        hyperframes.HyperFrames().graphics(tmp_path, tmp_path / "o.mp4")


def test_a_composition_needs_node(monkeypatch):
    monkeypatch.setattr(hyperframes.shutil, "which", lambda name: None)
    assert hyperframes.HyperFrames().missing_env()


@needs_ffmpeg
def test_a_silent_file_is_told_apart_from_a_real_one(tmp_path):
    quiet, loud = tmp_path / "q.wav", tmp_path / "l.wav"
    media.run(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo:d=1", str(quiet)])
    media.run(["-f", "lavfi", "-i", "sine=f=220:d=1", str(loud)])
    assert not media.has_sound(quiet) and media.has_sound(loud)
