"""Kinetic captions drawn as a transparent layer, cards as shots, and where the type may sit."""

from __future__ import annotations

import json
import re
import shutil

import numpy as np
import pytest

from kalainova import assets, config, edit, media, qachecks, render
from kalainova.jobfs import ContractError, Job
from kalainova.providers import base
from kalainova.render import drawn, spec

HAVE_FFMPEG = shutil.which("ffmpeg") is not None
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg not installed")

CARDS = [
    {
        "start_sec": 0.5,
        "end_sec": 1.7,
        "text": "one two three",
        "words": [
            {"text": "one", "start_sec": 0.5, "end_sec": 0.9},
            {"text": "two", "start_sec": 0.9, "end_sec": 1.3},
            {"text": "three", "start_sec": 1.3, "end_sec": 1.7},
        ],
        "emphasis": ["two"],
    }
]
ZONE = [0.55, 0.72, 0.15]


class FakeGraphics(base.Provider):
    """Stands in for the graphics provider: a transparent layer with one white box in it."""

    name = "fake-graphics"
    capabilities = ("graphics",)
    free = True
    calls: list[dict] = []

    def graphics(self, folder, dst, **kw):
        page = (folder / "index.html").read_text()
        FakeGraphics.calls.append({"page": page, "fps": kw.get("fps"), "dst": dst.name})
        w, h = (int(x) for x in re.search(r'data-width="(\d+)" data-height="(\d+)"', page).groups())
        seconds = float(re.search(r'data-duration="([\d.]+)"', page).group(1))
        rate = kw.get("fps") or 30
        media.run(
            ["-f", "lavfi", "-i", f"color=c=black@0.0:s={w}x{h}:d={seconds}:r={rate},format=rgba",
             "-f", "lavfi", "-i", f"color=c=white:s=200x200:d={seconds}:r={rate},format=rgba",
             "-filter_complex", "[0][1]overlay=100:100:format=auto,format=yuva420p",
             "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-auto-alt-ref", "0", str(dst)]
        )  # fmt: skip
        return base.Result(path=dst, model="fake-graphics")


@pytest.fixture
def graphics(monkeypatch):
    FakeGraphics.calls = []
    monkeypatch.setattr(drawn, "_provider", lambda: FakeGraphics())
    return FakeGraphics


def _job(tmp_path, monkeypatch, profile="short-9x16", brief=None, edit_opts=None):
    monkeypatch.setenv("KALAINOVA_OUT", str(tmp_path / "out"))
    for key in ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "FAL_KEY"):
        monkeypatch.delenv(key, raising=False)
    folder = tmp_path / "jobs" / "kin"
    folder.mkdir(parents=True)
    data = {
        "schema_version": "0.1",
        "job_id": "kin",
        "strategy": "generated",
        "media": ["video", "audio"],
        "rights": "owned",
        "distribution_identity": "test",
        "status": "draft",
        "skip_funded": True,
        "cost_cap": 0,
        "profile": profile,
        "brief": {"subject": "test", "duration_sec": 6, **(brief or {})},
    }
    if edit_opts:
        data["edit"] = edit_opts
    (folder / "job.json").write_text(json.dumps(data))
    beats = [
        {"id": "b1", "role": "hook", "text": "A first line of speech.", "on_screen": "Title"},
        {"id": "b2", "role": "payoff", "text": "And a second line follows it."},
    ]
    (folder / "script_packet.json").write_text(
        json.dumps({"schema_version": "0.1", "job_id": "kin", "beats": beats})
    )
    job = Job(folder)
    assets.run(job)
    return job


def _manifest(job):
    edit.run(job)
    return json.loads(job.path("edit_manifest").read_text())


# ---------------------------------------------------------------- routing
@needs_ffmpeg
def test_a_brief_that_asks_for_kinetic_captions_routes_a_short_to_the_graphics_layer(
    tmp_path, monkeypatch
):
    job = _job(tmp_path, monkeypatch, brief={"captions": "kinetic"})
    em = _manifest(job)
    assert em["caption_style"] == "drawn"
    assert em["profile"]["safe_zone"] == config.safe_zone("short-9x16")
    render.compile_plan(job)
    plan = json.loads(job.path("render_plan").read_text())
    step = next(s for s in plan["steps"] if s["op"] == "burn_captions")
    assert step["args"]["style"] == "drawn"
    assert step["args"]["zone"] == [0.55, 0.72, 0.15]
    assert step["args"]["fps"] == em["profile"]["fps"]


@needs_ffmpeg
def test_without_the_brief_a_short_keeps_the_libass_captions(tmp_path, monkeypatch):
    job = _job(tmp_path, monkeypatch)
    em = _manifest(job)
    assert em["caption_style"] == "studio" and "safe_zone" not in em["profile"]


@needs_ffmpeg
def test_a_film_profile_burns_nothing_even_when_asked_and_keeps_its_sidecars(
    tmp_path, monkeypatch, graphics
):
    job = _job(tmp_path, monkeypatch, profile="film-hd", brief={"captions": "kinetic"})
    em = _manifest(job)
    assert em["caption_style"] == "none"
    render.compile_plan(job)
    plan = json.loads(job.path("render_plan").read_text())
    ops = [s["op"] for s in plan["steps"]]
    assert "burn_captions" not in ops and "caption_files" in ops
    assert graphics.calls == []


@needs_ffmpeg
def test_an_explicit_edit_caption_style_wins_over_the_brief(tmp_path, monkeypatch):
    job = _job(
        tmp_path,
        monkeypatch,
        brief={"captions": "kinetic"},
        edit_opts={"caption_style": "kinetic"},
    )
    assert _manifest(job)["caption_style"] == "kinetic"


def test_the_burn_step_accepts_the_drawn_style_and_nothing_else_new():
    args = {
        "input": "a.mp4",
        "out": "b.mp4",
        "width": 1080,
        "height": 1920,
        "style": "drawn",
        "captions": [],
        "fps": 30,
        "zone": [0.55, 0.72, 0.15],
    }
    assert spec.coerce("burn_captions", args, 0)["style"] == "drawn"
    with pytest.raises(ContractError, match="unknown args"):
        spec.coerce("burn_captions", {**args, "shell": "x"}, 0)


# ---------------------------------------------------------------- the composition
def _tween_times(page, selector):
    pattern = rf'tl\.set\("{re.escape(selector)}", \{{color: "[^"]+"\}}, ([\d.]+)\)'
    return [float(x) for x in re.findall(pattern, page)]


def test_word_timings_reach_the_composition_unchanged():
    page, _ = drawn.caption_composition(CARDS, 1080, 1920, 4.0, 30, ZONE)
    assert _tween_times(page, "#g0w0")[0] == 0.5
    assert _tween_times(page, "#g0w1")[0] == 0.9
    assert _tween_times(page, "#g0w2")[0] == 1.3
    assert 'data-start="0.5" data-duration="1.2"' in page
    for word in ("ONE", "TWO", "THREE"):
        assert f">{word}<" in page


def test_the_layer_is_transparent_and_declares_the_profile_size_and_rate():
    page, _ = drawn.caption_composition(CARDS, 1080, 1920, 4.0, 29.97, ZONE)
    assert "background: transparent" in page
    assert 'data-width="1080" data-height="1920"' in page and 'data-fps="29.97"' in page
    assert "Math.random" not in page and "Date.now" not in page


def test_type_stays_in_the_caption_band_and_out_of_the_right_margin():
    long = {
        "start_sec": 0,
        "end_sec": 3,
        "text": "x",
        "words": [
            {"text": w, "start_sec": i * 0.3, "end_sec": i * 0.3 + 0.3}
            for i, w in enumerate("extraordinarily considerate neighbours gather quietly".split())
        ],
    }
    page, report = drawn.caption_composition([long, *CARDS], 1080, 1920, 4.0, 30, ZONE)
    assert report["zone"] == ZONE
    for box in report["boxes"]:
        assert 0.55 <= box["top"] and box["bottom"] <= 0.72 and box["right"] <= 0.85
    width = int(re.search(r"\.cap \{ position: absolute; left: (\d+)px; width: (\d+)px", page)[2])
    left = int(re.search(r"\.cap \{ position: absolute; left: (\d+)px", page)[1])
    assert left + width <= 1080 * 0.85


def test_a_zone_that_is_not_a_band_is_refused():
    with pytest.raises(ContractError, match="not a band"):
        drawn.band([0.8, 0.5, 0.1])


def test_text_in_a_caption_is_escaped():
    card = {"start_sec": 0, "end_sec": 1, "text": "<b>", "words": [
        {"text": "<script>", "start_sec": 0, "end_sec": 1}]}  # fmt: skip
    page, _ = drawn.caption_composition([card], 1080, 1920, 2.0, 30, ZONE)
    assert "<script>" not in page.split("</style>")[1].split("<script>")[0]
    assert "&lt;SCRIPT&gt;" in page


# ---------------------------------------------------------------- the render
@needs_ffmpeg
def test_a_rendered_short_keeps_the_profile_size_rate_and_colour_tags(
    tmp_path, monkeypatch, graphics
):
    job = _job(tmp_path, monkeypatch, brief={"captions": "kinetic"})
    _manifest(job)
    render.compile_plan(job)
    out = render.execute(job)
    prof = config.profile("short-9x16")
    info = media.summarize(out)
    assert (info["width"], info["height"]) == (prof["width"], prof["height"])
    assert info["fps"] == pytest.approx(prof["fps"], abs=0.05)
    stream = next(s for s in media.probe(out)["streams"] if s["codec_type"] == "video")
    assert stream.get("color_space") == "bt709" and stream.get("color_transfer") == "bt709"
    assert stream.get("color_primaries") == "bt709"
    assert len(graphics.calls) == 1
    assert graphics.calls[0]["fps"] == pytest.approx(prof["fps"], abs=0.5)
    assert not (job.work / "captions.ass").exists()  # nothing went through libass
    report = json.loads((job.work / "captions.drawn.json").read_text())
    assert report["zone"] == [0.55, 0.72, 0.15]


@needs_ffmpeg
def test_the_layer_lands_over_the_picture_and_the_rest_of_the_picture_is_untouched(
    tmp_path, monkeypatch, graphics
):
    job = _job(tmp_path, monkeypatch, brief={"captions": "kinetic"})
    _manifest(job)
    render.compile_plan(job)
    render.execute(job)
    before = media.decode_gray(job.work / "picture.mp4", width=270)[2]
    after = media.decode_gray(job.work / "picture.cap.mp4", width=270)[2]
    corner = (slice(40, 70), slice(25, 70))  # where the fake layer drew a white box
    assert after[corner].mean() > 200
    elsewhere = (slice(150, 400), slice(100, 250))
    assert np.abs(after[elsewhere].astype(int) - before[elsewhere].astype(int)).mean() < 2


@needs_ffmpeg
def test_with_no_runtime_for_the_graphics_provider_the_render_says_so(tmp_path, monkeypatch):
    class Missing(FakeGraphics):
        def available(self):
            return False

        def missing_env(self):
            return ["npx (Node 22 or newer)"]

    monkeypatch.setattr(drawn, "_provider", lambda: Missing())
    job = _job(tmp_path, monkeypatch, brief={"captions": "kinetic"})
    _manifest(job)
    render.compile_plan(job)
    with pytest.raises(ContractError, match="npx"):
        render.execute(job)


# ---------------------------------------------------------------- the warning
def test_drawn_captions_outside_the_band_warn_and_inside_it_pass(tmp_path):
    job = Job.__new__(Job)
    job.folder = tmp_path
    path = tmp_path / "captions.drawn.json"
    zone = config.safe_zone("short-9x16")
    inside = {"boxes": [{"top": 0.58, "bottom": 0.68, "right": 0.85}]}
    path.write_text(json.dumps(inside))
    assert qachecks._drawn_caption_check(path, zone)[0]["status"] == "pass"
    outside = {"boxes": [{"top": 0.58, "bottom": 0.82, "right": 0.95}]}
    path.write_text(json.dumps(outside))
    found = qachecks._drawn_caption_check(path, zone)[0]
    assert found["id"] == "safe_zone.drawn" and found["status"] == "warn"
    assert qachecks._drawn_caption_check(tmp_path / "none.json", zone) == []


# ---------------------------------------------------------------- cards
@pytest.mark.parametrize(
    ("kind", "fields", "shows"),
    [
        ("title", {"text": "A <b>title</b>", "sub": "under it"}, ["A &lt;b&gt;title&lt;/b&gt;"]),
        ("quote", {"text": "Said once", "sub": "someone"}, ["&ldquo;Said once&rdquo;", "someone"]),
        ("stat", {"value": "42%", "label": "of things"}, ["of things", "toFixed(0)"]),
    ],
)
def test_each_card_kind_is_a_full_frame_composition_that_moves(kind, fields, shows):
    page = drawn.card_composition(kind, fields, 1080, 1920, 5.0)
    assert 'data-width="1080" data-height="1920"' in page and 'data-duration="5"' in page
    assert 'tl.fromTo("#bg"' in page  # a slow move under every hold
    for fragment in shows:
        assert fragment in page


def test_a_card_missing_a_required_field_or_of_an_unknown_kind_is_refused():
    with pytest.raises(ContractError, match="needs value, label"):
        drawn.card_composition("stat", {"value": ""}, 1080, 1920, 3.0)
    with pytest.raises(ContractError, match="card kind"):
        drawn.card_composition("poster", {"text": "x"}, 1080, 1920, 3.0)


def test_a_written_card_carries_the_vendored_font_and_no_subject(tmp_path):
    out = drawn.write_card(tmp_path / "graphics" / "b1", "title", {"text": "Hello"}, 1080, 1920, 4)
    assert out.name == "index.html"
    assert (out.parent / "assets" / "fonts" / drawn.FACE).exists()


def test_the_engine_ships_no_text_of_its_own_in_the_layer():
    page, _ = drawn.caption_composition([], 1080, 1920, 3.0, 30, ZONE)
    body = page.split('<div id="root"', 1)[1].split("</div>", 1)[0]
    assert "<span" not in body
