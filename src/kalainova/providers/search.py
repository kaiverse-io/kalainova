"""Where research starts. Each returns candidate sources, and nothing here decides what is true.

Wikipedia and OpenAlex are free with no key and good for finding primary sources. Exa finds pages on
the open web and needs a key. A request names this project and never a person.
"""

from __future__ import annotations

import os

import requests

from .. import HTTP_HEADERS
from .base import Provider, register
from .contract import Context, Hit, Result, SearchRequest
from .transport import Https, Transport, raise_for

TIMEOUT = 30
HEADERS = HTTP_HEADERS


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

    def search(self, req: SearchRequest, ctx: Context) -> Result:
        found = requests.get(
            "https://en.wikipedia.org/w/rest.php/v1/search/page",
            params={"q": req.query, "limit": str(req.limit)},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        raise_for(found, self.name)
        hits: list[Hit] = []
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
        return Result(model="wikipedia", hits=hits)


@register
class OpenAlex(Provider):
    name = "openalex"
    capabilities = ("search",)
    free = True
    synthetic = False

    def search(self, req: SearchRequest, ctx: Context) -> Result:
        found = requests.get(
            "https://api.openalex.org/works",
            params={"search": req.query, "per-page": str(req.limit)},
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        raise_for(found, self.name)
        hits: list[Hit] = []
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
        return Result(model="openalex", hits=hits)


def _exa_headers() -> dict[str, str]:
    return {**HEADERS, "x-api-key": os.environ["EXA_API_KEY"]}


@register
class Exa(Provider):
    name = "exa"
    capabilities = ("search",)
    env_key = "EXA_API_KEY"
    synthetic = False
    rehearses = True
    transport: Transport = Https("exa", "https://api.exa.ai", _exa_headers)

    def search(self, req: SearchRequest, ctx: Context) -> Result:
        body = {"query": req.query, "numResults": req.limit, "contents": {"text": True}}
        reply = self.transport.send("search", body, ctx, wait=TIMEOUT)
        hits: list[Hit] = [
            {
                "url": str(item.get("url", "")),
                "title": str(item.get("title") or item.get("url", "")),
                "published": str(item.get("publishedDate") or ""),
                "reliability": "unknown",
                "text": str(item.get("text") or ""),
            }
            for item in reply.get("results", [])
            if item.get("url")
        ]
        return Result(model="exa", hits=hits)
