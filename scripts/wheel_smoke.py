"""Run inside a fresh environment that has only the built wheel: the engine must know everything a
checkout knows (ADR 0027). Started by scripts/check_wheel.py with `python -I`, from an empty folder.
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    import kalainova
    from kalainova import captions, config, fingerprint, jobfs, prompts, resources, shots
    from kalainova.jobfs import ContractError
    from kalainova.providers import fal_sing
    from kalainova.providers.contract import SingRequest

    here = Path(kalainova.__file__).resolve()
    assert "site-packages" in here.parts, f"imported from {here}, not the installed wheel"
    assert not resources.in_checkout(), "the installed copy thinks it is a checkout"
    assert resources.root() == here.parent / "_data", resources.root()

    names = sorted(p.stem for p in resources.path("prompts").glob("*.md") if p.stem != "README")
    assert names, "no prompts shipped"
    for name in names:
        assert prompts.load(name).strip(), f"prompt {name} is empty"
    assert config.studio().get("sing_models"), "the default config did not ship"
    assert jobfs.load_schema("job").get("properties"), "the job schema did not ship"
    assert any(captions.FONTS.glob("*.ttf")) or any(captions.FONTS.glob("*.otf")), "no fonts"
    assert (resources.path("jobs", "_template") / "job.json").is_file(), "no job template"
    assert shots.performance("sing"), "no direction for a sung shot"
    assert fingerprint.code_stamp().startswith("v"), fingerprint.code_stamp()
    assert "site-packages" not in jobfs.default_home().parts, jobfs.default_home()

    spec = config.studio()["sing_models"]["fal"]["bytedance/omnihuman/v2"]
    ask = SingRequest(prompt="x" * 301, still=Path("s.png"), audio=Path("l.wav"),
                      dst=Path("o.mp4"), aspect="9:16")  # fmt: skip
    try:
        fal_sing.payload(spec, ask, "still", "line", [], "")
    except ContractError:
        pass
    else:
        raise AssertionError("a 301-character prompt to a 300-character model was not refused")
    print(f"installed wheel ok: {len(names)} prompts, engine {fingerprint.code_stamp()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
