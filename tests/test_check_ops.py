"""The contract gate accepts exactly the render ops the engine runs."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from kalainova.render import spec

CHECK = Path(__file__).resolve().parents[1] / "scripts" / "check.py"


def test_the_gate_and_the_engine_agree_on_every_render_op():
    loaded = importlib.util.spec_from_file_location("kalainova_check", CHECK)
    assert loaded and loaded.loader
    module = importlib.util.module_from_spec(loaded)
    loaded.loader.exec_module(module)
    assert module.OPS == set(spec.OPS)
