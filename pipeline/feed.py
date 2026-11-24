"""Build the daily feed: written questions and statements, screened for tech topics.

Output matches the file Hugh's Power Automate flow used to save
(parliament-YYYY-MM-DD.json), so the Copilot Cowork briefing can read either:
generatedUtc, fromDate, toDate, questionsScanned, writtenQuestions,
writtenStatements, plus warnings and a few extra counts.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from api import QS_API, Api
from topics import match_topics

log = logging.getLogger("feed")
TRUNCATED = 250  # list endpoints cut question/answer/statement text at ~255 characters


def window(run_date: date) -> tuple[str, str]:
    """Yesterday, or Friday to Sunday when run on a Monday."""
    to_d = run_date - timedelta(days=1)
    from_d = run_date - timedelta(days=3) if run_date.weekday() == 0 else to_d
    return from_d.isoformat(), to_d.isoformat()


def _flat(matched: dict[str, list[str]]) -> list[str]:
    return sorted({w for words in matched.values() for w in words})


def build_feed(api: Api, run_date: date, workers: int = 4) -> dict:
    f, t = window(run_date)
    warnings: list[str] = []
    counts: dict[str, int] = {}

    def fetch(label: str, path: str, params: dict) -> list[dict]:
        items, complete = api.get_all(path, params)
        counts[label] = len(items)
        log.info("%s: %d", label, len(items))
        if not complete:
            warnings.append(f"{label}: request failed or was incomplete after retries ({len(items)} records received).")
        return items

    questions: dict[int, dict] = {}
    for kind, key in (("answered", "answeredWhen"), ("tabled", "tabledWhen")):
        for house in ("Commons", "Lords"):
            for q in fetch(f"{kind} {house}", "writtenquestions/questions",
                           {f"{key}From": f, f"{key}To": t, "house": house, "expandMember": "true"}):
                qid = q.get("id")
                if qid not in questions or (q.get("answerText") and not questions[qid].get("answerText")):
                    questions[qid] = q
    statements = fetch("statements", "writtenstatements/statements",
                       {"madeWhenFrom": f, "madeWhenTo": t, "expandMember": "true"})

    # The list endpoints truncate text, so fetch full records before screening.
    def full_q(q: dict) -> dict:
        if len(q.get("questionText") or "") >= TRUNCATED or len(q.get("answerText") or "") >= TRUNCATED:
            d = api.get(f"{QS_API}/writtenquestions/questions/{q['id']}", {"expandMember": "true"}, retries=2)
            if d:
                return d.get("value", d)
        return q

    def full_s(s: dict) -> dict:
        if len(s.get("text") or "") >= TRUNCATED:
            d = api.get(f"{QS_API}/writtenstatements/statements/{s['id']}", {"expandMember": "true"}, retries=2)
            if d:
                return d.get("value", d)
        return s

    with ThreadPoolExecutor(workers) as pool:
        full_questions = list(pool.map(full_q, questions.values()))
        full_statements = list(pool.map(full_s, statements))
    counts["apiCalls"] = api.calls

    wq = []
    for q in full_questions:
        m = match_topics(q.get("heading"), q.get("questionText"), q.get("answerText"))
        if m:
            wq.append({**q, "matched": _flat(m), "topics": m})
    ws = []
    for s in full_statements:
        m = match_topics(s.get("title"), s.get("text"))
        if m:
            ws.append({**s, "matched": _flat(m), "topics": m})

    if api.failures:
        warnings.append(f"{len(api.failures)} individual requests failed after retries; see the run log.")

    return {
        "generatedUtc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "fromDate": f,
        "toDate": t,
        "questionsScanned": len(questions),
        "statementsScanned": len(statements),
        "counts": counts,
        "writtenQuestions": sorted(wq, key=lambda q: (q.get("answeringBodyName") or "", q.get("uin") or "")),
        "writtenStatements": ws,
        "warnings": warnings,
    }
