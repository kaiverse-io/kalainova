"""TEMPLATES. A fixed brief and claim shape, filled from fresh data, into a new job.

A template names what stays the same between runs: the brief's wording, the claim sentences, and
any cards, each written with `{field}` placeholders. A data file supplies what changes: today's
numbers, and how fresh they are. Filling checks the data is not stale before trusting it, then
hydrates every placeholder and threads each claim's source straight into `script_packet.json`, so
a claim never reaches a job without the source the data file gave it.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import yaml

from .jobfs import ContractError, Job, home

DEFAULT_STRATEGY = "owned-derivative"
DEFAULT_RIGHTS = "owned"
DEFAULT_MEDIA = ["video", "audio"]


def _load(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise ContractError(f"{p} does not exist")
    text = p.read_text()
    loaded: Any = json.loads(text) if p.suffix.lower() == ".json" else yaml.safe_load(text)
    if not isinstance(loaded, dict):
        raise ContractError(f"{p} must contain a mapping at the top level")
    return loaded


def _format(value: Any, data: dict[str, Any], data_path: str | Path, where: str) -> Any:
    """Fill `{field}` placeholders from data, recursing through dicts and lists."""
    if isinstance(value, str):
        try:
            return value.format_map(data)
        except KeyError as exc:
            raise ContractError(
                f"{data_path}: {where} needs {exc} from the data file, which has no such field"
            ) from exc
    if isinstance(value, dict):
        return {k: _format(v, data, data_path, f"{where}.{k}") for k, v in value.items()}
    if isinstance(value, list):
        return [_format(v, data, data_path, f"{where}[{i}]") for i, v in enumerate(value)]
    return value


def _check_fresh(data: dict[str, Any], data_path: str | Path, max_age_hours: float | None) -> None:
    if max_age_hours is None:
        return
    raw = data.get("as_of", data.get("timestamp"))
    if raw is None:
        return
    try:
        as_of = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError(f"{data_path}: as_of {raw!r} is not an ISO 8601 time") from exc
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=dt.UTC)
    age = (dt.datetime.now(dt.UTC) - as_of).total_seconds() / 3600
    if age > max_age_hours:
        raise ContractError(
            f"data file {data_path} is stale: as_of is {age:.1f}h old (limit: {max_age_hours}h)"
        )


def _claim_text(claim: dict[str, Any]) -> str:
    return str(claim.get("claim") or claim.get("statement") or "")


def _beats(brief: dict[str, Any], claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    title = str(brief.get("title") or brief.get("subject") or "Update")
    beats = [{"id": "b1", "role": "hook", "text": title}]
    for i, claim in enumerate(claims, start=2):
        beats.append({"id": f"b{i}", "role": "body", "text": _claim_text(claim)})
    return beats


def _packet_claims(claims: list[dict[str, Any]], data_path: str | Path) -> list[dict[str, Any]]:
    sourced = []
    for i, claim in enumerate(claims, start=1):
        statement = _claim_text(claim)
        source = str(claim.get("source") or "")
        if not statement or not source:
            raise ContractError(
                f"{data_path}: claim {i} needs both claim text and a source once hydrated, "
                f"got {claim!r}"
            )
        sourced.append({"id": f"c{i}", "statement": statement, "source": source})
    return sourced


def fill_template(
    template_path: str | Path,
    data_path: str | Path,
    job_id: str,
    *,
    max_age_hours: float | None = None,
) -> Job:
    template = _load(template_path)
    data = _load(data_path)

    limit = max_age_hours if max_age_hours is not None else template.get("max_age_hours")
    _check_fresh(data, data_path, limit)

    brief: dict[str, Any] = _format(template.get("brief") or {}, data, data_path, "brief")
    raw_claims: list[dict[str, Any]] = _format(
        template.get("claims") or [], data, data_path, "claims"
    )
    raw_cards = template.get("cards")
    cards = _format(raw_cards, data, data_path, "cards") if raw_cards is not None else None
    distribution_identity = _format(
        template.get("distribution_identity"), data, data_path, "distribution_identity"
    )

    folder = home() / "jobs" / job_id
    if folder.exists():
        raise ContractError(f"{folder} already exists")
    folder.mkdir(parents=True)
    job = Job(folder)

    job.write(
        "job",
        {
            "schema_version": "0.1",
            "job_id": job_id,
            "strategy": template.get("strategy", DEFAULT_STRATEGY),
            "rights": template.get("rights", DEFAULT_RIGHTS),
            "distribution_identity": distribution_identity,
            "status": "draft",
            "media": template.get("media", DEFAULT_MEDIA),
            "brief": brief,
        },
    )

    claims = _packet_claims(raw_claims, data_path)
    packet: dict[str, Any] = {
        "schema_version": "0.1",
        "job_id": job_id,
        "beats": _beats(brief, raw_claims),
    }
    if claims:
        packet["claims"] = claims
    job.write("script_packet", packet)

    if cards is not None:
        (folder / "cards.json").write_text(json.dumps(cards, indent=2, ensure_ascii=False) + "\n")

    return job
