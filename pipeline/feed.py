"""Build the daily feed: written questions and statements, screened for tech topics.

Output matches the file the reader's Power Automate flow used to save
(parliament-YYYY-MM-DD.json), so the Copilot Cowork briefing can read either:
generatedUtc, fromDate, toDate, questionsScanned, writtenQuestions,
writtenStatements, plus warnings and a few extra counts.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone

from api import QS_API, Api
from semantic import candidates, classify
from topics import DEPARTMENTS, match_topics, screen_question

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

    # Layers 1-3: keyword rules, watched departments, watched members.
    wq, missed = [], []
    layer_counts = {"keyword": 0, "department": 0, "watchlist": 0, "semantic": 0}
    for q in full_questions:
        topics, layers = screen_question(q)
        if layers:
            for l in layers:
                layer_counts[l] += 1
            wq.append({**q, "matched": _flat(topics), "topics": topics, "matchedBy": layers})
        else:
            missed.append(q)
    # Layer 4: the AI classifier reads everything the rules missed.
    flagged, err = classify(candidates(missed))
    if err:
        warnings.append(err)
    for q in missed:
        f = flagged.get(q.get("id"))
        if f:
            layer_counts["semantic"] += 1
            wq.append({**q, "matched": [f"AI: {f['reason']}"], "topics": {f["topic"]: [f["reason"]]},
                       "matchedBy": ["semantic"]})
    ws = []
    for s in full_statements:
        m = match_topics(s.get("title"), s.get("text"))
        layers = ["keyword"] if m else []
        if (s.get("answeringBodyName") or "") in DEPARTMENTS:
            layers.append("department")
            m.setdefault(f"{s.get('answeringBodyName')} business", [s.get("answeringBodyName")])
        if layers:
            ws.append({**s, "matched": _flat(m), "topics": m, "matchedBy": layers})

    if api.failures:
        warnings.append(f"{len(api.failures)} individual requests failed after retries; see the run log.")

    return {
        "generatedUtc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "fromDate": f,
        "toDate": t,
        "questionsScanned": len(questions),
        "statementsScanned": len(statements),
        "counts": counts,
        "layers": layer_counts,
        "aiClassifierRan": err is None,
        "writtenQuestions": sorted(wq, key=lambda q: (q.get("answeringBodyName") or "", q.get("uin") or "")),
        "writtenStatements": ws,
        "warnings": warnings,
    }
