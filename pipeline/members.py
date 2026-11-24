"""Evidence-based profiles of the members who asked relevant questions.

Everything comes from Parliament's own public record (Members API and the
Written Questions API): role, party, seat, committees, posts, registered
interests, self-declared policy focus and 12 months of written questions.
'Signals' are rule-based readings of that evidence, each citing its source.
Nothing here is about members' private lives.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from api import MEMBERS_API, QS_API, Api
from topics import TOPICS, match_topics, to_plain_text

log = logging.getLogger("members")
SITE = "https://members.parliament.uk/member"
WQ_SITE = "https://questions-statements.parliament.uk/written-questions/detail"
CACHE_DAYS = 7

TECH_COMMITTEE = re.compile(
    r"science|technology|digital|culture, media|communications|business|treasury|public accounts|"
    r"home affairs|national security|human rights|public administration|energy|economic affairs|"
    r"industry and regulators|artificial intelligence|international agreements|education", re.I)
TECH_INTEREST = re.compile(
    r"\b(ai|artificial intelligence|tech\w*|digital|data|software|cyber\w*|cloud|computing|"
    r"microsoft|google|amazon|meta|apple|openai|anthropic|nvidia|telecom\w*|internet|online|"
    r"turing|semiconductor\w*|quantum|start-?up|venture)\b", re.I)


def _v(d):
    return d.get("value", d) if isinstance(d, dict) else d


def _current(items: list[dict] | None) -> list[dict]:
    return [i for i in (items or []) if not i.get("endDate")]


def _fetch_member(api: Api, mid: int, run_date: date) -> dict:
    base = f"{MEMBERS_API}/Members/{mid}"
    core = _v(api.get(base, retries=2) or {})
    bio = _v(api.get(f"{base}/Biography", retries=2) or {})
    interests = _v(api.get(f"{base}/RegisteredInterests", retries=2) or [])
    focus = _v(api.get(f"{base}/Focus", retries=2) or [])
    synopsis = _v(api.get(f"{base}/Synopsis", retries=2) or "")
    since = (run_date - timedelta(days=365)).isoformat()
    history, complete = api.get_all("writtenquestions/questions",
                                    {"askingMemberId": mid, "tabledWhenFrom": since})
    return {"id": mid, "fetchedOn": run_date.isoformat(), "core": core, "bio": bio,
            "interests": interests, "focus": focus, "synopsis": synopsis,
            "history": [{"id": q.get("id"), "uin": q.get("uin"), "heading": q.get("heading"),
                         "questionText": q.get("questionText"), "dateTabled": q.get("dateTabled"),
                         "answeringBodyName": q.get("answeringBodyName")} for q in history],
            "historyComplete": complete}


def load_member(api: Api, mid: int, run_date: date, cache_dir: Path) -> dict:
    path = cache_dir / f"{mid}.json"
    if path.exists():
        cached = json.loads(path.read_text())
        if (run_date - date.fromisoformat(cached["fetchedOn"])).days < CACHE_DAYS:
            return cached
    data = _fetch_member(api, mid, run_date)
    if data["core"]:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    return data


def _interest_lines(interests) -> list[str]:
    out = []
    for cat in interests or []:
        for it in cat.get("interests", []) or []:
            texts = [it.get("interest") or ""] + [c.get("interest") or "" for c in it.get("childInterests") or []]
            for t in texts:
                t = to_plain_text(t)
                if t and TECH_INTEREST.search(t):
                    out.append(f"{cat.get('name', 'Interest')}: {t[:220]}")
    return out[:6]


def profile(raw: dict, todays: list[dict]) -> dict:
    core, bio = raw["core"] or {}, raw["bio"] or {}
    hm = core.get("latestHouseMembership") or {}
    party = (core.get("latestParty") or {}).get("name")
    name = core.get("nameDisplayAs") or (todays[0].get("askingMember") or {}).get("name")
    house = "Lords" if hm.get("house") == 2 else "Commons"

    committees = [c.get("name") for c in _current(bio.get("committeeMemberships"))]
    gov = [p.get("name") for p in _current(bio.get("governmentPosts"))]
    opp = [p.get("name") for p in _current(bio.get("oppositionPosts"))]
    other = [p.get("name") for p in _current(bio.get("otherPosts"))]
    posts = gov + opp + other
    focus = [f for cat in raw.get("focus") or [] for f in cat.get("focus", []) or []]
    interests = _interest_lines(raw.get("interests"))

    # 12-month written-question history, screened on heading + question text.
    hist = raw.get("history") or []
    relevant, by_topic, depts = [], Counter(), Counter()
    for q in hist:
        m = match_topics(q.get("heading"), q.get("questionText"))
        depts[q.get("answeringBodyName") or "Other"] += 1
        if m:
            relevant.append((q, m))
            for label in m:
                by_topic[label] += 1
    relevant.sort(key=lambda x: x[0].get("dateTabled") or "", reverse=True)
    share = round(100 * len(relevant) / len(hist)) if hist else 0

    signals: list[str] = []
    if gov:
        signals.append(f"Government post ({gov[0]}): speaks for the Government rather than asking as a backbencher.")
    elif opp:
        signals.append(f"Opposition frontbench ({opp[0]}): questions are likely part of their party's scrutiny of that brief.")
    elif other:
        signals.append(f"Holds a party or parliamentary role ({other[0]}), which may shape the issues they pursue.")
    tc = [c for c in committees if TECH_COMMITTEE.search(c or "")]
    if tc:
        signals.append(f"Sits on {', '.join(tc[:3])}, which gives a standing reason to follow these issues.")
    if hist:
        if len(relevant) >= 5:
            top = ", ".join(f"{k[0].lower() + k[1:] if not k.startswith("Microsoft") else k} ({v})" for k, v in by_topic.most_common(3))
            signals.append(f"Sustained interest: {len(relevant)} of {len(hist)} written questions in the past year ({share}%) "
                           f"touch these topics, mainly {top}.")
        elif relevant:
            signals.append(f"Occasional interest: {len(relevant)} of {len(hist)} written questions in the past year touch these topics.")
        else:
            signals.append(f"New interest: none of their {len(hist)} written questions in the past year touched these topics before.")
    if len(todays) >= 3:
        signals.append(f"Tabled or received answers to {len(todays)} related questions in this period: a deliberate line of inquiry.")
    seat = hm.get("membershipFrom") or ""
    if house == "Commons" and seat:
        local = [q for q, _ in relevant + [(t, {}) for t in todays]
                 if seat.split(" and ")[0].lower() in (to_plain_text(q.get("questionText")) or "").lower()]
        if local:
            signals.append(f"Constituency angle: at least one question names {seat}.")
    if interests:
        signals.append("Has registered interests touching technology or data (see below); check before engaging.")
    if focus:
        signals.append(f"Self-declared policy focus includes: {', '.join(focus[:5])}.")

    return {
        "id": raw["id"], "name": name, "party": party, "house": house, "seat": seat,
        "since": (hm.get("membershipStartDate") or "")[:10], "thumbnail": core.get("thumbnailUrl"),
        "posts": posts[:4], "committees": committees[:8], "focus": focus[:8], "interests": interests,
        "history": {"total": len(hist), "relevant": len(relevant), "share": share,
                    "complete": raw.get("historyComplete", False),
                    "byTopic": dict(by_topic.most_common()), "topDepartments": dict(depts.most_common(4)),
                    "recent": [{"uin": q.get("uin"), "heading": q.get("heading") or to_plain_text(q.get("questionText"))[:90],
                                "date": (q.get("dateTabled") or "")[:10],
                                "url": f"{WQ_SITE}/{(q.get('dateTabled') or '')[:10]}/{q.get('uin')}"}
                               for q, _ in relevant[:6]]},
        "today": [t.get("uin") for t in todays],
        "signals": signals,
        "links": {"profile": f"{SITE}/{raw['id']}/contact",
                  "questions": f"{SITE}/{raw['id']}/writtenquestions",
                  "interests": f"{SITE}/{raw['id']}/registeredinterests",
                  "focus": f"{SITE}/{raw['id']}/focus",
                  "voting": f"{SITE}/{raw['id']}/voting"},
    }


def build_profiles(api: Api, feed: dict, run_date: date, cache_dir: Path) -> list[dict]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    by_member: dict[int, list[dict]] = {}
    for q in feed["writtenQuestions"]:
        mid = q.get("askingMemberId") or (q.get("askingMember") or {}).get("id")
        if mid:
            by_member.setdefault(mid, []).append(q)
    def one(item):
        mid, todays = item
        try:
            return profile(load_member(api, mid, run_date, cache_dir), todays)
        except Exception as e:  # one bad record must not sink the run
            log.exception("profile %s failed: %s", mid, e)
            return None

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(4) as pool:
        out = [p for p in pool.map(one, by_member.items()) if p]
    out.sort(key=lambda p: (-len(p["today"]), p["name"] or ""))
    return out
