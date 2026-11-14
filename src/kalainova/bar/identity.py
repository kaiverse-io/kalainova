"""Whether a picture shows a character: each face found in it, compared with the kit's faces.

The engine ships no face model. `identity.face_command` in config/studio.yaml is an argument list
for a command that takes `--out FILE` and image paths after it, and writes one JSON object to
FILE, `{path: [face, ...]}`, where a face is `{"box": [x, y, w, h], "score": s,
"embedding": [floats]}`.
`providers/runners/face_run.py` is one such command (OpenCV's YuNet detector and SFace
recognizer), run in an environment of its own.

Every face in a picture is compared with every reference face, so a crowd is read face by face:
the reading says how many faces were found and how close the nearest one comes to the character.
With no command configured nothing is measured, and a caller reports a gap, never a pass.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .. import config, media, opentools
from ..jobfs import ContractError
from .readings import Reading

FACE_TIMEOUT_SEC = 300.0


@dataclass(frozen=True)
class Face:
    box: tuple[float, float, float, float]
    score: float
    embedding: tuple[float, ...]

    @property
    def area(self) -> float:
        return self.box[2] * self.box[3]


@dataclass(frozen=True)
class Match:
    """What one picture's faces say against a set of reference faces."""

    faces: int
    best: float | None  # cosine similarity of the closest face to any reference; None: no face
    matching: int  # faces at or above the limit

    def detail(self, limit: float) -> str:
        if not self.faces:
            return "no face found"
        return (
            f"{self.faces} face(s); closest {self.best:.3f}; "
            f"{self.matching} at or above {limit:g}, a limit not yet checked against verdicts"
        )


def _settings() -> dict[str, Any]:
    return dict(config.studio().get("identity") or {})


def configured() -> bool:
    """Whether a face command is set. Without one, identity is a gap that a person fills."""
    return bool(_settings().get("face_command"))


def limit() -> float:
    """Cosine similarity at or above which two faces are read as one person."""
    return float(_settings().get("same_face_min", 0.363))


def faces(paths: list[Path]) -> dict[Path, list[Face]]:
    """Every face in each picture, from one run of the configured command."""
    command = [str(Path(part).expanduser()) for part in _settings().get("face_command") or []]
    if not command:
        raise ContractError("no identity.face_command in config/studio.yaml")
    wanted = [str(p.resolve()) for p in paths]
    with tempfile.TemporaryDirectory() as tmp:
        out_file = Path(tmp) / "faces.json"
        run = opentools.run([*command, "--out", str(out_file), *wanted], timeout=FACE_TIMEOUT_SEC)
        if run.returncode != 0:
            raise ContractError(f"the face command failed: {run.stderr.strip()[-400:]}")
        try:
            found = json.loads(out_file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ContractError(f"the face command wrote no readable JSON: {exc}") from exc
    out: dict[Path, list[Face]] = {}
    for path, key in zip(paths, wanted, strict=True):
        rows = found.get(key)
        if rows is None:
            raise ContractError(f"the face command said nothing about {path.name}")
        out[path] = [
            Face(tuple(r["box"]), float(r["score"]), tuple(float(v) for v in r["embedding"]))
            for r in rows
        ]
    return out


def similarity(a: Face, b: Face) -> float:
    va, vb = np.asarray(a.embedding), np.asarray(b.embedding)
    norm = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb / norm) if norm else 0.0


def reference_faces(found: dict[Path, list[Face]], references: list[Path]) -> list[Face]:
    """The largest face in each reference picture. A reference with no face holds nothing."""
    return [max(found[r], key=lambda f: f.area) for r in references if found.get(r)]


def match(picture: list[Face], refs: list[Face], at_least: float) -> Match:
    if not picture or not refs:
        return Match(len(picture), None, 0)
    best_per_face = [max(similarity(face, ref) for ref in refs) for face in picture]
    return Match(
        faces=len(picture),
        best=max(best_per_face),
        matching=sum(s >= at_least for s in best_per_face),
    )


def face_reading(image: Path, references: list[Path]) -> Reading | None:
    """How close the nearest face in a picture comes to the character. None: not measured.

    A picture with no face reads 0, since it was asked to show the character. Warns only: the
    limit is the recognizer's published one, not yet checked against a person's verdicts.
    """
    if not references or not configured():
        return None
    found = faces([image, *references])
    refs = reference_faces(found, references)
    if not refs:
        raise ContractError("no face found in any reference picture")
    result = match(found[image], refs, limit())
    value = 0.0 if result.best is None else result.best
    return Reading(
        id="identity.face_match",
        value=round(value, 4),
        limit=f">= {limit():g}",
        ok=value >= limit(),
    )


def panels_check(panels: list[Path], refs: list[Path]) -> tuple[str, str]:
    """Panels against a cast's faces. A panel with no face says nothing; one whose faces match no
    one in the cast is named. A gap, never a pass, when no face command is set."""
    if not configured():
        return "warn", "no face check configured (identity.face_command); a person compares faces"
    found = faces([*panels, *refs])
    cast = reference_faces(found, refs)
    if not cast:
        return "warn", "no face found in the kit's reference pictures"
    peopled = {p: match(found[p], cast, limit()) for p in panels if found[p]}
    if not peopled:
        return "warn", "no face found in any panel"
    strangers = sorted(p.stem for p, m in peopled.items() if not m.matching)
    closest = min(m.best for m in peopled.values() if m.best is not None)
    detail = f"{len(peopled)} panel(s) with faces; weakest match {closest:.3f} (>= {limit():g})"
    if strangers:
        detail += f"; no cast face in {', '.join(strangers)}"
    return ("warn" if strangers else "pass"), detail


CAST_FILE = "identity.json"


def check_cast(
    work: Path, resolved: Any, beats: list[dict[str, Any]], rows: list[Any]
) -> list[dict[str, Any]]:
    """Each animatic still against the characters its shot names, in one run of the command.

    Advises the person deciding on the animatic; it blocks nothing. The result goes to
    identity.json in the work folder, and an earlier one is removed when nothing is measured.
    A command that fails is reported, not raised, since the animatic itself is sound.
    """
    (work / CAST_FILE).unlink(missing_ok=True)
    if resolved is None or not configured():
        return []
    from ..kits import blob_path

    cast_of = {b["id"]: b.get("cast") or [] for b in beats}
    shots = []
    for row in rows:
        still = work / str(row.get("still") or "")
        roles = cast_of.get(row["beat_id"]) or []
        if roles and still.is_file():
            refs = {
                role: [
                    blob_path(resolved.root, e)
                    for e in (resolved.characters[role].get("identity") or {}).get("refs", [])
                ]
                for role in roles
            }
            shots.append((row["beat_id"], still, refs))
    if not shots:
        return []
    every_ref = sorted({p for _, _, refs in shots for paths in refs.values() for p in paths})
    try:
        found = faces([*{s for _, s, _ in shots}, *every_ref])
    except ContractError as exc:
        print(f"identity not measured: {exc}", file=sys.stderr)
        return []
    results = []
    for beat_id, still, refs in shots:
        for role, paths in refs.items():
            seen = match(found[still], reference_faces(found, paths), limit())
            results.append(
                {
                    "beat_id": beat_id,
                    "role": role,
                    "faces": seen.faces,
                    "closest": None if seen.best is None else round(seen.best, 4),
                    "found": bool(seen.matching),
                }
            )
    (work / CAST_FILE).write_text(json.dumps(results, indent=2) + "\n")
    return results


def cast_lines(work: Path) -> list[str]:
    """What the face check said about each character still, for the animatic's printout."""
    path = work / CAST_FILE
    if not path.is_file():
        return []
    lines = []
    for r in json.loads(path.read_text()):
        if not r["faces"]:
            said = "no face found"
        else:
            said = f"{'found' if r['found'] else 'NOT found'}, closest {r['closest']:.2f} of "
            said += f"{r['faces']} face(s), limit {limit():g}"
        lines.append(f"  face check on {r['beat_id']}, {r['role']}: {said}")
    return lines


FRAMES_PER_RUN = 400  # pictures per run of the face command, so a long set stays within argv
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


def _stretches(times: list[float], step: float) -> list[tuple[float, float]]:
    """Runs of sample times one step apart, as (start, end) spans."""
    spans: list[tuple[float, float]] = []
    for t in times:
        if spans and t - spans[-1][1] <= step * 1.5:
            spans[-1] = (spans[-1][0], t)
        else:
            spans.append((t, t))
    return spans


def clip_limits() -> tuple[float, float]:
    """A video's limits: its median closest similarity, and the level below which a sampled frame
    has lost the character. Lighting and motion pull single frames down, so a video is not read
    frame by frame against the still limit."""
    s = _settings()
    return float(s.get("clip_median_min", limit())), float(s.get("lost_below", 0.25))


def summarise_clip(closest: list[float | None], every_sec: float) -> dict[str, Any]:
    """Per sampled frame, the closest face's similarity to the character (None: no face)."""
    median_min, lost_below = clip_limits()
    seen = [c for c in closest if c is not None]
    lost = [i * every_sec for i, c in enumerate(closest) if c is not None and c < lost_below]
    no_face = [i * every_sec for i, c in enumerate(closest) if c is None]
    median = round(float(np.median(seen)), 4) if seen else None
    return {
        "frames": len(closest),
        "every_sec": every_sec,
        "median_closest": median,
        "median_min": median_min,
        "ok": median is not None and median >= median_min,
        "lost_below": lost_below,
        "lost_at": _stretches(lost, every_sec),
        "no_face_at": _stretches(no_face, every_sec),
    }


def clip_report(clip: Path, references: list[Path], every_sec: float = 1.0) -> dict[str, Any]:
    """The character through a video, one sampled frame per `every_sec`, read in batches so a
    20 to 30 minute set stays within one command line per run."""
    with tempfile.TemporaryDirectory() as tmp:
        fit = "scale=w='if(gt(iw,ih),min(1280,iw),-2)':h='if(gt(iw,ih),-2,min(1280,ih))'"
        frames_dir = Path(tmp)
        media.run(
            ["-i", str(clip), "-vf", f"fps=1/{every_sec:g},{fit}", "-q:v", "3",
             str(frames_dir / "f%06d.jpg")]
        )  # fmt: skip
        frames = sorted(frames_dir.glob("f*.jpg"))
        found: dict[Path, list[Face]] = {}
        for at in range(0, len(frames), FRAMES_PER_RUN):
            found.update(faces([*frames[at : at + FRAMES_PER_RUN], *references]))
        cast = reference_faces(found, references)
        if not cast:
            raise ContractError("no face found in any reference picture")
        closest = [match(found[f], cast, limit()).best for f in frames]
    return summarise_clip(closest, every_sec)


def _clock(seconds: float) -> str:
    return f"{int(seconds // 60)}:{seconds % 60:04.1f}"


def kit_line(target: Path, references: list[Path], label: str) -> str:
    """One line for `kalainova bar --kit`: a picture face by face, or a video frame by frame."""
    if not configured():
        return "identity: not measured; set identity.face_command in config/studio.yaml"
    if target.suffix.lower() in VIDEO_SUFFIXES:
        r = clip_report(target, references)
        lost = ", ".join(f"{_clock(a)}-{_clock(b)}" for a, b in r["lost_at"][:8])
        verdict = "holds" if r["ok"] else "does NOT hold"
        return (
            f"identity against {label}, {r['frames']} frames (1 per {r['every_sec']:g}s): "
            f"the character {verdict}, median closest {r['median_closest']} "
            f"(clip limit {r['median_min']:g}); lost (below {r['lost_below']:g}) "
            + (f"at {lost}" if lost else "nowhere")
            + f"; no face in {sum(int((b - a) / r['every_sec']) + 1 for a, b in r['no_face_at'])}"
        )
    found = faces([target, *references])
    result = match(found[target], reference_faces(found, references), limit())
    return f"identity against {label}: {result.detail(limit())}"
