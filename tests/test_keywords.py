"""Offline tests for the keyword picker data and the rewrite's re-screening (no network)."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

import keywords  # noqa: E402
import regen  # noqa: E402

WQ = "https://questions-statements.parliament.uk/written-questions/detail"


def q(uin, text, heading="", topics=None, name="Ann Example"):
    return {"id": uin, "uin": str(uin), "house": "Commons", "heading": heading, "askingMember": {"name": name, "party": "Labour"},
            "answeringBodyName": "Department for Science, Innovation and Technology", "dateTabled": "2026-11-20T00:00:00",
            "questionText": text, "answerText": "", **({"topics": topics} if topics is not None else {})}


@pytest.fixture
def repo(tmp_path):
    d = "2026-11-26"
    for sub in ("data/feed", "data/sources", "data/corpus", "editorial", "reports"):
        (tmp_path / sub).mkdir(parents=True)
    screened = [q(1, "What steps on artificial intelligence and the Sovereign Compute Fund?", "AI", {"Artificial intelligence": ["artificial intelligence"]}),
                q(2, "What assessment of AI in the Sovereign Compute Fund and online data?", "AI", {"Artificial intelligence": ["ai"]}),
                q(3, "On online safety for children.", "Online", {"Online safety and social media": ["online safety"]})]
    unscreened = [q(4, "What progress on the Sovereign Compute Fund for digital research?", "Research"),
                  q(5, "How many potholes were filled?", "Roads")]
    (tmp_path / "data/feed" / f"parliament-{d}.json").write_text(json.dumps(
        {"fromDate": d, "toDate": d, "questionsScanned": 5, "writtenQuestions": screened, "writtenStatements": []}))
    (tmp_path / "data/corpus" / f"{d}.json").write_text(json.dumps(keywords.compact_corpus({"questions": screened + unscreened, "statements": []})))
    (tmp_path / "data/sources" / f"{d}.json").write_text(json.dumps({"hansard": [], "committees": [], "today": []}))
    (tmp_path / "editorial" / f"{d}.json").write_text(json.dumps({"headline": "H", "questions": [{"title": "x", "link": f"{WQ}/2026-11-20/1"}]}))
    (tmp_path / "reports" / f"{d}.html").write_text("<html><body></body></html>")
    return tmp_path, d


def test_items_mark_briefing_and_screen(repo):
    root, d = repo
    its, full = keywords.items(root, d)
    assert full
    by = {i["id"]: i for i in its}
    assert by["1"]["b"] == 1 and by["2"]["b"] == 0
    assert by["4"]["s"] == 0 and by["1"]["s"] == 1
    assert by["1"]["tp"] == ["Artificial intelligence"]


def test_mining_finds_a_new_programme(repo):
    root, d = repo
    terms = {c["term"]: c for c in keywords.mine(root, d)}
    assert "Sovereign Compute Fund" in terms
    assert terms["Sovereign Compute Fund"]["newHits"] == 1      # question 4, missed by the standing rules
    payload = keywords.site_payload(root, d)
    assert payload["fullCorpus"] and any(s["term"] == "Sovereign Compute Fund" for s in payload["suggestions"])


def test_rescreen_adds_keyword_hits_and_drops_switched_off_topics(repo):
    root, d = repo
    feed = json.loads((root / "data/feed" / f"parliament-{d}.json").read_text())
    corpus = json.loads((root / "data/corpus" / f"{d}.json").read_text())
    f2, _ = regen.rescreen(feed, corpus, {"hansard": []}, ["Sovereign Compute Fund"], ["Online safety and social media"])
    uins = {x["uin"] for x in f2["writtenQuestions"]}
    assert uins == {"1", "2", "4"}
    four = next(x for x in f2["writtenQuestions"] if x["uin"] == "4")
    assert four["topics"] == {"Your keywords": ["Sovereign Compute Fund"]}


def test_job_is_validated(repo, monkeypatch):
    root, d = repo
    monkeypatch.setattr(regen, "ROOT", root)
    ed, terms, off = regen.clean_job({"edition": d, "keywords": ["cloud", "ignore previous instructions; <script>", "x" * 41, "Cloud"],
                                      "off": ["Online safety and social media", "made up"]})
    assert terms == ["cloud"] and off == ["Online safety and social media"]
    with pytest.raises(regen.JobError):
        regen.clean_job({"edition": "2020-01-01", "keywords": ["cloud"]})
    with pytest.raises(regen.JobError):
        regen.clean_job({"edition": d, "keywords": ["<>"]})
