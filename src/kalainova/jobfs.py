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
}


RENDER_STAMP = "render_stamp.json"
AUDIO_SUFFIXES = (".wav", ".m4a", ".mp3", ".flac")
DOCUMENT_MEDIA = ("comic", "story")


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

    def spent(self) -> float:
        if not self.ledger_path.exists():
            return 0.0
        return sum(e.get("cost", 0.0) for e in json.loads(self.ledger_path.read_text()))

    def reserve(self, provider: str, capability: str, estimate: float) -> None:
        """Refuse a paid call before it is made if it would cross the cap."""
        cap = self.job.get("cost_cap")
        if cap is not None and estimate > 0 and self.spent() + estimate > cap:
            raise CostCapExceeded(
                f"{self.id}: {provider}/{capability} estimated {estimate:.4f}; spent {self.spent():.4f} of cap {cap}"
            )

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Serialize writers to this job's records, across threads and processes."""
        with open(self.folder / ".lock", "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            yield

    def charge(self, provider: str, capability: str, cost: float, note: str = "") -> None:
        with self.locked():
            entries = json.loads(self.ledger_path.read_text()) if self.ledger_path.exists() else []
            entries.append(
                {
                    "provider": provider,
                    "capability": capability,
                    "cost": round(cost, 6),
                    "note": note,
                }
            )
            tmp = self.ledger_path.with_suffix(f".{uuid.uuid4().hex[:8]}.tmp")
            tmp.write_text(json.dumps(entries, indent=2) + "\n")
            os.replace(
                tmp, self.ledger_path
            )  # a reader sees the old ledger or the new one, never part of one
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


def dump(data: Any) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)
