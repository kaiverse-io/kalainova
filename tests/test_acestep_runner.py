"""The ACE-Step runner against the model package's own parameter names.

CI does not install ACE-Step, so these tests run the real runner script against a stand-in package
whose GenerationParams has exactly the fields of ace-step 1.5.0. A keyword the package does not
take fails here the way it fails on a Mac: a runner once passed `src_audio_path`, and every song
take raised TypeError after the model had loaded.
"""

from __future__ import annotations

import json
import runpy
import sys

import pytest

from kalainova.providers import mac

# dataclasses.fields(acestep.inference.GenerationParams) in ace-step 1.5.0
ACESTEP_1_5_PARAMS = (
    "task_type instruction reference_audio src_audio audio_codes caption global_caption lyrics "
    "instrumental vocal_language bpm keyscale timesignature duration enable_normalization "
    "normalization_db fade_in_duration fade_out_duration latent_shift latent_rescale "
    "inference_steps seed guidance_scale use_adg cfg_interval_start cfg_interval_end shift "
    "infer_method sampler_mode velocity_norm_threshold velocity_ema_factor dcw_enabled dcw_mode "
    "dcw_scaler dcw_high_scaler dcw_wavelet timesteps repainting_start repainting_end "
    "chunk_mask_mode repaint_latent_crossfade_frames repaint_wav_crossfade_sec repaint_mode "
    "repaint_strength retake_seed retake_variance flow_edit_morph flow_edit_source_caption "
    "flow_edit_source_lyrics flow_edit_n_min flow_edit_n_max flow_edit_n_avg audio_cover_strength "
    "cover_noise_strength thinking lm_temperature lm_cfg_scale lm_top_k lm_top_p "
    "lm_negative_prompt use_cot_metas use_cot_caption use_cot_lyrics use_cot_language "
    "use_constrained_decoding cot_bpm cot_keyscale cot_timesignature cot_duration "
    "cot_vocal_language cot_caption cot_lyrics"
).split()
ACESTEP_1_5_CONFIG = (
    "batch_size allow_lm_batch use_random_seed seeds lm_batch_chunk_size "
    "constrained_decoding_debug audio_format mp3_bitrate mp3_sample_rate"
).split()

INFERENCE = """
import dataclasses, json, os
from pathlib import Path

GenerationParams = dataclasses.make_dataclass(
    "GenerationParams", [(name, object, dataclasses.field(default=None)) for name in {params}]
)
GenerationConfig = dataclasses.make_dataclass(
    "GenerationConfig", [(name, object, dataclasses.field(default=None)) for name in {config}]
)


class Result:
    def __init__(self, path):
        self.success, self.error, self.audios = True, "", [{{"path": path}}]


def generate_music(dit, llm, params, config, save_dir=None, progress=None):
    Path(os.environ["FAKE_ACESTEP_SEEN"]).write_text(json.dumps(dataclasses.asdict(params)))
    out = Path(save_dir) / "take.wav"
    out.write_bytes(b"RIFF")
    return Result(str(out))
"""

HANDLER = """
import os
from pathlib import Path


class AceStepHandler:
    def initialize_service(self, project_root, config_path, device="auto", **kw):
        Path(os.environ["FAKE_ACESTEP_LOADED"]).write_text("loaded")
        return "ok", True
"""


@pytest.fixture
def runner(tmp_path, monkeypatch):
    """Run the real runner script against the stand-in package; return what it asked for."""
    pkg = tmp_path / "site" / "acestep"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "handler.py").write_text(HANDLER)
    (pkg / "inference.py").write_text(
        INFERENCE.format(params=ACESTEP_1_5_PARAMS, config=ACESTEP_1_5_CONFIG)
    )
    monkeypatch.syspath_prepend(str(tmp_path / "site"))
    monkeypatch.delenv("ACESTEP_LM_MODEL", raising=False)
    seen, loaded = tmp_path / "seen.json", tmp_path / "loaded"
    monkeypatch.setenv("FAKE_ACESTEP_SEEN", str(seen))
    monkeypatch.setenv("FAKE_ACESTEP_LOADED", str(loaded))
    for name in [m for m in sys.modules if m == "acestep" or m.startswith("acestep.")]:
        monkeypatch.delitem(sys.modules, name)
    (tmp_path / "lyrics.txt").write_text("[verse]\nla la")
    (tmp_path / "tags.txt").write_text("warm, acoustic")

    def run(*extra: str) -> dict:
        argv = [
            "acestep_run.py",
            "--checkpoint", str(tmp_path),
            "--lyrics", str(tmp_path / "lyrics.txt"),
            "--tags", str(tmp_path / "tags.txt"),
            "--seconds", "20",
            "--out", str(tmp_path / "out.wav"),
            *extra,
        ]  # fmt: skip
        monkeypatch.setattr(sys, "argv", argv)
        runpy.run_path(str(mac.SONG_RUNNERS["ace-step"]), run_name="__main__")
        return json.loads(seen.read_text())

    run.loaded = loaded  # type: ignore[attr-defined]  # the test asks whether a model was loaded
    run.folder = tmp_path  # type: ignore[attr-defined]  # where the source file for a repaint goes
    return run


def test_a_text_to_music_take_uses_only_names_the_package_takes(runner):
    params = runner()
    assert params["task_type"] == "text2music"
    assert params["src_audio"] is None
    assert params["repainting_start"] is None and params["repainting_end"] is None
    assert (runner.folder / "out.wav").is_file()


def test_a_repaint_names_its_source_and_span_the_way_the_package_does(runner):
    source = runner.folder / "chosen.wav"
    source.write_bytes(b"RIFF")
    params = runner(
        "--task-type", "repaint", "--src-audio", str(source),
        "--repainting-start", "32", "--repainting-end", "48",
    )  # fmt: skip
    assert params["task_type"] == "repaint"
    assert params["src_audio"] == str(source)
    assert (params["repainting_start"], params["repainting_end"]) == (32.0, 48.0)


@pytest.mark.parametrize(
    "extra",
    [
        ("--task-type", "repaint"),
        ("--task-type", "repaint", "--src-audio", "missing.wav", "--repainting-end", "8"),
    ],
)
def test_a_repaint_with_no_source_stops_before_any_model_loads(runner, extra):
    with pytest.raises(SystemExit, match="repaint needs"):
        runner(*extra)
    assert not runner.loaded.exists()


def test_a_repaint_whose_span_ends_before_it_starts_stops_before_any_model_loads(runner):
    source = runner.folder / "chosen.wav"
    source.write_bytes(b"RIFF")
    with pytest.raises(SystemExit, match="repainting-end"):
        runner(
            "--task-type", "repaint", "--src-audio", str(source),
            "--repainting-start", "40", "--repainting-end", "10",
        )  # fmt: skip
    assert not runner.loaded.exists()
