"""Offline tests for the archive, themes and timeline (no network)."""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import importlib.util  # noqa: E402

import news  # noqa: E402
import trends  # noqa: E402

# pipeline/site.py shares its name with Python's own site module, so load it by path
_spec = importlib.util.spec_from_file_location("briefing_site", Path(__file__).resolve().parent.parent / "pipeline" / "site.py")
sitemod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sitemod)

DCMS = "Department for Digital, Culture, Media and Sport"


def wq(uin, member, text, tabled, heading="", body=DCMS, topics=None, mid=None):
    return {"uin": uin, "askingMemberId": mid or member, "askingMember": {"id": mid or member, "name": member, "partyAbbreviation": "Lab"},
            "heading": heading, "answeringBodyName": body, "dateTabled": f"{tabled}T00:00:00",
            "questionText": text, "topics": topics or {"Artificial intelligence": ["ai"]}}


def write_repo(tmp: Path, feeds: dict, sources=None):
    for d in ("data/feed", "data/sources", "editorial", "reports"):
        (tmp / d).mkdir(parents=True, exist_ok=True)
    for ed, qs in feeds.items():
        (tmp / "data/feed" / f"parliament-{ed}.json").write_text(json.dumps(
            {"fromDate": ed, "toDate": ed, "questionsScanned": 100, "writtenQuestions": qs, "writtenStatements": []}))
        (tmp / "editorial" / f"{ed}.json").write_text(json.dumps({"headline": f"Headline {ed}", "summary": "Sum"}))
        (tmp / "editorial" / f"{ed}.validation.json").write_text(json.dumps({"verdict": "pass"}))
        (tmp / "reports" / f"{ed}.html").write_text(f"<!DOCTYPE html><html><head></head><body><h1>Report {ed}</h1></body></html>")
    if sources:
        (tmp / "data/sources" / f"{max(feeds)}.json").write_text(json.dumps({"hansard": sources}))


FEEDS = {
    "2026-11-23": [
        wq("100", "Ann Lee", "To ask the Minister for the Cabinet Office, whether the AI Taskforce will publish a report.", "2026-11-18", "AI Taskforce", "Cabinet Office", mid="1"),
        wq("43125", "Adam Dance", "To ask the Secretary of State for Digital, Culture, Media and Sport, what the cost was of the Microsoft 365 outage.",
           "2026-11-13", "Microsoft: Outages", topics={"Microsoft and its businesses": ["microsoft"]}, mid="2"),
        wq("200", "Ben Cole", "To ask the Secretary of State, how many data centre applications were received in each local authority area last year.", "2026-11-10", "Data Centres: Planning", mid="3",
           topics={"Cloud, data centres and compute": ["data centre"]}),
    ],
    "2026-11-24": [
        wq("101", "Ann Lee", "To ask the Minister for the Cabinet Office, pursuant to the answer to Question 100, what objectives the AI Taskforce has.", "2026-11-19", "AI Taskforce", "Cabinet Office", mid="1"),
        wq("102", "Ann Lee", "To ask the Minister for the Cabinet Office, pursuant to the answer to Question 100, how often the Taskforce meets.", "2026-11-19", "AI Taskforce", "Cabinet Office", mid="1"),
        wq("46113", "Navendu Mishra", "To ask the hon. Member, what assessment has been made of the Microsoft outage on Parliament.", "2026-11-24",
           topics={"Microsoft and its businesses": ["microsoft"]}, mid="4"),
        wq("201", "Cara Moss", "To ask the Secretary of State, how many data centre applications were received in each local authority area this year.", "2026-11-12", "Data Centres", mid="5",
           topics={"Cloud, data centres and compute": ["data centre"]}),
        wq("202", "Dev Shah", "To ask the Secretary of State, what community benefit data centres must provide.", "2026-11-20", "Data Centres", mid="6",
           topics={"Cloud, data centres and compute": ["data centre"]}),
    ],
}


def test_threads_find_each_kind(tmp_path):
    write_repo(tmp_path, FEEDS)
    a = trends.analyse(tmp_path)
    kinds = {t["kind"]: t for t in a["threads"]}
    assert {"followup", "subject", "wording"} <= set(kinds)
    fu = kinds["followup"]
    assert {i["uin"] for i in fu["items"]} == {"100", "101", "102"}  # links back to the cited answer
    subj = [t for t in a["threads"] if t["kind"] == "subject" and t["title"].startswith("Data Centres")][0]
    assert len(subj["members"]) == 3  # "Data Centres" and "Data Centres: Planning" share a subject
    assert any(t["title"].startswith("Microsoft named") for t in a["threads"])
    assert a["threads"][0]["microsoft"]  # Microsoft threads rank first
    states = {t["title"]: t["state"] for t in a["byEdition"]["2026-11-24"]}
    assert any(s == "growing" for s in states.values())
    assert a["rising"] == []  # not enough history yet


def test_news_links_direct_and_possible(tmp_path):
    write_repo(tmp_path, FEEDS, sources=[{"date": "2026-11-24", "debate": "Cyber Bill", "speaker": "Victoria Collins",
                                          "text": "the Microsoft outage showed the risk", "link": "https://hansard.parliament.uk/x"}])
    (tmp_path / "data/events.json").write_text(json.dumps([{"date": "2026-11-12", "endDate": "2026-11-13", "title": "Microsoft 365 outage",
                                                             "kind": "incident", "source": "https://example.org/a",
                                                             "topics": ["Microsoft and its businesses"], "terms": [["microsoft"], ["outage"]]}]))
    items, _ = trends.load(tmp_path)

    def fake_get(url):
        if "gov.uk" in url:
            return {"results": [{"title": "CMA update on cloud services market", "link": "/government/news/x",
                                 "public_timestamp": "2026-11-20T09:00:00Z", "organisations": [{"title": "CMA"}]},
                                {"title": "Farming grants open", "link": "/y", "public_timestamp": "2026-11-20T09:00:00Z"}]}
        if "timelinevolraw" in url:
            return {"timeline": [{"data": [{"date": "20261112T000000Z", "value": 40}, {"date": "20261113T000000Z", "value": 25}]}]}
        return {"articles": [{"url": "https://news.example/a", "title": "Outage hits users", "seendate": "20261112T101500Z", "domain": "news.example"},
                             {"url": "javascript:alert(1)", "title": "bad", "seendate": "20261112T101500Z"}]}

    r = news.collect(items, date(2026, 11, 24), speeches=trends.speeches(tmp_path), root=tmp_path, get=fake_get)
    outage = [x for x in r["events"] if x["title"] == "Microsoft 365 outage"][0]
    assert [d["uin"] for d in outage["direct"]] == ["43125", "46113", None]  # two questions and the speech, by lag
    assert outage["direct"][0]["lag"] == 1
    assert [x["title"] for x in r["events"] if x["origin"] == "GOV.UK"] == ["CMA update on cloud services market"]
    assert r["volume"]["2026-11-12"] == 40
    assert all(h["source"].startswith("https://") for h in r["headlines"])  # unsafe links dropped
    assert r["gaps"] == []


def test_news_failure_is_a_gap(tmp_path):
    write_repo(tmp_path, FEEDS)

    def down(url):
        raise OSError("offline")

    r = news.collect([], date(2026, 11, 24), root=tmp_path, get=down)
    assert len(r["gaps"]) == 2 and r["events"] == []


def test_govuk_ignores_a_publisher_naming_itself():
    def result(title, desc=""):
        return {"title": title, "description": desc, "link": "/x", "public_timestamp": "2026-11-26T09:00:00Z",
                "organisations": [{"title": "Competition and Markets Authority"}]}
    res = [result("CMA study reveals catalogue of concerns in private dentistry market", "The CMA has published"),
           result("CMA opens cloud market investigation", "The CMA is looking at cloud services")]
    got = news.govuk(date(2026, 11, 1), get=lambda url: {"results": res})
    assert [e["title"] for e in got] == ["CMA opens cloud market investigation"]


def test_site_builds_with_navigation(tmp_path, monkeypatch):
    write_repo(tmp_path, FEEDS)
    monkeypatch.setattr(sitemod, "ROOT", tmp_path)
    monkeypatch.setattr(sitemod, "OUT", tmp_path / "_site")
    monkeypatch.setenv("NEWS_DISABLED", "true")
    assert sitemod.build() == 0
    out = tmp_path / "_site"
    first, last = (out / "2026-11-23.html").read_text(), (out / "2026-11-24.html").read_text()
    assert 'href="2026-11-24.html" rel="next"' in first and "First edition" in first
    assert 'href="2026-11-23.html" rel="prev"' in last and "Newest edition" in last
    assert "Continuing threads" in last and "themes.html#" in last
    assert last.index("pb-bar") < last.index("<h1>Report")  # bar sits at the top of the body
    assert "2026-11-24.html" in (out / "latest.html").read_text()
    idx = (out / "index.html").read_text()
    assert "Headline 2026-11-24" in idx and 'class="cal"' in idx
    rows = json.loads((out / "search.json").read_text())
    assert {r["u"] for r in rows} >= {"43125", "101"} and all(r["l"].startswith("https://questions-statements.parliament.uk/") for r in rows)
    assert "Follow-up questions" in (out / "themes.html").read_text()
    tl = (out / "timeline.html").read_text()
    assert "NEWS_DISABLED" in tl
    assert '<a href="2026-11-2' in tl and 'class="day go"' in tl and 'class="legend"' in tl  # bars open a briefing


def test_site_survives_analysis_failure(tmp_path, monkeypatch):
    write_repo(tmp_path, FEEDS)
    monkeypatch.setattr(sitemod, "ROOT", tmp_path)
    monkeypatch.setattr(sitemod, "OUT", tmp_path / "_site")
    monkeypatch.setattr(trends, "analyse", lambda root: (_ for _ in ()).throw(ValueError("boom")))
    assert sitemod.build() == 0
    assert "could not be built" in (tmp_path / "_site" / "themes.html").read_text()
    assert 'rel="prev"' in (tmp_path / "_site" / "2026-11-24.html").read_text()


def test_internal_names_never_reach_a_page(tmp_path, monkeypatch):
    from redact import scrub
    assert scrub("central to Hugh&#x27;s brief") == "central to the reader's brief"
    assert scrub("Hugh needs to track this") == "The reader needs to track this"
    assert "microsoft.com" not in scrub("send to jo.bloggs@microsoft.com")
    assert "CELA" not in scrub("Daily briefing for Microsoft UK CELA")
    monkeypatch.setenv("REDACT_TERMS", "Dana Fox")
    assert scrub("see Dana Fox's note") == "see the reader's note"
    assert scrub("Hugh Gaffney (Lab) asked") == "Hugh Gaffney (Lab) asked"  # a member's name is left alone
    write_repo(tmp_path, FEEDS)
    (tmp_path / "reports" / "2026-11-24.html").write_text("<html><body><p>Hugh&#x27;s brief, for CELA</p></body></html>")
    monkeypatch.setattr(sitemod, "ROOT", tmp_path)
    monkeypatch.setattr(sitemod, "OUT", tmp_path / "_site")
    monkeypatch.setenv("NEWS_DISABLED", "true")
    assert sitemod.build() == 0
    for f in (tmp_path / "_site").glob("*.html"):
        text = f.read_text()
        assert "Hugh" not in text and "CELA" not in text, f.name
