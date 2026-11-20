"""The groove a take was asked for, read off synthetic audio: when the kick enters, a kick where
the plan keeps it out, a build that rises or does not, and Longuet-Higgins and Lee syncopation."""

from __future__ import annotations

import numpy as np
import pytest

from kalainova.bar import groove
from kalainova.editor import beats

SR = beats.SR
BPM = 120  # a beat is 0.5 s, a bar 2 s


def _kick(seconds: float, from_sec: float = 0.0, until: float | None = None) -> np.ndarray:
    """A 55 Hz thump on every beat between two times, over a quiet bed."""
    rng = np.random.default_rng(3)
    pcm = 0.002 * rng.standard_normal(int(SR * seconds))
    t = np.arange(int(SR * 0.12)) / SR
    hit = 0.8 * np.sin(2 * np.pi * 55 * t) * np.exp(-t * 30)
    at = from_sec
    while at < (until if until is not None else seconds) - 0.12:
        i = int(at * SR)
        pcm[i : i + hit.size] += hit
        at += 60 / BPM
    return pcm


def _song(sections):
    return {"title": "T", "style": "house", "bpm": BPM, "sections": sections}


def test_the_kick_is_heard_entering_where_it_enters():
    assert groove.kick_enters(_kick(24, from_sec=8.0), BPM) == pytest.approx(8.0, abs=0.06)
    assert groove.kick_enters(_kick(24), BPM) == pytest.approx(0.0, abs=0.06)


def test_a_kick_in_a_section_that_keeps_it_out_is_carded():
    song = _song([{"kind": "intro", "bars": 4, "avoid": "kick, rap"},
                  {"kind": "verse", "bars": 4, "lines": ["w"]}])  # fmt: skip
    late = groove.kick_cards(_kick(16, from_sec=8.0), song)
    assert late == [], "the kick waited for the verse, as asked"
    (card,) = groove.kick_cards(_kick(16), song)
    assert card["id"] == "plan.kick" and card["section"] == "intro" and card["at"] == "0:00"
    assert card["planned"] == "keeps out the kick"


def _ramp(rising: bool, seconds: float = 8.0) -> np.ndarray:
    rng = np.random.default_rng(5)
    n = int(SR * seconds)
    level = np.linspace(0.02, 0.4, n) if rising else np.linspace(0.4, 0.02, n)
    return level * rng.standard_normal(n)


BUILD = [{"kind": "pre-chorus", "bars": 4, "energy": 2, "lines": ["w"]},
         {"kind": "chorus", "bars": 4, "energy": 5, "lines": ["w"]}]  # fmt: skip


def test_a_build_that_rises_into_the_drop_raises_no_card_and_one_that_falls_does():
    rising = np.concatenate([_ramp(True), 0.4 * np.random.default_rng(1).standard_normal(SR * 8)])
    falling = np.concatenate([_ramp(False), 0.4 * np.random.default_rng(1).standard_normal(SR * 8)])
    assert groove.build_cards(rising, _song(BUILD)) == []
    (card,) = groove.build_cards(falling, _song(BUILD))
    assert card["id"] == "plan.build" and card["section"] == "pre-chorus"
    assert "energy 2 to 5" in card["planned"]


def test_only_a_planned_build_is_read_as_one():
    verse = [{**BUILD[0], "kind": "verse"}, BUILD[1]]
    falling = np.concatenate([_ramp(False), 0.4 * np.random.default_rng(1).standard_normal(SR * 8)])
    assert groove.build_cards(falling, _song(verse)) == [], "a verse that says nothing of a build"
    said = [{**verse[0], "style": "pads swell, toms build"}, BUILD[1]]
    assert len(groove.build_cards(falling, _song(said))) == 1


def test_syncopation_follows_longuet_higgins_and_lee():
    bar = np.zeros(16, dtype=bool)
    four = bar.copy()
    four[[0, 4, 8, 12]] = True
    assert groove.syncopation(four) == 0, "notes on the beats are not syncopated"
    off = bar.copy()
    off[[2, 6, 10, 14]] = True
    # each off-beat eighth is held over the stronger place after it: +1, +2, +1, and the last
    # leads into a struck downbeat
    assert groove.syncopation(off) == 4
    push = bar.copy()
    push[[0, 7, 12]] = True  # a note just before the half bar, held over it
    assert groove.syncopation(push) == 3
    assert groove.syncopation(push, next_downbeat=False) == 3 + 2


def test_measures_read_the_kick_and_the_syncopation_per_section():
    song = _song([{"kind": "intro", "bars": 4}, {"kind": "verse", "bars": 4, "lines": ["w"]}])
    found = groove.measures(_kick(16, from_sec=8.0), song)
    assert found["kick_enters_sec"] == pytest.approx(8.0, abs=0.06)
    assert [s["section"] for s in found["sections"]] == ["intro", "verse"]
    assert groove.measures(_kick(4), {"sections": []}) == {}


def test_a_kick_from_the_first_bar_where_the_note_holds_it_back_is_carded():
    """The take that opened at full weight: its intro said "filtered arpeggio alone, kick enters
    late", and the kick struck from the first beat (2026-11-20)."""
    held = {"kind": "intro", "bars": 4, "style": "filtered arpeggio alone, kick enters late"}
    song = _song([held, {"kind": "verse", "bars": 4, "lines": ["w"]}])
    (card,) = groove.kick_cards(_kick(16), song)
    assert card["planned"] == "the kick enters late"
    assert card["measured"].startswith("a kick from its first bar")
    assert groove.kick_cards(_kick(16, from_sec=4.0), song) == [], "it came in late, as asked"
    quiet = _song([{"kind": "intro", "bars": 4, "energy": 1}, {"kind": "verse", "bars": 4}])
    assert len(groove.kick_cards(_kick(16), quiet)) == 1
