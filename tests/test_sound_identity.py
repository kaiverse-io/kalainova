"""Issue #61: a fixed sound identity per stream, checked against a rendered track."""

from __future__ import annotations

import json

from kalainova.sound_identity import SoundIdentity, check_track, load_sound_identity


def test_load_sound_identity_from_dict():
    identity = load_sound_identity(
        {
            "name": "late-night-act",
            "tempo_range": [90.0, 130.0],
            "keys": ["C minor", "G minor"],
            "drum_kit": "808-warm",
            "target_lufs": -13.0,
            "true_peak_dbtp_max": -1.5,
        }
    )

    assert identity == SoundIdentity(
        name="late-night-act",
        tempo_range=(90.0, 130.0),
        keys=["C minor", "G minor"],
        drum_kit="808-warm",
        target_lufs=-13.0,
        true_peak_dbtp_max=-1.5,
    )


def test_load_sound_identity_defaults_when_fields_omitted():
    identity = load_sound_identity({"name": "bare-act"})

    assert identity == SoundIdentity(name="bare-act")


def test_load_sound_identity_from_json_file(tmp_path):
    path = tmp_path / "identity.json"
    path.write_text(
        json.dumps(
            {
                "name": "file-act",
                "tempo_range": [100.0, 120.0],
                "keys": ["A minor"],
                "drum_kit": "acoustic-kit",
                "target_lufs": -14.0,
                "true_peak_dbtp_max": -1.0,
            }
        )
    )

    identity = load_sound_identity(path)

    assert identity.name == "file-act"
    assert identity.tempo_range == (100.0, 120.0)
    assert identity.keys == ["A minor"]


def _identity():
    return SoundIdentity(
        name="late-night-act",
        tempo_range=(90.0, 130.0),
        keys=["C minor", "G minor"],
        drum_kit="808-warm",
        target_lufs=-14.0,
    )


def test_check_track_passes_when_metadata_matches_identity():
    checks = check_track({"bpm": 110.0, "key": "C minor", "lufs": -14.5}, _identity())

    assert {c["id"] for c in checks} == {"sound.tempo", "sound.key", "sound.loudness"}
    assert all(c["status"] == "pass" for c in checks)


def test_check_track_warns_on_tempo_outside_range():
    checks = check_track({"bpm": 170.0, "key": "C minor", "lufs": -14.0}, _identity())

    tempo = next(c for c in checks if c["id"] == "sound.tempo")
    assert tempo["status"] == "warn"
    assert "170.0" in tempo["detail"]


def test_check_track_warns_on_key_not_in_identity():
    checks = check_track({"bpm": 110.0, "key": "F# major", "lufs": -14.0}, _identity())

    key_check = next(c for c in checks if c["id"] == "sound.key")
    assert key_check["status"] == "warn"
    assert "F# major" in key_check["detail"]


def test_check_track_warns_on_loudness_deviation():
    checks = check_track({"bpm": 110.0, "key": "C minor", "lufs": -20.0}, _identity())

    loudness = next(c for c in checks if c["id"] == "sound.loudness")
    assert loudness["status"] == "warn"
    assert "-20.0" in loudness["detail"]


def test_check_track_ignores_key_when_identity_has_no_keys():
    identity = SoundIdentity(name="no-keys-act")

    checks = check_track({"bpm": 110.0, "key": "anything", "lufs": -14.0}, identity)

    key_check = next(c for c in checks if c["id"] == "sound.key")
    assert key_check["status"] == "pass"
