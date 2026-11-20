"""From a song file to its release: what a song model is sent, what a take keeps, what is refused
before spend, a rehearsal of the takes, a pin set by command, the chosen master released, and the
record of what AI made."""

from __future__ import annotations

import json

import pytest
from fakes import Wire, context, make_job, needs_ffmpeg

from kalainova import media, rehearse, song_lead, song_master, songs, takes
from kalainova.__main__ import main
from kalainova.jobfs import ContractError
from kalainova.providers import fal
from kalainova.providers.contract import SongRequest
from kalainova.render import release

pytestmark = needs_ffmpeg
MUREKA = "mureka/v9.5/generate/song"
VERSE = ["Paper boats on the kitchen floor", "Pencil marks beside the door"]
MOVES = [
    {"kind": "verse", "lines": ["Words"], "style": "restrained and intimate."},
    {"kind": "chorus", "lines": ["More"], "style": "full groove, harmonies wide"},
    {"kind": "outro", "lines": ["End"]},
]


def _song(**extra):
    return {
        "schema_version": "0.1",
        "job_id": "p1",
        "title": "A Song",
        "style": "warm indie pop, acoustic guitar, clear lead vocal",
        "duration_sec": 12,
        "bpm": 120,
        "vocal_gender": "female",
        "words_by": "model",
        "sections": [{"kind": "verse", "lines": VERSE, "bars": 6}],
        **extra,
    }


@pytest.fixture
def mureka(monkeypatch, tmp_path):
    monkeypatch.setenv("FAL_KEY", "k")
    wire = Wire(default={"audio": {"url": "u"}, "song_id": "vendor-17"}, files={"u": b"x"})
    monkeypatch.setattr(fal.Fal, "transport", wire)
    monkeypatch.setattr(media, "run", lambda *a, **k: None)
    return fal.Fal(), wire, tmp_path


# ---------------------------------------------------------------- what the model is sent


def test_the_vocal_gender_goes_to_mureka_as_its_own_setting(mureka):
    provider, wire, tmp = mureka
    req = SongRequest(lyrics="[Verse]\nW", dst=tmp / "s.wav", style="house", duration=180,
                      vocal_gender="female")  # fmt: skip
    res = provider.song(req, context(model=MUREKA))
    assert wire.sent[-1]["payload"]["gender"] == "female"
    assert res.meta == {"song_id": "vendor-17"}  # kept, so an edit of the take needs no upload


def test_an_instrumental_or_a_model_without_the_setting_is_sent_no_gender(mureka):
    provider, wire, tmp = mureka
    req = SongRequest(lyrics="[Inst]", dst=tmp / "s.wav", style="house", duration=180,
                      vocal_gender="male", instrumental=True)  # fmt: skip
    provider.song(req, context(model=MUREKA))
    assert "gender" not in wire.sent[-1]["payload"]
    sung = SongRequest(lyrics="[Verse]\nW", dst=tmp / "t.wav", style="pop", vocal_gender="male")
    provider.song(sung, context(model="fal-ai/lyria3/pro"))
    assert "gender" not in wire.sent[-1]["payload"]


@pytest.mark.parametrize("style", ["house, no autotune", "pop without reverb", "never any vocoder"])
def test_a_style_that_names_what_it_does_not_want_is_refused(style):
    found = songs.problems(_song(style=style))
    assert found and "avoid" in found[0]


def test_a_style_of_only_what_it_wants_passes():
    assert songs.problems(_song(style="nocturnal, notably bright pads, nonstop groove")) == []


def test_a_section_note_is_held_to_the_styles_rules_since_it_is_sent_too():
    quiet = [{"kind": "intro", "lines": [], "style": "pads only, no vocal"},
             {"kind": "verse", "lines": VERSE}]  # fmt: skip
    found = songs.problems(_song(sections=quiet))
    assert len(found) == 1 and "section" in found[0] and "avoid" in found[0]


@pytest.mark.parametrize("line", ["instrumental", "(Instrumental)", "[inst]", "no vocals"])
def test_a_stage_direction_among_the_lines_is_refused_since_it_would_be_sung(line):
    quiet = [{"kind": "intro", "lines": [line]}, {"kind": "verse", "lines": VERSE}]
    found = songs.problems(_song(sections=quiet))
    assert len(found) == 1 and "would be sung" in found[0]
    assert (
        songs.problems(_song(sections=[{"kind": "verse", "lines": ["An instrumental night"]}]))
        == []
    )


def test_how_an_uncommon_word_is_said_reaches_the_model_with_the_style():
    song = _song(sections=[{"kind": "verse", "lines": ["Wave the lantern, amigos"]}],
                 pronounce={"amigos": "ah-MEE-gohs"})  # fmt: skip
    assert songs.problems(song) == []
    said = songs.style_text(song)
    assert said == 'warm indie pop, acoustic guitar, clear lead vocal, pronounce "amigos" as ' \
                   '"ah-MEE-gohs", 120 bpm'  # fmt: skip
    assert "adelante" in songs.problems({**song, "pronounce": {"adelante": "ah-deh-LAHN-teh"}})[0]


def test_a_draft_brief_is_short_names_no_tempo_and_keeps_its_section_notes_brief():
    assert song_lead.draft_problems(_song()) == []
    long = song_lead.draft_problems(_song(style="pads, " * 100))
    assert len(long) == 1 and "under 450" in long[0]
    assert "bpm" in song_lead.draft_problems(_song(style="pads, a steady 122 bpm pulse"))[0]
    wordy = [{"kind": "verse", "lines": VERSE, "style": "drums " * 20}]
    assert "verse" in song_lead.draft_problems(_song(sections=wordy))[0]


def test_a_section_note_rides_on_its_lyric_tag_where_the_model_reads_it_there(mureka):
    provider, wire, tmp = mureka
    words = SongRequest(lyrics="[Verse]\nWords\n", dst=tmp / "s.wav", style="house", duration=180,
                        sections=MOVES)  # fmt: skip
    provider.song(words, context(model="mureka/v9.5/generate/song"))
    assert wire.sent[-1]["payload"]["prompt"] == "house"
    assert wire.sent[-1]["payload"]["lyrics"] == (
        "[Verse] restrained and intimate\nWords\n[Chorus] full groove, harmonies wide\nMore\n"
        "[Outro]\nEnd\n"
    )


def test_a_model_that_reads_no_notes_on_tags_gets_them_after_the_style(mureka):
    provider, wire, tmp = mureka
    words = SongRequest(lyrics="[Verse]\nWords\n", dst=tmp / "s.wav", style="house.",
                        duration=90, sections=MOVES)  # fmt: skip
    provider.song(words, context(model="minimax/music-3"))
    assert wire.sent[-1]["payload"]["prompt"] == (
        "house. Verse: restrained and intimate. Chorus: full groove, harmonies wide."
    )
    assert wire.sent[-1]["payload"]["lyrics"] == "[Verse]\nWords\n"


def test_words_past_the_vendors_limit_are_refused_before_sending(mureka):
    provider, wire, tmp = mureka
    long = SongRequest(lyrics="w" * 5001, dst=tmp / "s.wav", style="house", duration=180)
    with pytest.raises(ValueError, match="at most 5000 lyrics characters"):
        provider.song(long, context(model="mureka/v9.5/generate/song"))
    short = SongRequest(lyrics="w", dst=tmp / "s.wav", style="house", duration=90)
    with pytest.raises(ValueError, match="at least 120 s"):
        provider.song(short, context(model="mureka/v9.5/generate/song"))


def test_a_plan_model_takes_each_section_as_a_chunk_of_its_own_length_and_direction(mureka):
    provider, wire, tmp = mureka
    verse = {"kind": "verse", "bars": 16, "lines": VERSE, "style": "restrained and intimate"}
    sections = [{"kind": "intro", "bars": 8, "style": "pads alone", "avoid": "kick, rap"}, verse]
    req = SongRequest(lyrics="", dst=tmp / "s.wav", style="synth pop", duration=180, bpm=120,
                      sections=sections, avoid="rap, autotune", seed=7)  # fmt: skip
    res = provider.song(req, context(model="elevenlabs/music/v2.5"))
    sent = wire.sent[-1]["payload"]
    first, second = sent["composition_plan"]["chunks"]
    assert (first["duration_ms"], second["duration_ms"]) == (16000, 32000)  # bars at 120 bpm
    assert first["text"] == "[Intro]" and second["text"] == "[Verse]\n" + "\n".join(VERSE)
    assert first["positive_styles"] == ["pads alone", "synth pop"]  # its own note leads
    assert second["positive_styles"] == ["restrained and intimate"]
    assert first["negative_styles"] == ["kick", "rap", "autotune"]  # its own, then the song's
    assert second["negative_styles"] == ["rap", "autotune"] and sent["seed"] == 7
    assert res.cost == pytest.approx(48 * 0.01)  # $0.60 a minute, for the 48 s the plan runs


def test_a_section_longer_than_a_chunk_is_refused_before_sending(mureka):
    provider, wire, tmp = mureka
    long = SongRequest(lyrics="", dst=tmp / "s.wav", style="house", bpm=60,
                       sections=[{"kind": "verse", "bars": 40, "lines": ["a"]}])  # fmt: skip
    with pytest.raises(ValueError, match="a chunk is 3 to 120 s"):
        provider.song(long, context(model="elevenlabs/music/v2.5"))


def test_mureka_v9_takes_v95s_request_without_a_length(mureka):
    provider, wire, tmp = mureka
    req = SongRequest(lyrics="[Verse]\nW\n", dst=tmp / "s.wav", style="house", duration=180,
                      vocal_gender="female", sections=MOVES)  # fmt: skip
    provider.song(req, context(model="mureka/v9/generate/song"))
    sent = wire.sent[-1]["payload"]
    assert "duration" not in sent and sent["gender"] == "female"
    assert sent["lyrics"].startswith("[Verse] restrained and intimate\n")


# ---------------------------------------------------------------- before spend


def _job(tmp_path, song=None, **extra):
    job = make_job(tmp_path, media=["song"], **extra)
    job.write("song", song or _song())
    return job


def test_a_rehearsal_writes_down_each_planned_take_and_sends_nothing(tmp_path, studio):
    job = _job(tmp_path, _song(duration_sec=180))  # Mureka makes 120 to 300 s
    pinned = {"provider": "fal", "model": MUREKA}
    job.write("job", {**job.job, "providers": {**job.job["providers"], "song": ["fal"]},
                      "brief": {**job.job["brief"], "song_model": pinned}})  # fmt: skip
    report = rehearse.run(job, check=None)
    asked = [r for c in report["calls"] if c["capability"] == "song" for r in c["requests"]]
    assert len(asked) == songs.SAFE_TAKES["takes"], report["stopped"]
    assert {r["payload"]["gender"] for r in asked} == {"female"}
    assert not report["stopped"]
    assert not takes.load(job)["shots"]  # the real job made nothing


def test_a_rehearsal_stops_where_the_run_would(tmp_path, studio):
    job = _job(tmp_path, _song(style="house, no autotune"))
    assert "avoid" in rehearse.run(job, check=None)["stopped"]


def test_a_pin_sets_the_song_model_and_its_takes_by_command(tmp_path, studio, monkeypatch):
    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    job = _job(tmp_path)
    assert main(["pin", job.id, "song", f"fal:{MUREKA}", "--takes", "3"]) == 0
    data = json.loads(job.path("job").read_text())
    assert data["brief"]["song_model"] == {"provider": "fal", "model": MUREKA}
    assert data["providers"]["song"] == ["fal"]
    assert data["brief"]["takes"] == data["brief"]["max_takes"] == 3
    assert main(["pin", job.id, "song", "nowhere"]) != 0
    assert main(["pin", job.id, "transcribe", "fal:some-model"]) != 0


# ---------------------------------------------------------------- the release


def _made(tmp_path):
    job = _job(tmp_path)
    songs.run(job)
    return job


def test_a_release_says_what_ai_made_part_by_part(tmp_path, studio):
    job = _made(tmp_path)
    record = json.loads((job.work / "release" / release.AI_USE).read_text())
    assert record["parts"]["lyrics"] == {"by": "a model", "ai": True}
    assert record["parts"]["music"]["ai"] and record["parts"]["vocals"]["ai"]
    assert record["parts"]["mastering"]["ai"] is False
    assert record["suggested_ai_credits"] == ["All of the audio", "The lyrics"]


def test_words_a_person_wrote_are_not_credited_to_ai():
    record = release.ai_use(_song(words_by="person"), "fake: m", None)
    assert record["parts"]["lyrics"]["ai"] is False
    assert record["suggested_ai_credits"] == ["All of the audio"]


def test_only_a_master_a_person_chose_is_released(tmp_path, studio):
    job = _made(tmp_path)
    with pytest.raises(ContractError, match="no master options"):
        song_master.release(job)
    made = song_master.make(job, vocal_db=[-1.0, 1.0])
    with pytest.raises(ContractError, match="no one has chosen"):
        song_master.release(job)
    takes.choose(job, "master", made[1]["n"])
    final = song_master.release(job)
    assert media.loudness(final)["integrated_lufs"] == pytest.approx(-14, abs=1)
    song = next(a for a in job.read("asset_manifest")["assets"] if a["role"] == "song")
    assert song["provenance"]["master"]["take"] == made[1]["n"]
    assert song["provenance"]["master"]["vocal_db"] == 1.0
    record = json.loads((job.work / "release" / release.AI_USE).read_text())
    assert record["parts"]["mastering"]["chosen_by"] == "a person"


def test_a_master_of_another_song_take_is_refused_until_that_take_stands(tmp_path, studio):
    job = _job(tmp_path)
    job.write("job", {**job.job, "brief": {**job.job["brief"], "takes": 2, "max_takes": 2}})
    songs.run(job)
    other = next(t["n"] for t in takes.load(job)["shots"]["song"]["takes"]
                 if t["n"] != takes.chosen(job, "song")["n"])  # fmt: skip
    (made,) = song_master.make(job, take_n=other)
    takes.choose(job, "master", made["n"])
    with pytest.raises(ContractError, match="the song stands on take"):
        song_master.release(job)


def test_the_style_joins_its_tempo_and_key_cleanly():
    said = songs.style_text(_song(style="warm pads. The outro thins out.", key="A minor"))
    assert said == "warm pads. The outro thins out, 120 bpm, A minor"


def _noise_wav(path, levels, sr=22050, sec=8.0):
    import wave

    import numpy as np

    rng = np.random.default_rng(1)
    parts = [level * rng.standard_normal(int(sr * sec)) for level in levels]
    pcm = (np.clip(np.concatenate(parts), -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1), out.setsampwidth(2), out.setframerate(sr)
        out.writeframes(pcm.tobytes())
    return path


def test_an_intro_played_at_full_level_reads_as_no_soft_start(tmp_path):
    from kalainova.bar import song as musicbar

    sections = [{"kind": "intro", "bars": 4}, {"kind": "chorus", "bars": 4}]  # 8 s each at 120
    song = _song(sections=sections, bpm=120)
    soft = musicbar.intro_rise(_noise_wav(tmp_path / "soft.wav", [0.05, 0.4]), song)
    loud = musicbar.intro_rise(_noise_wav(tmp_path / "loud.wav", [0.4, 0.4]), song)
    assert soft < -15 and -0.5 < loud <= 0.0
    assert musicbar.intro_rise(tmp_path / "loud.wav", _song()) is None  # no intro asked for
    unplaced = _song(sections=[{"kind": "intro"}, {"kind": "chorus"}])
    assert (
        musicbar.intro_rise(_noise_wav(tmp_path / "long.wav", [0.05, 0.05, 0.4, 0.4]), unplaced)
        < -10
    )


def test_an_uncommon_word_is_said_on_the_chunk_that_sings_it(mureka):
    """The hint rode only in the song's style, which a plan sends on its first chunk, so a word
    sung in the pre-chorus was sung as an English one (2026-11-20)."""
    provider, wire, tmp = mureka
    sections = [
        {"kind": "intro", "bars": 8, "style": "pads alone"},
        {"kind": "pre-chorus", "bars": 4, "lines": ["Juntos, one breath in"], "style": "rising"},
        {"kind": "chorus", "bars": 8, "lines": ["Hold the light"]},
    ]
    style = 'house, pronounce "juntos" as "HOON-tohs"'
    req = SongRequest(lyrics="", dst=tmp / "s.wav", style=style, duration=180, bpm=120,
                      sections=sections, pronounce={"juntos": "HOON-tohs"})  # fmt: skip
    provider.song(req, context(model="elevenlabs/music/v2.5"))
    intro, pre, chorus = wire.sent[-1]["payload"]["composition_plan"]["chunks"]
    assert pre["positive_styles"] == ["rising", 'pronounce "juntos" as "HOON-tohs"']
    assert intro["positive_styles"] == ["pads alone", 'house, pronounce "juntos" as "HOON-tohs"']
    # a section with no note of its own keeps the style, and sings no uncommon word
    assert chorus["positive_styles"] == ['house, pronounce "juntos" as "HOON-tohs"']


def test_a_hint_is_keyed_into_the_request_only_when_a_song_has_one(tmp_path):
    plain = SongRequest(lyrics="w", dst=tmp_path / "s.wav", style="house")
    said = SongRequest(lyrics="w", dst=tmp_path / "s.wav", style="house", pronounce={"a": "b"})
    assert "pronounce" not in plain._shape()[1]
    assert plain.key() != said.key()
