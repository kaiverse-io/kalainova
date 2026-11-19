"""A song made inside the studio's genre profile, asked of a stream; and one span of a vendor's
take sung again through the vendor's own edit route."""

from __future__ import annotations

import pytest
from fakes import Wire, context, make_job, needs_ffmpeg
from kit_fixtures import make_character, make_stream

from kalainova import config, genres, media, songs, streams, writers
from kalainova.jobfs import ContractError
from kalainova.providers import fal
from kalainova.providers.contract import Repaint, SongRequest

pytestmark = needs_ffmpeg
MUREKA, EDIT = "mureka/v9.5/generate/song", "mureka/api/song/edit"
PROFILE = {
    "label": "a test genre",
    "bpm": [120, 126],
    "keys": ["A minor", "F minor"],
    "duration_sec": 180,
    "vocal_gender": "female",
    "style": "warm pads, rolling bass",
    "avoid": "rap",
    "structure": [{"kind": "verse", "bars": 8}, {"kind": "chorus", "bars": 8}],
    "song_model": {"provider": "fal", "model": MUREKA},
    "takes": 3,
}


@pytest.fixture
def genre(monkeypatch):
    monkeypatch.setitem(config.studio(), "genres", {"test-genre": dict(PROFILE)})
    return "test-genre"


def _song(**extra):
    return {
        "schema_version": "0.1",
        "job_id": "p1",
        "title": "A Song",
        "style": "warm pads, rolling bass, clear lead vocal",
        "bpm": 123,
        "key": "A minor",
        "vocal_gender": "female",
        "sections": [{"kind": "verse", "lines": ["Hold the ladder steady now"], "bars": 8},
                     {"kind": "chorus", "lines": ["Hand me down the garden hose"], "bars": 8}],
        **extra,
    }  # fmt: skip


# ---------------------------------------------------------------- the profile


def test_a_genre_sets_the_songs_model_takes_and_length_unless_the_brief_does(genre):
    brief = genres.apply({"subject": "s"}, genre)
    assert brief["song_model"] == PROFILE["song_model"] and brief["takes"] == 3
    assert brief["duration_sec"] == 180
    own = {"provider": "fal", "model": "minimax/music-3"}
    assert genres.apply({"song_model": own, "takes": 1}, genre)["song_model"] == own
    with pytest.raises(ContractError, match="no genre profile"):
        genres.apply({}, "nowhere")


@pytest.mark.parametrize(
    ("change", "said"),
    [({"bpm": 140}, "tempo"), ({"key": "C major"}, "keys"), ({"vocal_gender": "male"}, "voice")],
)
def test_a_song_outside_its_genre_is_refused_before_spend(genre, change, said):
    found = genres.problems(_song(**change), genres.profile(genre))
    assert found and said in found[0]
    assert genres.problems(_song(), genres.profile(genre)) == []


def test_the_writer_is_handed_the_profile_but_not_the_model_or_takes(genre):
    text = genres.writer_text({"genre": genre})
    assert '"bpm"' in text and "structure" in text
    assert "song_model" not in text and '"takes"' not in text
    assert genres.writer_text({}) == ""


def test_the_writer_writes_inside_the_genre(tmp_path, studio, genre):
    job = make_job(tmp_path, media=["song"])
    job.write("job", {**job.job, "brief": {**job.job["brief"], "genre": genre}})
    studio.replies = ['{"title": "T", "style": "pads", "bpm": 123, "sections": [{"kind": "verse",'
                      ' "lines": ["a line"]}]}']  # fmt: skip
    writers.ensure(job, "song")
    asked = next(c for c in studio.calls if c["capability"] == "llm")
    assert "a test genre" in asked["prompt"] and job.read("song")["words_by"] == "model"


def test_a_song_outside_its_genre_never_reaches_a_model(tmp_path, studio, genre):
    job = make_job(tmp_path, media=["song"])
    job.write("job", {**job.job, "brief": {**job.job["brief"], "genre": genre}})
    job.write("song", _song(bpm=140))
    with pytest.raises(ContractError, match="tempo"):
        songs.run(job)
    assert not [c for c in studio.calls if c["capability"] == "song"]


# ---------------------------------------------------------------- a stream asked for a song


def test_a_stream_that_makes_audio_can_be_asked_for_a_song_in_a_genre(root, genre):
    make_character(root)
    make_stream(root)
    job = streams.request(root, "chan", "a night drive", media=["song"], genre=genre)
    assert job.job["media"] == ["song"]
    assert job.job["brief"]["genre"] == genre and job.job["brief"]["song_model"]["model"] == MUREKA
    with pytest.raises(ContractError, match="makes video, audio"):
        streams.request(root, "chan", "x", media=["comic"])
    with pytest.raises(ContractError, match="for a song"):
        streams.request(root, "chan", "x", genre=genre)


# ---------------------------------------------------------------- one span sung again


@pytest.fixture
def mureka(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "k")
    wire = Wire(default={"audio": {"url": "u"}, "song_id": "s-2", "id": "up-1"}, files={"u": b"x"})
    monkeypatch.setattr(fal.Fal, "transport", wire)
    return fal.Fal(), wire, tmp_path


def _edit(tmp, **span):
    take = tmp / "take.wav"
    take.write_bytes(b"w")
    words = span.pop("lyrics", "[Chorus]\nHand me down the garden hose")
    return SongRequest(lyrics="", dst=tmp / "e.wav", repaint=Repaint(
        source=take, start_sec=span.pop("start", 30.0), end_sec=span.pop("end", 45.0),
        lyrics=words, **span))  # fmt: skip


def test_a_vendors_own_take_is_edited_by_its_id_with_the_spans_new_words(mureka, monkeypatch):
    provider, wire, tmp = mureka
    monkeypatch.setattr(media, "run", lambda *a, **k: None)
    res = provider.song(_edit(tmp, vendor_id="s-1"), context(model=EDIT))
    sent = wire.sent[-1]
    assert sent["endpoint"] == EDIT
    assert sent["payload"] == {"song_id": "s-1", "lyrics": "[Chorus]\nHand me down the garden hose",
                               "edit_start": 30000, "edit_end": 45000}  # fmt: skip
    assert res.cost == pytest.approx(0.10) and res.meta == {"song_id": "s-2"}


def test_a_take_the_vendor_did_not_make_goes_up_first_and_is_charged(mureka, monkeypatch):
    provider, wire, tmp = mureka
    made = []
    monkeypatch.setattr(media, "run", lambda args, **k: made.append(args) or open(args[-1], "wb"))
    res = provider.song(_edit(tmp), context(model=EDIT))
    up, edit = wire.sent[-2], wire.sent[-1]
    assert up["endpoint"] == "mureka/api/files/upload" and up["payload"]["purpose"] == "audio"
    assert edit["payload"]["upload_audio_id"] == "up-1" and "song_id" not in edit["payload"]
    assert any("+bitexact" in a for a in made[0]), "the same bytes in a rehearsal and the paid run"
    assert res.cost == pytest.approx(0.11)


@pytest.mark.parametrize(
    ("span", "said"), [({"end": 31.0}, "at least 3"), ({"lyrics": " "}, "words")]
)
def test_an_edit_too_short_or_without_words_is_refused(mureka, span, said):
    provider, _, tmp = mureka
    with pytest.raises(ValueError, match=said):
        provider.song(_edit(tmp, **span), context(model=EDIT))


def test_a_repair_of_a_pinned_vendor_model_is_pinned_to_its_edit_route(
    tmp_path, studio, monkeypatch
):
    from kalainova import song_repair

    monkeypatch.setenv("FAL_KEY", "k")
    job = make_job(tmp_path, media=["song"])
    pinned = {"provider": "fal", "model": MUREKA}
    job.write("job", {**job.job, "brief": {**job.job["brief"], "song_model": pinned}})
    painter, pin = song_repair._repainter(job)
    assert painter == "fal" and pin is not None and pin.model == EDIT
    assert song_repair._span_words(_song(), "chorus") == "[Chorus]\nHand me down the garden hose"


# ---------------------------------------------------------------- a subscription's command line


def _stand_in(tmp_path, reply="ready"):
    """A stand-in for `claude -p`: it echoes what it was asked into a file and answers."""
    script = tmp_path / "claude"
    body = f'cat > "$PWD/asked.txt"; cp "$PWD/asked.txt" {tmp_path}/asked.txt; echo "{reply}"'
    script.write_text(f"#!/bin/sh\n{body}\n")
    script.chmod(0o755)
    return script


def test_a_subscription_command_line_writes_text_from_an_empty_folder(tmp_path, monkeypatch):
    from kalainova.providers import base, cli_llm
    from kalainova.providers.contract import TextRequest

    found = base.get("cli")
    monkeypatch.delenv(cli_llm.COMMAND_ENV, raising=False)
    assert not found.available("llm")
    monkeypatch.setenv(cli_llm.COMMAND_ENV, str(_stand_in(tmp_path)))
    assert found.available("llm") and found.free
    res = found.llm(TextRequest(prompt="write a song", system="be brief"), context())
    assert res.text == "ready" and res.model == "claude:default"
    assert (tmp_path / "asked.txt").read_text().strip() == "be brief\n\nwrite a song"
    assert cli_llm.argv("claude", "c", "", tmp_path)[:4] == ["c", "-p", "--output-format", "text"]
    assert "--allowedTools" in cli_llm.argv("claude", "c", "", tmp_path), "no tools: text only"
    assert cli_llm.argv("codex", "x", "m", tmp_path)[-3:] == ["-m", "m", "-"]


def test_a_subscription_at_its_limit_passes_the_question_to_the_next(tmp_path, monkeypatch):
    from kalainova.providers import base, cli_llm
    from kalainova.providers.contract import TextRequest

    spent = tmp_path / "limited" / "claude"
    spent.parent.mkdir()
    spent.write_text('#!/bin/sh\necho "You\'ve hit your session limit" >&2; exit 1\n')
    spent.chmod(0o755)
    other = tmp_path / "other"
    other.mkdir()
    codex = other / "codex"
    codex.write_text('#!/bin/sh\nwhile [ $# -gt 0 ]; do [ "$1" = -o ] && out="$2"; shift; done\n'
                     'echo written > "$out"\n')  # fmt: skip
    codex.chmod(0o755)
    monkeypatch.setenv(cli_llm.COMMAND_ENV, f"{spent}:{codex}")
    res = base.get("cli").llm(TextRequest(prompt="write"), context())
    assert res.text == "written" and res.model == "codex:default"
    monkeypatch.setenv(cli_llm.COMMAND_ENV, str(spent))
    with pytest.raises(RuntimeError, match="session limit"):
        base.get("cli").llm(TextRequest(prompt="write"), context())


def test_a_draft_that_breaks_the_songs_rules_is_told_and_written_again(tmp_path, studio, genre):
    job = make_job(tmp_path, media=["song"])
    job.write("job", {**job.job, "brief": {**job.job["brief"], "genre": genre}})
    off = (
        '{"title": "T", "style": "pads, no autotune", "bpm": 140, "key": "A minor", '
        '"vocal_gender": "female", "sections": [{"kind": "verse", "lines": ["a line"]}]}'
    )
    good = off.replace(", no autotune", "").replace("140", "123")
    studio.replies = [off, good]
    writers.ensure(job, "song", check=lambda d: songs.problems(d) + genres.problems(d, PROFILE))
    asks = [c for c in studio.calls if c["capability"] == "llm"]
    assert len(asks) == 2 and "tempo" in asks[1]["prompt"] and "avoid" in asks[1]["prompt"]
    assert job.read("song")["bpm"] == 123


def test_a_song_pinned_to_a_provider_alone_keeps_no_other_vendors_model(
    tmp_path, studio, monkeypatch
):
    from kalainova.__main__ import main

    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    job = make_job(tmp_path, media=["song"])
    pinned = {"provider": "fal", "model": MUREKA}
    job.write("job", {**job.job, "brief": {**job.job["brief"], "song_model": pinned}})
    assert main(["pin", job.id, "song", "mac", "--takes", "1"]) == 0
    from kalainova.jobfs import Job

    brief = Job(job.folder).job["brief"]
    assert "song_model" not in brief and brief["takes"] == 1


def test_the_song_file_is_written_alone_before_anything_is_made(tmp_path, studio, monkeypatch):
    from kalainova.__main__ import main

    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    job = make_job(tmp_path, media=["song"])
    studio.replies = ['{"title": "T", "style": "pads", "bpm": 123, "sections": [{"kind": "verse",'
                      ' "lines": ["a line"]}]}']  # fmt: skip
    assert main(["song", job.id, "--write"]) == 0
    assert job.read("song")["title"] == "T"
    assert not [c for c in studio.calls if c["capability"] == "song"], "nothing was made"


def test_a_songs_writer_gets_the_artists_voice_and_not_a_scripts_rules(root, studio, genre):
    from kalainova.jobfs import Job

    make_character(root)
    make_stream(root)
    job = streams.request(root, "chan", "a night drive", media=["song"], genre=genre)
    job.write("job", {**job.job, "providers": {"llm": ["fake"]}})
    studio.replies = [
        '{"title": "T", "style": "pads", "bpm": 123, "key": "A minor", '
        '"vocal_gender": "female", "sections": [{"kind": "verse", "lines": ["a"]}]}'
    ]
    writers.ensure(Job(job.folder), "song")
    asked = next(c for c in studio.calls if c["capability"] == "llm")["prompt"]
    assert "never_say" in asked and "three hooks" not in asked
