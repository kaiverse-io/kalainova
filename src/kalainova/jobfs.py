"""Job folder access: paths, JSON load/save, schema validation, cost ledger."""

from __future__ import annotations

import fcntl
import json
import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SCHEMAS = REPO / "schemas"


def home() -> Path:
    """Where operator data lives: jobs, kits, streams. This repo is public, so real work belongs in
    a private directory named by $KALAINOVA_HOME. The engine, schemas, and prompts stay in the repo."""
    return Path(os.environ.get("KALAINOVA_HOME", REPO))


CONTRACT_FILES = {
    "job": "job.json",
    "script_packet": "script_packet.json",
    "asset_manifest": "asset_manifest.json",
    "edit_manifest": "edit_manifest.json",
    "render_plan": "render_plan.json",
    "qa": "qa.json",
    "approval": "approval.json",
    "publish_log": "publish_log.json",
    "measure": "measure.json",
    "kit_lock": "kit.lock.json",
    "comic_script": "comic_script.json",
    "story": "story.json",
    "song": "song.json",
    "research": "research.json",
    "takes": "takes.json",
    "findings": "findings.json",
    "animatic": "animatic.json",
}


RENDER_STAMP = "render_stamp.json"
AUDIO_SUFFIXES = (".wav", ".m4a", ".mp3", ".flac")
DOCUMENT_MEDIA = ("comic", "story")
RESERVED = "reserved"


class ContractError(RuntimeError):
    pass


class CostCapExceeded(Exception):
    """Deliberately not a RuntimeError, so provider fallbacks never swallow it."""


def load_schema(name: str) -> dict:
    return json.loads((SCHEMAS / f"{name}.schema.json").read_text())


def validate(name: str, data: dict, where: str = "") -> None:
    """Validate against schemas/<name>.schema.json. Raises ContractError."""
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - jsonschema ships in the image
        return
    schema_path = SCHEMAS / f"{name}.schema.json"
    if not schema_path.exists():
        return
    validator = jsonschema.Draft202012Validator(load_schema(name))
    problems = sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path))
    if problems:
        lines = [
            f"{where or name}: {'/'.join(map(str, p.absolute_path)) or '<root>'}: {p.message}"
            for p in problems
        ]
        raise ContractError("\n".join(lines))


@dataclass
class Job:
    folder: Path

    @property
    def id(self) -> str:
        return self.folder.name

    @property
    def work(self) -> Path:
        """Where media bytes go. Outside git by default."""
        root = Path(os.environ.get("KALAINOVA_OUT", home() / "out"))
        path = root / self.id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path(self, name: str) -> Path:
        return self.folder / CONTRACT_FILES[name]

    def has(self, name: str) -> bool:
        return self.path(name).exists()

    def read(self, name: str) -> dict:
        path = self.path(name)
        if not path.exists():
            raise ContractError(f"{self.id}: missing {path.name}; run the earlier stage first")
        data = json.loads(path.read_text())
        validate(name, data, str(path))
        return data

    def write(self, name: str, data: dict) -> Path:
        validate(name, data, f"{self.id}/{CONTRACT_FILES[name]}")
        path = self.path(name)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return path

    def artifact(self) -> Path:
        """The file this job delivers. A job with video always delivers final.mp4, so a stray audio file
        cannot stand in for it."""
        kinds = self.job.get("media", [])
        if "video" in kinds:
            return self.work / "final.mp4"
        if "song" in kinds:
            return self.work / "final.wav"
        if any(kind in kinds for kind in DOCUMENT_MEDIA):
            return self.work / "final.pdf"
        for suffix in AUDIO_SUFFIXES:
            path = self.work / f"final{suffix}"
            if path.exists():
                return path
        return self.work / f"final{AUDIO_SUFFIXES[0]}"

    def write_stamp(self, data: dict) -> None:
        (self.folder / RENDER_STAMP).write_text(json.dumps(data, indent=2) + "\n")

    def read_stamp(self) -> dict | None:
        path = self.folder / RENDER_STAMP
        return json.loads(path.read_text()) if path.exists() else None

    @property
    def job(self) -> dict:
        return self.read("job")

    def set_status(self, status: str) -> None:
        data = self.job
        data["status"] = status
        self.write("job", data)

    # --- cost ledger -------------------------------------------------------
    @property
    def ledger_path(self) -> Path:
        return self.folder / "ledger.json"

    def _ledger(self) -> list[dict]:
        return json.loads(self.ledger_path.read_text()) if self.ledger_path.exists() else []

    def _write_ledger(self, entries: list[dict]) -> None:
        tmp = self.ledger_path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
        tmp.write_text(json.dumps(entries, indent=2) + "\n")
        # a reader sees the old ledger or the new one, never part of one
        os.replace(tmp, self.ledger_path)

    def spent(self) -> float:
        """Money the job has settled. Reservations are not spent until they settle."""
        return sum(e.get("cost", 0.0) for e in self._ledger() if e.get("status") != RESERVED)

    def committed(self) -> float:
        """Settled money plus every reservation still open, which is what the cap is held against."""
        return sum(e.get("cost", 0.0) for e in self._ledger())

    def reserve(self, provider: str, capability: str, estimate: float) -> str | None:
        """Hold the estimate on the ledger before a paid call, so parallel calls cannot overshoot.

        Returns the reservation to settle or release. A free call needs none.
        """
        cap = self.job.get("cost_cap")
        with self.locked():
            held = self.committed()
            if cap is not None and estimate > 0 and held + estimate > cap:
                raise CostCapExceeded(
                    f"{self.id}: {provider}/{capability} estimated {estimate:.4f}; "
                    f"{held:.4f} already committed of cap {cap}"
                )
            if estimate <= 0:
                return None
            reservation = uuid.uuid4().hex[:12]
            self._write_ledger(
                [
                    *self._ledger(),
                    {
                        "provider": provider,
                        "capability": capability,
                        "cost": round(estimate, 6),
                        "note": "reserved before the call",
                        "status": RESERVED,
                        "reservation": reservation,
                    },
                ]
            )
        return reservation

    def release(self, reservation: str | None) -> None:
        """Give a reservation back: the call failed and nothing was billed."""
        if not reservation:
            return
        with self.locked():
            self._write_ledger([e for e in self._ledger() if e.get("reservation") != reservation])

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Serialize writers to this job's records, across threads and processes."""
        with open(self.folder / ".lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            yield

    def charge(
        self,
        provider: str,
        capability: str,
        cost: float,
        note: str = "",
        reservation: str | None = None,
    ) -> None:
        """Record what a call cost, settling its reservation if it had one."""
        with self.locked():
            entries = [
                e for e in self._ledger() if e.get("reservation") != reservation or not reservation
            ]
            entries.append(
                {
                    "provider": provider,
                    "capability": capability,
                    "cost": round(cost, 6),
                    "note": note,
                }
            )
            self._write_ledger(entries)
        cap = self.job.get("cost_cap")
        if cap is not None and self.spent() > cap:
            raise CostCapExceeded(
                f"{self.id}: spent {self.spent():.4f} is over cap {cap}; stop rendering"
            )


def open_job(ref: str | Path) -> Job:
    path = Path(ref)
    if not (path / "job.json").exists():
        candidate = home() / "jobs" / str(ref)
        if (candidate / "job.json").exists():
            path = candidate
        else:
            raise ContractError(f"no job.json at {ref}")
    return Job(path.resolve())


def open_child(parent: Job, new_id: str, *, profile: str, brief: dict) -> Job:
    """A new job made from another: the same rights, identity, and limits, and a line back to it."""
    folder = home() / "jobs" / new_id
    if folder.exists():
        raise ContractError(f"{folder} already exists")
    source = parent.job
    data = {
        "schema_version": "0.1",
        "job_id": new_id,
        "strategy": source["strategy"],
        "media": ["video", "audio"],
        "rights": source["rights"],
        "distribution_identity": source.get("distribution_identity"),
        "status": "draft",
        "cost_cap": source.get("cost_cap"),
        "parent_job_id": parent.id,
        "profile": profile,
        "brief": brief,
    }
    for key in ("providers", "skip_funded"):
        if key in source:
            data[key] = source[key]
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(dump(data) + "\n")
    return Job(folder)


def dump(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)
