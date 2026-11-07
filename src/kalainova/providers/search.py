"""Where research starts. Each returns candidate sources, and nothing here decides what is true.

Wikipedia and OpenAlex are free with no key and good for finding primary sources. Exa finds pages on
the open web and needs a key. A request names this project and never a person.
"""

from __future__ import annotations

import os
from typing import Any

import requests

from .base import Provider, Result, register

TIMEOUT = 30
HEADERS = {"User-Agent": "Kalainova/0.1 (https://github.com/kaiverse-io/kalainova)"}


def _abstract(inverted: dict[str, list[int]] | None) -> str:
    """OpenAlex stores an abstract as word positions, so it has to be put back in order."""
    if not inverted:
        return ""
    placed = sorted((at, word) for word, spots in inverted.items() for at in spots)
    return " ".join(word for _, word in placed)


@register
class Wikipedia(Provider):
    name = "wikipedia"
    capabilities = ("search",)
    free = True
    synthetic = False

    def search(self, query: str, *, limit: int = 5, **kw: Any) -> Result:
        found = requests.get(
            "https://en.wikipedia.org/w/rest.php/v1/search/page",
            params={"q": query, "limit": str(limit)},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        found.raise_for_status()
        hits = []
        for page in found.json().get("pages", []):
            title = str(page.get("key", ""))
            hits.append(
                {
                    "url": f"https://en.wikipedia.org/wiki/{title}",
                    "title": str(page.get("title", title)),
                    "publisher": "Wikipedia",
                    "reliability": "reference",
                }
            )
        return Result(model="wikipedia", meta={"hits": hits})


@register
class OpenAlex(Provider):
    name = "openalex"
    capabilities = ("search",)
    free = True
    synthetic = False

    def search(self, query: str, *, limit: int = 5, **kw: Any) -> Result:
        found = requests.get(
            "https://api.openalex.org/works",
            params={"search": query, "per-page": str(limit)},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        found.raise_for_status()
        hits = []
        for work in found.json().get("results", []):
            url = work.get("doi") or work.get("id")
            if not url:
                continue
            source = ((work.get("primary_location") or {}).get("source") or {}).get("display_name")
            hits.append(
                {
                    "url": str(url),
                    "title": str(work.get("title") or url),
                    "publisher": str(source or "OpenAlex"),
                    "published": str(work.get("publication_date") or ""),
                    "reliability": "primary",
                    "text": _abstract(work.get("abstract_inverted_index")),
                }
            )
        return Result(model="openalex", meta={"hits": hits})


@register
class Exa(Provider):
    name = "exa"
    capabilities = ("search",)
    env_key = "EXA_API_KEY"
    synthetic = False

    def search(self, query: str, *, limit: int = 5, **kw: Any) -> Result:
        found = requests.post(
            "https://api.exa.ai/search",
            headers={**HEADERS, "x-api-key": os.environ[self.env_key]},
            json={"query": query, "numResults": limit, "contents": {"text": True}},
            timeout=TIMEOUT,
        )
        found.raise_for_status()
        hits = [
            {
                "url": str(item.get("url", "")),
                "title": str(item.get("title") or item.get("url", "")),
                "published": str(item.get("publishedDate") or ""),
                "reliability": "unknown",
                "text": str(item.get("text") or ""),
            }
            for item in found.json().get("results", [])
            if item.get("url")
        ]
        return Result(model="exa", meta={"hits": hits})
