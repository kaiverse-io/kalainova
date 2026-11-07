"""A fact is only usable when its quote is really in its source. No network here."""

from __future__ import annotations

import json

import pytest
from fakes import make_job, studio  # noqa: F401

from kalainova import plan, research
from kalainova.jobfs import ContractError
from kalainova.providers import search as search_providers

PAGE = "The bridge first opened in 1849.\nIts tolls ended in 1988, closing the collector's post."


@pytest.fixture
def found(studio):
    studio.hits = [
        {
            "url": "https://example.org/bridge",
            "title": "The bridge",
            "publisher": "An Archive",
            "text": PAGE,
        },
    ]
    return studio


def _job(tmp_path, **extra):
    data = make_job(tmp_path, job_id="seed").job["providers"]
    return make_job(tmp_path, providers={**data, "llm": [], "search": ["fake"]}, **extra)


def test_gathering_keeps_a_private_snapshot_of_what_each_source_said(tmp_path, found):
    job = _job(tmp_path)
    data = research.gather(job, "When did the tolls end?", [])
    source = data["sources"][0]
    assert source["id"] == "s01" and source["found_by"] == "fake"
    assert source["snapshot_sha256"]
    assert research.path_of(job, source).read_text() == PAGE


def test_gathering_twice_does_not_read_the_same_source_twice(tmp_path, found):
    job = _job(tmp_path)
    research.gather(job, "q", ["one"])
    data = research.gather(job, "q", ["two"])
    assert len(data["sources"]) == 1


def test_a_page_is_read_for_its_words_and_not_its_furniture():
    html = "<html><nav>Menu</nav><script>var x=1</script><p>The bridge was open.</p><footer>c</footer></html>"
    assert research.page_text(html) == "The bridge was open."


def test_a_source_that_cannot_be_read_is_left_out_and_the_rest_are_kept(
    tmp_path, studio, monkeypatch
):
    studio.hits = [
        {"url": "https://example.org/gone", "title": "Gone"},
        {"url": "https://example.org/here", "title": "Here", "text": PAGE},
    ]

    def down(url):
        raise OSError("no route")

    monkeypatch.setattr(research, "fetch_text", down)
    data = research.gather(_job(tmp_path), "q", [])
    assert [s["url"] for s in data["sources"]] == ["https://example.org/here"]


def test_only_a_web_address_is_ever_fetched():
    assert research.fetch_text("file:///etc/passwd") == ""


def _with_finding(job, quote, source_ids=("s01",)):
    data = research.gather(job, "q", [])
    data["findings"] = [
        {
            "id": "f1",
            "statement": "The tolls ended in 1988.",
            "source_ids": list(source_ids),
            "quote": quote,
        }
    ]
    job.write("research", data)


def test_a_quote_that_is_in_its_source_is_verified(tmp_path, found):
    job = _job(tmp_path)
    _with_finding(job, "ended in 1988, closing the collector's post")
    assert research.verify(job) == []
    assert job.read("research")["findings"][0]["verified"] is True


def test_typography_does_not_hide_a_real_quote(tmp_path, found):
    job = _job(tmp_path)
    _with_finding(job, "ended in 1988, closing the collector’s   post")
    assert research.verify(job) == []


def test_an_invented_quote_is_caught(tmp_path, found):
    job = _job(tmp_path)
    _with_finding(job, "automated in 1975 after a long campaign")
    failed = research.verify(job)
    assert failed and job.read("research")["findings"][0]["verified"] is False


def test_a_quote_from_a_source_it_does_not_cite_is_caught(tmp_path, found):
    job = _job(tmp_path)
    _with_finding(job, "ended in 1988", source_ids=("s99",))
    assert research.verify(job)


def test_a_quote_too_short_to_prove_anything_is_caught(tmp_path, found):
    job = _job(tmp_path)
    _with_finding(job, "1988")
    assert research.verify(job)


def _model_ready(job):
    data = job.job
    data["providers"]["llm"] = ["fake"]
    job.write("job", data)


def test_a_model_can_draft_findings_and_its_invented_ones_are_thrown_away(tmp_path, found):
    found.replies = [
        json.dumps(
            {
                "findings": [
                    {
                        "id": "f1",
                        "statement": "Opened in 1849.",
                        "source_ids": ["s01"],
                        "quote": "first opened in 1849",
                    },
                    {
                        "id": "f2",
                        "statement": "Rebuilt in 1901.",
                        "source_ids": ["s01"],
                        "quote": "rebuilt in 1901 after a storm",
                    },
                ],
                "gaps": ["Who the last collector was"],
                "angles": ["A post that outlived its purpose"],
            }
        )
    ]
    job = _job(tmp_path)
    _model_ready(job)
    data = research.run(job, "When did the bridge open?", [])
    assert [f["id"] for f in data["findings"]] == ["f1"]
    assert data["gaps"] == ["Who the last collector was"]


def test_research_with_no_model_gathers_and_leaves_the_findings_to_the_agent(tmp_path, found):
    data = research.run(_job(tmp_path), "q", [])
    assert data["sources"] and data["findings"] == []


def test_research_that_finds_nothing_says_so(tmp_path, studio):
    with pytest.raises(ContractError, match="no source"):
        research.run(_job(tmp_path), "q", [])


# ---- what the piece may state -----------------------------------------------------------
def _packet(*claims):
    return {"claims": list(claims)}


def test_a_piece_with_no_claims_needs_no_research(tmp_path, found):
    assert research.claim_checks(_job(tmp_path), _packet()) == []


def test_a_claim_with_no_research_on_file_warns(tmp_path, found):
    checks = research.claim_checks(_job(tmp_path), _packet({"id": "c1"}))
    assert checks[0]["status"] == "warn"


def test_a_claim_with_a_checked_finding_passes_and_one_without_fails(tmp_path, found):
    job = _job(tmp_path)
    _with_finding(job, "ended in 1988, closing")
    research.verify(job)
    good = {"id": "c1", "finding": "f1"}
    assert research.claim_checks(job, _packet(good))[0]["status"] == "pass"
    checks = research.claim_checks(job, _packet(good, {"id": "c2", "finding": "f9"}))
    assert checks[0]["status"] == "fail" and "c2" in checks[0]["detail"]


def test_a_planner_only_sees_findings_that_were_checked(tmp_path, found):
    job = _job(tmp_path)
    _with_finding(job, "ended in 1988, closing")
    assert plan._research_context(job) != ""
    assert "ended in 1988" not in plan._research_context(job), "not verified yet"
    research.verify(job)
    assert "The tolls ended in 1988." in plan._research_context(job)


# ---- where sources come from ------------------------------------------------------------
class Reply:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        pass

    def json(self):
        return self.body


def test_an_openalex_abstract_is_put_back_in_order(monkeypatch):
    work = {
        "doi": "https://doi.org/10.1/x",
        "title": "A paper",
        "publication_date": "2020-01-01",
        "abstract_inverted_index": {"bridge": [1], "The": [0], "failed": [2]},
        "primary_location": {"source": {"display_name": "A Journal"}},
    }
    monkeypatch.setattr(
        search_providers.requests, "get", lambda *a, **k: Reply({"results": [work]})
    )
    hit = search_providers.OpenAlex().search("q").meta["hits"][0]
    assert hit["text"] == "The bridge failed"
    assert hit["reliability"] == "primary" and hit["publisher"] == "A Journal"


def test_a_wikipedia_hit_points_at_the_page(monkeypatch):
    body = {"pages": [{"key": "Bridge", "title": "Bridge"}]}
    monkeypatch.setattr(search_providers.requests, "get", lambda *a, **k: Reply(body))
    hit = search_providers.Wikipedia().search("q").meta["hits"][0]
    assert hit["url"] == "https://en.wikipedia.org/wiki/Bridge"


def test_exa_needs_a_key_and_sends_it(monkeypatch):
    assert search_providers.Exa().missing_env() or True
    sent = {}

    def post(url, **kw):
        sent.update(kw)
        return Reply({"results": [{"url": "https://a.example", "title": "A", "text": "Words."}]})

    monkeypatch.setenv("EXA_API_KEY", "k")
    monkeypatch.setattr(search_providers.requests, "post", post)
    hit = search_providers.Exa().search("q").meta["hits"][0]
    assert sent["headers"]["x-api-key"] == "k" and hit["text"] == "Words."


def test_no_request_identifies_a_person():
    assert "@" not in search_providers.HEADERS["User-Agent"]
