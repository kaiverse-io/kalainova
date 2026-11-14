"""Issue #100: hold a kit's voice as owned reference recordings, not just a single sample."""

from __future__ import annotations

import pytest

from kalainova import kits
from kalainova.__main__ import main
from kalainova.jobfs import ContractError, validate


def _audio(root, name="voice.wav"):
    path = root / name
    path.write_bytes(b"not really audio, just bytes for the trial")
    return path


def test_add_voice_reference_with_owned_rights_succeeds(root):
    kits.new(root, "lead")
    kit_folder = kits.draft_path(root, "lead").parent
    audio = _audio(root)

    dest = kits.add_voice_reference(kit_folder, audio, rights="owned", transcript="hello there")

    assert dest == kit_folder / "voice_references" / "voice.wav"
    assert dest.read_bytes() == audio.read_bytes()

    kit = kits.read_draft(root, "lead")
    refs = kit["voice"]["references"]
    assert refs == [
        {"file": "voice_references/voice.wav", "rights": "owned", "transcript": "hello there"}
    ]


def test_add_voice_reference_initializes_voice_when_absent(root):
    kits.new(root, "lead")
    kit_folder = kits.draft_path(root, "lead").parent
    audio = _audio(root)

    kits.add_voice_reference(kit_folder, audio, rights="licensed")

    kit = kits.read_draft(root, "lead")
    assert kit["voice"]["references"][0]["rights"] == "licensed"
    assert "transcript" not in kit["voice"]["references"][0]


def test_add_voice_reference_appends_to_existing_references(root):
    kits.new(root, "lead")
    kit_folder = kits.draft_path(root, "lead").parent
    kits.add_voice_reference(kit_folder, _audio(root, "one.wav"), rights="owned")
    kits.add_voice_reference(kit_folder, _audio(root, "two.wav"), rights="funded-brief")

    kit = kits.read_draft(root, "lead")
    files = [r["file"] for r in kit["voice"]["references"]]
    assert files == ["voice_references/one.wav", "voice_references/two.wav"]


def test_kit_json_schema_validation_succeeds_with_voice_references(root):
    kits.new(root, "lead")
    kit_folder = kits.draft_path(root, "lead").parent
    kits.add_voice_reference(kit_folder, _audio(root), rights="owned", transcript="a line")

    kit = kits.read_draft(root, "lead")
    validate("kit", kit)  # raises on any schema violation


def test_invalid_rights_refuses(root):
    kits.new(root, "lead")
    kit_folder = kits.draft_path(root, "lead").parent
    audio = _audio(root)

    with pytest.raises(ContractError, match="rights"):
        kits.add_voice_reference(kit_folder, audio, rights="stolen")

    assert not (kit_folder / "voice_references").exists()
    kit = kits.read_draft(root, "lead")
    assert "voice" not in kit


def test_add_voice_reference_needs_a_real_file(root):
    kits.new(root, "lead")
    kit_folder = kits.draft_path(root, "lead").parent

    with pytest.raises(ContractError, match="no file at"):
        kits.add_voice_reference(kit_folder, root / "missing.wav")


def test_cli_wires_kit_voice_ref(root, capsys):
    kits.new(root, "lead")
    audio = _audio(root)

    argv = ["kit", "voice-ref", "lead", str(audio), "--rights", "owned", "--transcript", "hi"]
    assert main(argv) == 0

    out = capsys.readouterr().out
    assert "lead" in out
    assert "voice_references/voice.wav" in out

    kit = kits.read_draft(root, "lead")
    assert kit["voice"]["references"][0] == {
        "file": "voice_references/voice.wav",
        "rights": "owned",
        "transcript": "hi",
    }


def test_cli_kit_voice_ref_rejects_bad_rights(root):
    kits.new(root, "lead")
    audio = _audio(root)

    with pytest.raises(SystemExit):
        main(["kit", "voice-ref", "lead", str(audio), "--rights", "stolen"])
