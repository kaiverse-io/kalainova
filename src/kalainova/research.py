"""RESEARCH. What a piece may state as fact, with the words that support it.

An invented fact is the costliest thing an engine can write, and a model is good at inventing them.
So a finding is only usable when it quotes a source, and the quote is checked against a private
snapshot of what that source said when it was read. A model can draft findings. Nothing it wrote
counts until the check finds its quote.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests

from . import config, prompts
from .jobfs import ContractError, Job
from .providers import base, router
from .providers.search import HEADERS

SNAPSHOTS = "research"
FETCH_TIMEOUT = 30
MOST_BYTES = 4_000_000
MOST_CONTEXT_CHARS = 6000  # how much of each source a model reads when drafting findings
LEAST_QUOTE_CHARS = 12  # shorter than this proves nothing
SKIPPED_TAGS = {"script", "style", "nav", "footer", "header", "noscript", "svg", "form", "aside"}
TEXT_TYPES = ("text/html", "text/plain", "application/xhtml")


class _Reader(HTMLParser):
    """The readable text of a page, leaving out what is not the page's content."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIPPED_TAGS:
            self.skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIPPED_TAGS and self.skip:
            self.skip -= 1

    def handle_data(self, data: str) -> None:
        if not self.skip and data.strip():
            self.parts.append(data.strip())


def page_text(html: str) -> str:
    reader = _Reader()
    reader.feed(html)
    return "\n".join(reader.parts)


def fetch_text(url: str) -> str:
    """What a page says, as text. Empty when it is not a page this can read."""
    if not re.match(r"https?://", url):
        return ""
    with requests.get(url, headers=HEADERS, timeout=FETCH_TIMEOUT, stream=True) as reply:
        reply.raise_for_status()
        kind = reply.headers.get("content-type", "text/html").lower()
        if not any(t in kind for t in TEXT_TYPES):
            return ""
        blob = next(reply.iter_content(MOST_BYTES), b"")
    text = blob.decode(reply.encoding or "utf-8", errors="replace")
    return text if "text/plain" in kind else page_text(text)


def normalise(text: str) -> str:
    """Compare words, not typography: curly quotes, dashes, and line breaks must not hide a match."""
    swaps = {"‘": "'", "’": "'", "“": '"', "”": '"', "–": "-", "—": "-"}
    for old, new in swaps.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip().lower()


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _snapshot(job: Job, source_id: str, text: str) -> tuple[str, str]:
    folder = job.folder / SNAPSHOTS
    folder.mkdir(exist_ok=True)
    path = folder / f"{source_id}.txt"
    path.write_text(text)
    return str(path.relative_to(job.folder)), hashlib.sha256(text.encode()).hexdigest()


def _hits_from(job: Job, name: str, query: str, limit: int) -> list[dict[str, Any]]:
    try:
        _, res = router.generate(
            job, "search", "search", query, only=[name], limit=limit, note=f"search: {query[:60]}"
        )
    except (router.ProviderError, OSError) as exc:
        print(f"{job.id}: {name} found nothing: {exc}")
        return []
    return [{**hit, "found_by": name} for hit in res.meta.get("hits", [])]


def _source_id(n: int) -> str:
    return f"s{n:02d}"


def _next_number(sources: list[dict[str, Any]]) -> int:
    numbers = [int(s["id"][1:]) for s in sources if re.fullmatch(r"s\d+", str(s["id"]))]
    return max(numbers, default=0) + 1


def _source_from(job: Job, hit: dict[str, Any], source_id: str) -> dict[str, Any] | None:
    try:
        text = str(hit.get("text") or "") or fetch_text(str(hit["url"]))
    except OSError as exc:
        print(f"{job.id}: could not read {hit['url']}: {exc}")
        return None
    if not text.strip():
        return None
    snapshot, digest = _snapshot(job, source_id, text)
    source: dict[str, Any] = {
        "id": source_id,
        "url": str(hit["url"]),
        "title": str(hit.get("title") or hit["url"]),
        "found_by": str(hit.get("found_by") or ""),
        "retrieved_at": _now(),
        "snapshot": snapshot,
        "snapshot_sha256": digest,
    }
    for key in ("publisher", "published", "reliability"):
        if hit.get(key):
            source[key] = str(hit[key])
    return source


def gather(job: Job, question: str, queries: list[str], *, limit: int = 5) -> dict[str, Any]:
    """Read what the listed search providers find. Findings already written are kept."""
    data: dict[str, Any] = (
        job.read("research")
        if job.has("research")
        else {
            "schema_version": "0.1",
            "job_id": job.id,
            "question": question,
            "sources": [],
            "findings": [],
        }
    )
    data["question"] = question
    data["researched_at"] = _now()
    seen = {s["url"] for s in data["sources"]}
    number = _next_number(data["sources"])
    for query in queries or [question]:
        for name in config.preference("search", job.job):
            if not _ready(name):
                continue
            for hit in _hits_from(job, name, query, limit):
                if hit["url"] in seen:
                    continue
                seen.add(hit["url"])
                source = _source_from(job, hit, _source_id(number))
                if source:
                    data["sources"].append(source)
                    number += 1
    job.write("research", data)
    return data


def _ready(name: str) -> bool:
    try:
        return base.get(name).available()
    except KeyError:
        return False


def _read_snapshot(job: Job, source: dict[str, Any]) -> str:
    snapshot = source.get("snapshot")
    path = job.folder / str(snapshot) if snapshot else None
    return path.read_text() if path and path.is_file() else ""


def verify(job: Job) -> list[str]:
    """Mark each finding by whether its quote is really in a source it cites. Returns what failed."""
    data = job.read("research")
    sources = {s["id"]: s for s in data["sources"]}
    failed = []
    for finding in data["findings"]:
        quote = normalise(finding["quote"])
        cited = [sources[i] for i in finding["source_ids"] if i in sources]
        found = len(quote) >= LEAST_QUOTE_CHARS and any(
            quote in normalise(_read_snapshot(job, source)) for source in cited
        )
        finding["verified"] = found
        if not found:
            failed.append(f"{finding['id']}: {finding['quote'][:80]!r} is not in its source")
    job.write("research", data)
    return failed


def _context(job: Job, data: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {
            "id": s["id"],
            "title": s["title"],
            "publisher": str(s.get("publisher", "")),
            "text": _read_snapshot(job, s)[:MOST_CONTEXT_CHARS],
        }
        for s in data["sources"]
    ]


def draft(job: Job) -> None:
    """Ask a model for findings. It proposes; verify() decides, and the unsupported are dropped."""
    from .plan import extract_json

    data = job.read("research")
    text = prompts.load("research_findings").format(
        question=data["question"],
        sources=json.dumps(_context(job, data), ensure_ascii=False),
    )
    _, res = router.generate(job, "llm", "llm", text, max_tokens=4000, note="research")
    reply = extract_json(res.text)
    data["findings"] = list(reply.get("findings") or [])
    data["gaps"] = [str(g) for g in reply.get("gaps") or []]
    data["angles"] = [str(a) for a in reply.get("angles") or []]
    job.write("research", data)
    failed = verify(job)
    if failed:
        print(f"{job.id}: dropped {len(failed)} findings whose quotes were not in their sources")
        kept = job.read("research")
        kept["findings"] = [f for f in kept["findings"] if f.get("verified")]
        job.write("research", kept)


def run(job: Job, question: str, queries: list[str], *, limit: int = 5) -> dict[str, Any]:
    """Gather sources and, when a model is available, draft findings from them.

    With no model, the agent driving the session writes findings into research.json by hand, and
    `kalainova research <job> --check` holds them to the same test.
    """
    data = gather(job, question, queries, limit=limit)
    if not data["sources"]:
        raise ContractError(f"{job.id}: no source could be read for {question!r}")
    if router.available(job, "llm"):
        draft(job)
    return job.read("research")


def claim_checks(job: Job, packet: dict[str, Any]) -> list[dict[str, str]]:
    """A piece's factual claims against its research. With research on file, a miss is a failure."""
    claims = packet.get("claims") or []
    if not claims:
        return []
    if not job.has("research"):
        detail = "no research on file, so no claim was checked against what its source says"
        return [{"id": "claims.verified", "status": "warn", "detail": detail}]
    findings = {f["id"]: f for f in job.read("research")["findings"]}
    bad = [
        str(c["id"])
        for c in claims
        if not (findings.get(str(c.get("finding"))) or {}).get("verified")
    ]
    detail = (
        f"claims with no checked finding: {bad}" if bad else "every claim has a checked finding"
    )
    return [{"id": "claims.verified", "status": "fail" if bad else "pass", "detail": detail}]


def path_of(job: Job, source: dict[str, Any]) -> Path:
    return job.folder / str(source["snapshot"])
