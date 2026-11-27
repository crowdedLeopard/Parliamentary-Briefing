"""Machine-readable form of each edition, for agents and other tools.

site.py writes, for every edition:
  data/<date>.json   the briefing as JSON (schema below)
  data/index.json    every edition, newest first, with links to its HTML and JSON
and mailer.py attaches the same JSON to the daily email.

Edition JSON (schemaVersion 1):
  edition, runDate, period {from, to}, sitting (one sentence), validation {verdict, writer, validator},
  title, headline, summary,
  sections {very_important, debates, questions, committees, other}: items {title, who, where, date,
            body, why, link, tags}
  today: Parliament Today items {time, venue, lead, title, why, link}
  coverage: notes on what was screened and any gaps
  writtenQuestions: the screened-in questions {uin, house, heading, asker, party, department,
            dateTabled, dateAnswered, holding, topics, question, answer, link}
  writtenStatements: {uin, house, title, date, text, link}
  counts {questionsScanned, questionsMatched, statementsScanned, statementsMatched}
  links {html, json}
Everything passes through redact.scrub(), like the pages.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from redact import scrub  # noqa: E402
from topics import to_plain_text  # noqa: E402

WQ = "https://questions-statements.parliament.uk/written-questions/detail"
WS = "https://questions-statements.parliament.uk/written-statements/detail"
SECTIONS = ("very_important", "debates", "questions", "committees", "other")
ITEM_KEYS = ("title", "who", "where", "date", "body", "why", "link", "tags")


def _load(p: Path):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def edition(root: Path, d: str, site: str = "") -> dict | None:
    """The edition for date d as a dict, or None if it has no report."""
    if not (root / "reports" / f"{d}.html").exists():
        return None
    ed = _load(root / "editorial" / f"{d}.json") or {}
    v = _load(root / "editorial" / f"{d}.validation.json") or {}
    feed = _load(root / "data" / "feed" / f"parliament-{d}.json") or {}
    src = _load(root / "data" / "sources" / f"{d}.json") or {}
    st = _load(root / "data" / "status" / f"{d}.json") or {}
    qs = [{"uin": q.get("uin"), "house": q.get("house"), "heading": q.get("heading") or "",
           "asker": (q.get("askingMember") or {}).get("name"), "party": (q.get("askingMember") or {}).get("party"),
           "department": q.get("answeringBodyName"), "dateTabled": (q.get("dateTabled") or "")[:10],
           "dateAnswered": (q.get("dateAnswered") or "")[:10] or None, "holding": bool(q.get("answerIsHolding")),
           "topics": sorted((q.get("topics") or {}).keys()),
           "question": to_plain_text(q.get("questionText")), "answer": to_plain_text(q.get("answerText")) or None,
           "link": f"{WQ}/{(q.get('dateTabled') or '')[:10]}/{q.get('uin')}"} for q in feed.get("writtenQuestions", [])]
    ss = [{"uin": s.get("uin"), "house": s.get("house"), "title": s.get("title"), "date": (s.get("dateMade") or "")[:10],
           "text": to_plain_text(s.get("text")), "link": f"{WS}/{(s.get('dateMade') or '')[:10]}/{s.get('uin')}"}
          for s in feed.get("writtenStatements", [])]
    out = {
        "schemaVersion": 1, "edition": d, "runDate": ed.get("today_date") or st.get("runDate"),
        "period": {"from": feed.get("fromDate"), "to": feed.get("toDate") or d},
        "sitting": (src.get("sitting") or {}).get("summary") or st.get("sitting"),
        "validation": {"verdict": v.get("verdict", "not run"), "writer": v.get("writer"), "validator": v.get("validator")},
        "title": ed.get("title"), "headline": ed.get("headline"), "summary": ed.get("summary"),
        "sections": {k: [{x: it.get(x) for x in ITEM_KEYS if it.get(x) is not None} for it in ed.get(k, [])] for k in SECTIONS},
        "today": ed.get("today", []), "coverage": ed.get("coverage", []),
        "writtenQuestions": qs, "writtenStatements": ss,
        "counts": {"questionsScanned": feed.get("questionsScanned"), "questionsMatched": len(qs),
                   "statementsScanned": feed.get("statementsScanned"), "statementsMatched": len(ss)},
        "links": {"html": f"{site}{d}.html", "json": f"{site}data/{d}.json"},
    }
    return json.loads(scrub(json.dumps(out, ensure_ascii=False)))


def index(eds: list[dict], site: str = "") -> dict:
    rows = [{"edition": x["edition"], "title": x.get("title"), "headline": x.get("headline"),
             "verdict": x["validation"]["verdict"], "html": x["links"]["html"], "json": x["links"]["json"]}
            for x in sorted(eds, key=lambda x: x["edition"], reverse=True)]
    return {"schemaVersion": 1, "latest": rows[0]["edition"] if rows else None, "editions": rows}


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=1)
