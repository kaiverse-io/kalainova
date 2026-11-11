"""LOOK DEVELOPMENT: a sheet of a kit's candidate references, for a person to choose from.

A character is looked at before it is frozen. The sheet shows each candidate reference at several
framings, and, if asked, one test still per look. It is a review artefact: it reads a kit and
changes nothing in it. A person picks, and a person freezes (`kit freeze` names them); nothing here
does.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from . import kitrules, kits
from .jobfs import ContractError, Job, dump, home
from .providers import base, router
from .timeline import _label_font

CELL_HEIGHT = 240
GAP = 6
LABEL_HEIGHT = 24
# the same picture, framed three ways: as given, the upper two thirds, and close on the upper middle
FRAMINGS = (
    ("whole", (0.0, 0.0, 1.0, 1.0)),
    ("upper", (0.0, 0.0, 1.0, 0.66)),
    ("close", (0.2, 0.0, 0.8, 0.4)),
)
NOTE = "framings are crops of the reference as given, not new views; this sheet changes no kit"
TEST_PROMPT = "A plain test portrait of the character in this look, on a neutral background."


def read(root: Path, kit_id: str) -> kits.Kit:
    """The kit being developed: its draft, else its latest frozen version. Read, never changed."""
    if kits.draft_path(root, kit_id).exists():
        return kits.read_draft(root, kit_id)
    known = kits.versions(root, kit_id)
    if not known:
        raise ContractError(f"kit {kit_id} has no draft and no frozen version to look at")
    return kits.load(root, kit_id, known[-1])


def candidates(root: Path, kit: kits.Kit) -> list[tuple[str, str, Path]]:
    """Every image reference the kit holds, as (slot, label, file)."""
    out = []
    for slot, entry in kitrules.files(kit):
        if str(entry.get("suffix", "")).lower() in kitrules.IMAGE_SUFFIXES:
            label = f"{slot}  {entry.get('label') or ''}  {str(entry['sha256'])[:8]}".replace(
                "  ", " "
            )
            out.append((slot, label.strip(), kits.blob_path(root, entry)))
    return out


def _row(path: Path) -> list[Image.Image]:
    with Image.open(path) as opened:
        rgb = opened.convert("RGB")
    cells = []
    for _, (left, top, right, bottom) in FRAMINGS:
        w, h = rgb.size
        crop = rgb.crop((round(w * left), round(h * top), round(w * right), round(h * bottom)))
        scale = CELL_HEIGHT / max(crop.height, 1)
        cells.append(crop.resize((max(round(crop.width * scale), 1), CELL_HEIGHT)))
    return cells


def sheet(
    root: Path, kit_id: str, dst: Path, *, stills: list[tuple[str, Path]] | None = None
) -> Path:
    """One row of framings per candidate reference, and a row of test stills if there are any."""
    rows = [(label, _row(path)) for _, label, path in candidates(root, read(root, kit_id))]
    if stills:
        rows.append(("test stills, one per look", [_row(p)[0] for _, p in stills]))
    if not rows:
        raise ContractError(f"kit {kit_id} holds no image reference to put on a sheet")
    width = max(sum(c.width + GAP for c in cells) for _, cells in rows)
    row_h = CELL_HEIGHT + LABEL_HEIGHT + GAP
    out = Image.new("RGB", (width, row_h * len(rows) + LABEL_HEIGHT), (16, 16, 18))
    draw = ImageDraw.Draw(out)
    font = _label_font(14)
    for n, (label, cells) in enumerate(rows):
        y = n * row_h
        draw.text((6, y + 3), label, fill=(255, 255, 255), font=font)
        x = 0
        for cell in cells:
            out.paste(cell, (x, y + LABEL_HEIGHT))
            x += cell.width + GAP
        if stills and n == len(rows) - 1:
            for (name, _), at in zip(stills, _starts(cells), strict=True):
                draw.text((at + 4, y + LABEL_HEIGHT + 4), name, fill=(255, 210, 60), font=font)
    draw.text((6, row_h * len(rows) + 3), NOTE, fill=(170, 170, 170), font=font)
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst, quality=88)
    return dst


def _starts(cells: list[Image.Image]) -> list[int]:
    starts, x = [], 0
    for cell in cells:
        starts.append(x)
        x += cell.width + GAP
    return starts


def out_dir(kit_id: str) -> Path:
    return Path(os.environ.get("KALAINOVA_OUT", home() / "out")) / f"look-{kit_id}"


# ------------------------------------------------------------------ test stills (paid, opt in)
def _scratch_job(root: Path, kit_id: str, cap: float) -> Job:
    """A job of its own for the test stills, so the ledger holds their spend under a cap."""
    folder = root / "jobs" / f"look-{kit_id}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "job.json").write_text(
        dump(
            {
                "schema_version": "0.1",
                "job_id": folder.name,
                "strategy": "generated",
                "media": ["still"],
                "rights": "owned",
                "status": "draft",
                "cost_cap": cap,
                "brief": {"subject": f"look development for kit {kit_id}"},
            }
        )
        + "\n"
    )
    return Job(folder)


def _reference(root: Path, entry: dict[str, Any], label: str) -> dict[str, Any]:
    return {
        "path": kits.blob_path(root, entry),
        "sha256": entry["sha256"],
        "label": label,
        "group": "",
    }


def looks_to_test(kit: kits.Kit) -> list[tuple[str, dict[str, Any]]]:
    """Each named look, or the identity alone when the kit names none."""
    named = sorted((kit.get("looks") or {}).items())
    return [(name, owner) for name, owner in named] or [("identity", {})]


def make_test_stills(
    root: Path, kit_id: str, *, cost_cap: float, provider: str, model: str
) -> list[tuple[str, Path]]:
    """One still per look, made with the kit's references on a model that can hold a face."""
    kit = read(root, kit_id)
    refs = (kit.get("identity") or {}).get("refs") or []
    if not refs:
        raise ContractError(f"kit {kit_id} has no identity reference to test a look with")
    try:
        support = base.get(provider).reference_support("image", model)
    except KeyError as exc:
        raise ContractError(str(exc)) from exc
    if not support:
        raise ContractError(
            f"{provider}/{model} takes no reference images, so a test still would not show the "
            "character. Pick one listed under reference_models in config/studio.yaml"
        )
    job = _scratch_job(root, kit_id, cost_cap)
    made = []
    for name, owner in looks_to_test(kit):
        wanted = [_reference(root, refs[0], "the character")]
        wanted += [_reference(root, e, f"wearing {name}") for e in owner.get("refs") or []]
        wanted += [_reference(root, e, "another angle") for e in refs[1:]]
        text = ". ".join(
            p.rstrip(". ")
            for p in (
                (kit.get("identity") or {}).get("description"),
                owner.get("description"),
                (kit.get("style") or {}).get("text"),
                TEST_PROMPT,
            )
            if p
        )
        dst = out_dir(kit_id) / f"test-{name}.png"
        dst.parent.mkdir(parents=True, exist_ok=True)
        router.generate(
            job, "image", "image", text + ".", dst,
            width=1024, height=1024, title=name, palette=0, style="studio",
            only=[provider], model=model, references=wanted[: support["max_images"]],
        )  # fmt: skip
        made.append((name, dst))
    return made
