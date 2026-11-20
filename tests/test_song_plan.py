"""A song take read against its own plan: the energy the writer planned for each section, a voice
only where there are words, the key asked for, and the uncommon words where they are sung."""

from __future__ import annotations

import json
import wave

import numpy as np
import pytest
from fakes import make_job, needs_ffmpeg

from kalainova import song_lead
from kalainova.bar import plan
from kalainova.editor import beats

pytestmark = needs_ffmpeg
SR = beats.SR
BPM = 120  # a bar of four beats is 2 s


def _song(sections, **extra):
    return {"title": "T", "style": "house", "bpm": BPM, "sections": sections, **extra}


def _noise(levels, bar_sec=2.0, bars=4, seed=1):
    rng = np.random.default_rng(seed)
    return np.concatenate([lv * rng.standard_normal(int(SR * bar_sec * bars)) for lv in levels])


def _wav(path, pcm):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1), out.setsampwidth(2), out.setframerate(SR)
        out.writeframes((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
    return path


ARC = [{"kind": "intro", "bars": 4, "energy": 1}, {"kind": "verse", "bars": 4, "energy": 3},
       {"kind": "chorus", "bars": 4, "energy": 5}]  # fmt: skip


def test_a_take_that_follows_its_planned_arc_raises_no_card():
    rho, cards = plan.energy_cards(plan.profile(_noise([0.02, 0.1, 0.4]), _song(ARC)), _song(ARC))
    assert rho == pytest.approx(1.0) and cards == []


def test_a_take_that_opens_at_full_weight_is_carded_where_it_misses():
    rho, cards = plan.energy_cards(plan.profile(_noise([0.4, 0.1, 0.4]), _song(ARC)), _song(ARC))
    assert rho is not None and rho <= 0.5
    assert cards[0]["section"] == "intro" and cards[0]["at"] == "0:00"  # and the verse, too quiet
    assert "energy 1 of 5" in cards[0]["planned"] and "level -0.0 dB" in cards[0]["measured"]


def test_no_energy_planned_means_no_reading():
    unplanned = [{k: v for k, v in s.items() if k != "energy"} for s in ARC]
    measured = plan.profile(_noise([0.4, 0.1, 0.4]), _song(unplanned))
    assert plan.energy_cards(measured, _song(unplanned)) == (None, [])
    assert plan.profile(_noise([0.1]), _song([{"kind": "verse"}])) == []  # no bars: not placed


def test_a_voice_where_the_plan_has_no_words_is_carded():
    sections = [{"kind": "intro", "bars": 4}, {"kind": "verse", "bars": 4, "lines": ["a"]}]
    quiet_intro = _noise([0.0005, 0.3])
    assert plan.voice_cards(quiet_intro, _song(sections)) == []
    sung_intro = _noise([0.3, 0.3])
    (card,) = plan.voice_cards(sung_intro, _song(sections))
    assert card["section"] == "intro" and card["planned"] == "no words"
    silent_verse = _noise([0.3, 0.0005])
    assert plan.voice_cards(silent_verse, _song([sections[1], {**sections[1], "kind": "chorus"}]))


def _chord(names, sec=6.0):
    t = np.arange(int(SR * sec)) / SR
    hz = {"A": 220.0, "C": 261.63, "E": 329.63, "F": 174.61, "Ab": 207.65, "G": 196.0}
    return sum(0.2 * np.sin(2 * np.pi * hz[n] * t) for n in names)


def test_the_key_heard_is_read_and_a_far_one_is_carded():
    a_minor = np.concatenate([_chord(["A", "C", "E"]), _chord(["A", "E"]), _chord(["A", "C"])])
    best = plan.key_fits(a_minor)[0][1]
    assert best in ("A minor", "C major")  # a chord's notes are shared with its relative key
    match, cards = plan.key_cards(a_minor, _song([], key="A minor"))
    assert match in (1.0, 0.5) and cards == []
    match, (card,) = plan.key_cards(a_minor, _song([], key="F# major"))
    assert match == 0.0 and card["planned"] == "F# major"


@pytest.mark.parametrize(
    ("asked", "heard", "match"),
    [("A minor", "A minor", 1.0), ("A minor", "C major", 0.5), ("C major", "A minor", 0.5),
     ("Bb major", "A# major", 1.0), ("F minor", "F major", 0.0), ("Am", "A minor", 1.0),
     ("in a mood", "A minor", None)],
)  # fmt: skip
def test_a_key_matches_itself_its_relative_and_its_other_spellings(asked, heard, match):
    assert plan.key_match(asked, heard) == match


def _heard(words):
    return [{"start_sec": at, "end_sec": at + 0.3, "text": w} for at, w in words]


SUNG = [{"kind": "verse", "bars": 4, "lines": ["Wave the lantern, amigos, adelante"]},
        {"kind": "chorus", "bars": 4, "lines": ["Bonne nuit, the lamp on the stair"]}]  # fmt: skip


def test_an_uncommon_word_not_heard_where_it_is_sung_is_carded_with_what_was_heard():
    song = _song(SUNG, pronounce={"adelante": "ah-deh-LAHN-teh", "nuit": "nwee"})
    heard = _heard([(1, "Wave"), (1.5, "the"), (2, "lantern,"), (3, "atlanta"), (9, "Bonne"),
                    (9.4, "Nwee,"), (10, "lamp"), (11, "stair")])  # fmt: skip
    (card,) = plan.pronounce_cards(song, heard)
    assert card["section"] == "verse" and '"adelante"' in card["planned"]
    assert "atlanta" in card["measured"]  # "nuit" heard as "Nwee" is the word said right


def test_a_section_whose_words_were_mostly_not_heard_there_is_carded():
    heard = _heard([(9, "Bonne"), (10, "lamp"), (11, "stair")])  # the verse's words never come
    (card,) = plan.words_cards(_song(SUNG), heard)
    assert card["section"] == "verse" and "lantern" in card["measured"]


def test_a_fresh_draft_gives_every_section_its_energy(tmp_path):
    job = make_job(tmp_path, media=["song"])
    draft = _song([{"kind": "verse", "bars": 4, "lines": ["a"]}], concept="c", title="New")
    assert any("energy" in p for p in song_lead.problems(job, draft))
    planned = {**draft, "sections": [{**draft["sections"][0], "energy": 3}]}
    assert not any("energy" in p for p in song_lead.problems(job, planned))


def test_a_take_is_read_against_its_plan_and_carded_by_command(tmp_path, studio, monkeypatch):
    from kalainova import songs
    from kalainova.__main__ import main

    monkeypatch.setenv("KALAINOVA_HOME", str(tmp_path))
    job = make_job(tmp_path, media=["song"])
    verse = {"kind": "verse", "bars": 2, "lines": ["Paper boats on the floor"], "energy": 2}
    chorus = {"kind": "chorus", "bars": 2, "lines": ["Hold the ladder"], "energy": 5}
    sections = [{"kind": "intro", "bars": 2, "energy": 1}, verse, chorus]
    song = {"schema_version": "0.1", "job_id": job.id, "title": "T", "style": "pop", "bpm": BPM,
            "key": "C major", "duration_sec": 12, "sections": sections}  # fmt: skip
    job.write("song", song)
    songs.run(job)
    take = json.loads(job.path("takes").read_text())["shots"]["song"]["takes"][0]
    ids = [r["id"] for r in take["readings"]["readings"]]
    assert "song.energy_follows_plan" in ids and "song.key_match" in ids
    assert main(["song-check", job.id]) == 0
    assert (job.work / take["file"]).with_suffix(".cards.json").exists()
    measured = json.loads((job.work / take["file"]).with_suffix(".groove.json").read_text())
    assert "kick_enters_sec" in measured  # the groove is read beside the plan
