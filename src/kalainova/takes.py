"""One shot, several attempts. A reading picks among them, and a human can overrule it.

A generated shot is a sample, not a result: the same prompt gives a frozen clip on one seed and a
living one on the next. So every attempt is kept with its seed and how it read, a failing reading
asks for another attempt up to a limit, and the piece uses one chosen take at a stable path.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import bar, config, media
from .blobstore import sha256_file
from .jobfs import ContractError, Job

Take = dict[str, Any]
Assess = Callable[[Path], tuple[dict[str, Any], bool]]
SEED_RANGE = 2**31 - 1
READ_WIDTH = bar.MOTION_WIDTH


def seed_for(prompt: str, n: int) -> int:
    """A different seed per attempt, and the same seed every time for the same attempt."""
    return int(hashlib.sha256(f"{prompt}#{n}".encode()).hexdigest()[:8], 16) % SEED_RANGE


def counts(brief: dict[str, Any]) -> tuple[int, int]:
    """How many takes are always made, and the most a failing reading can ask for."""
    defaults = config.takes()
    always = max(int(brief.get("takes", defaults.get("always", 1))), 1)
    return always, max(int(brief.get("max_takes", defaults.get("most", 2))), always)


def retake_limits(brief: dict[str, Any]) -> tuple[int, int]:
    """The most retakes one shot gets, and a whole job gets. A brief can set max_retakes."""
    defaults = config.takes()
    per_shot = max(int(defaults.get("retakes_per_shot", 2)), 0)
    per_job = max(int(brief.get("max_retakes", defaults.get("retakes_per_job", 6))), 0)
    return per_shot, per_job


def check_retake(job: Job, shot: str, brief: dict[str, Any]) -> None:
    """Refuse a retake past the limits. The command enforces this, so no skill can loop past it."""
    per_shot, per_job = retake_limits(brief)
    shots = load(job)["shots"]
    mine = sum(1 for t in (shots.get(shot) or {}).get("takes", []) if t.get("retake"))
    total = sum(1 for e in shots.values() for t in e["takes"] if t.get("retake"))
    if mine >= per_shot:
        raise ContractError(
            f"{job.id}: {shot} has had {mine} retakes and the limit is {per_shot}; "
            "choose among its takes with `kalainova take`, or hand it over as it is"
        )
    if total >= per_job:
        raise ContractError(
            f"{job.id}: the job has had {total} retakes and the limit is {per_job}; "
            "set brief.max_retakes to allow more, which is the operator's call"
        )


def findings(job: Job) -> dict[str, Any]:
    """What the last look at the piece in motion found, or nothing."""
    if job.has("findings"):
        return job.read("findings")
    return {"schema_version": "0.1", "job_id": job.id, "source": "agent", "shots": []}


def finding_for(job: Job, shot: str) -> dict[str, Any] | None:
    return next((f for f in findings(job)["shots"] if f["id"] == shot), None)


def load(job: Job) -> dict[str, Any]:
    if job.has("takes"):
        return job.read("takes")
    return {"schema_version": "0.1", "job_id": job.id, "shots": {}}


def _chosen(entry: dict[str, Any]) -> Take:
    return next(t for t in entry["takes"] if t["n"] == entry["chosen"])


def _score(take: Take) -> float:
    return float((take.get("readings") or {}).get("score", 0.0))


def _best(takes: list[Take]) -> int:
    """The take that reads best among those that pass; otherwise the one closest to passing.

    A bench take is a camera test, so it only stands for the shot when nothing else was made.
    """
    takes = [t for t in takes if not t.get("bench")] or takes
    passing = [t for t in takes if t["ok"]]
    return int(max(passing or takes, key=_score)["n"])


def record(job: Job, shot: str, take: Take) -> dict[str, Any]:
    """Add a take. A human's choice stands; otherwise the readings decide again."""
    data = load(job)
    entry = data["shots"].setdefault(
        shot, {"chosen": take["n"], "chosen_by": "reading", "takes": []}
    )
    entry["takes"] = [t for t in entry["takes"] if t["n"] != take["n"]] + [take]
    entry["takes"].sort(key=lambda t: t["n"])
    if entry["chosen_by"] != "human" and not (take.get("bench") and len(entry["takes"]) > 1):
        # someone asked for this take because they saw what a reading cannot, so it is used if it
        # reads well, even when an earlier take reads just as well
        asked_for = take.get("note") and take.get("ok")
        entry["chosen"] = take["n"] if asked_for else _best(entry["takes"])
    job.write("takes", data)
    return dict(entry)


def choose(job: Job, shot: str, n: int) -> Take:
    """A human's choice. It stands until a human changes it."""
    data = load(job)
    entry = data["shots"].get(shot)
    if not entry:
        raise ContractError(
            f"{job.id}: no takes of {shot}; shots with takes: {sorted(data['shots'])}"
        )
    if not any(t["n"] == n for t in entry["takes"]):
        have = [t["n"] for t in entry["takes"]]
        raise ContractError(f"{job.id}: {shot} has no take {n}; it has {have}")
    entry.update(chosen=n, chosen_by="human")
    job.write("takes", data)
    return _chosen(entry)


def chosen(job: Job, shot: str) -> Take | None:
    entry = load(job)["shots"].get(shot)
    return _chosen(entry) if entry else None


def next_take_number(job: Job, shot: str) -> int:
    entry = load(job)["shots"].get(shot)
    return max((t["n"] for t in entry["takes"]), default=-1) + 1 if entry else 0


def take_path(job: Job, shot: str, n: int, suffix: str) -> Path:
    folder = job.work / "takes" / shot
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"take-{n:02d}{suffix}"


def assess_clip(path: Path) -> tuple[dict[str, Any], bool]:
    """How a generated clip reads, and whether it can stand without another attempt."""
    try:
        info = media.summarize(path)
        fps = float(info.get("fps") or 24.0)
        frames = media.decode_gray(path, width=READ_WIDTH)
        moved = bar.shot_motion(frames, fps)
    except (media.MediaError, ValueError, KeyError):
        return {
            "score": 0.0,
            "unread": True,
        }, True  # no reason to pay again for what cannot be read
    limit = float(bar.limits()["shot_motion_min"])
    readings: dict[str, Any] = {"score": round(moved or 0.0, 4)}
    if moved is None:
        return readings, True  # too short to read, and no reason to pay for another
    readings["shot_motion"] = round(moved, 4)
    return readings, moved >= limit


def attempt(
    job: Job,
    shot: str,
    n: int,
    *,
    suffix: str,
    make: Callable[[int, Path], tuple[Any, Any]],
    assess: Assess,
    prompt: str = "",
    note: str = "",
    seed: int | None = None,
    extra: dict[str, Any] | None = None,
) -> Take:
    """Make one attempt with its own seed, read it, and record it with what it cost."""
    seed = seed_for(prompt, n) if seed is None else seed
    dst = take_path(job, shot, n, suffix)
    provider, res = make(seed, dst)
    readings, ok = assess(dst)
    take: Take = {
        "n": n,
        "seed": int((res.meta or {}).get("seed", seed)),
        "file": str(dst.relative_to(job.work)),
        "sha256": sha256_file(dst),
        "provider": provider.name,
        "model": res.model,
        "readings": readings,
        "ok": bool(ok),
        **({"cost": round(float(res.cost), 6)} if res.cost else {}),
        **(extra or {}),
    }
    if prompt:
        take["prompt"] = prompt
    if note:
        take["note"] = note
    if res.meta:
        take["meta"] = dict(res.meta)
    if res.words:
        take["words"] = list(res.words)
    record(job, shot, take)
    return take


def make_until_good(
    job: Job,
    shot: str,
    brief: dict[str, Any],
    *,
    suffix: str,
    make: Callable[[int, Path], tuple[Any, Any]],
    assess: Assess,
    prompt: str = "",
) -> Take:
    """Attempts until one reads well or the limit is reached. Returns the chosen take."""
    always, most = counts(brief)

    def made() -> list[
        Take
    ]:  # a bench take is a camera test, and does not count against the limits
        found = load(job)["shots"].get(shot, {}).get("takes", [])
        return [t for t in found if not t.get("bench")]

    while len(made()) < most:
        if len(made()) >= always and any(t["ok"] for t in made()):
            break
        n = next_take_number(job, shot)
        attempt(job, shot, n, suffix=suffix, make=make, assess=assess, prompt=prompt)
    found = chosen(job, shot)
    if not found:
        raise ContractError(f"{job.id}: no take of {shot} was made")
    return found


def place(job: Job, shot: str, dst: Path) -> Take:
    """Put the chosen take where the piece reads it."""
    take = chosen(job, shot)
    if not take:
        raise ContractError(f"{job.id}: no take of {shot}")
    shutil.copyfile(job.work / take["file"], dst)
    return take


def forget(job: Job) -> None:
    """Start the record again. The files stay on disk until the next attempt overwrites them."""
    job.path("takes").unlink(missing_ok=True)


def provider_meta(take: Take) -> dict[str, Any]:
    """The part of a take a record of the piece should carry."""
    kept = {k: take[k] for k in ("seed", "sha256") if k in take}
    return {**kept, **dict(take.get("meta") or {}), "take": take["n"]}
