"""Gather the source bundle the writer and validator agents both work from.

Uses Parliament's official APIs only. The ordinary web pages (hansard.,
whatson., committees.parliament.uk) put automated traffic from cloud servers
behind a bot check, which this pipeline must not try to get round.
  Hansard     hansard-api.parliament.uk     spoken contributions, by search term and date
  What's On   whatson-api.parliament.uk     today's Chamber, Westminster Hall and committee events
  Committees  committees-api.parliament.uk  publications in the period; events today
Every Hansard hit is re-screened with the full topic rules in topics.py.
Anything that cannot be read is recorded in 'gaps' for the coverage note.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from topics import SEARCH_TERMS, match_topics, to_plain_text

log = logging.getLogger("sources")
HANSARD_API = "https://hansard-api.parliament.uk"
WHATSON_API = "https://whatson-api.parliament.uk"
COMMITTEES_API = "https://committees-api.parliament.uk/api"
HANSARD = "https://hansard.parliament.uk"
UA = {"User-Agent": "parliamentary-briefing/1.0 (daily public-affairs digest)"}


def _get(c: httpx.Client, url: str, params: dict | None, gaps: list[str] | None, label: str) -> Any:
    for _ in range(3):
        try:
            r = c.get(url, params=params)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 404):
                break
        except (httpx.HTTPError, ValueError):
            pass
    if gaps is not None:
        gaps.append(f"{label} could not be read")
    return None


def _hansard_link(x: dict) -> str:
    house = x.get("House") or "Commons"
    day = (x.get("SittingDate") or "")[:10]
    ext = x.get("DebateSectionExtId")
    if ext and day:
        anchor = f"#contribution-{x['ContributionExtId']}" if x.get("ContributionExtId") else ""
        return f"{HANSARD}/{house}/{day}/debates/{ext}/x{anchor}"
    return f"{HANSARD}/{house}/{day}" if day else HANSARD


def hansard(c: httpx.Client, from_date: str, to_date: str, gaps: list[str], limit: int = 160) -> list[dict]:
    seen: dict[str, dict] = {}
    failed = 0
    for term in SEARCH_TERMS:
        data = _get(c, f"{HANSARD_API}/search/contributions/Spoken.json",
                    {"queryParameters.searchTerm": term, "queryParameters.startDate": from_date,
                     "queryParameters.endDate": to_date, "queryParameters.take": 100}, None, "")
        if data is None:
            failed += 1
            continue
        for x in data.get("Results", []) or []:
            key = x.get("ContributionExtId") or str(x.get("ItemId"))
            if key in seen:
                continue
            text = to_plain_text(x.get("ContributionTextFull") or x.get("ContributionText"))
            topics = match_topics(text, x.get("DebateSection"))
            if not topics:
                continue
            seen[key] = {"type": "hansard", "house": x.get("House"), "date": (x.get("SittingDate") or "")[:10],
                         "debate": x.get("DebateSection"), "section": x.get("Section") or x.get("HansardSection"),
                         "speaker": x.get("AttributedTo") or x.get("MemberName"), "memberId": x.get("MemberId"),
                         "topics": list(topics), "text": text[:1800], "link": _hansard_link(x)}
    if failed:
        gaps.append(f"Hansard search: {failed} of {len(SEARCH_TERMS)} searches failed")
    found = sorted(seen.values(), key=lambda h: -len(h["topics"]))
    if len(found) > limit:
        gaps.append(f"Hansard: {len(found)} relevant contributions found; the {limit} most relevant were passed to the agents.")
    log.info("hansard: %d relevant contributions from %d searches", len(found), len(SEARCH_TERMS) - failed)
    return found[:limit]


def _event(e: dict) -> dict:
    committee = e.get("Committee") or {}
    return {k: v for k, v in {
        "type": "whatson", "id": e.get("Id"), "house": e.get("House"), "kind": e.get("Type"),
        "category": e.get("Category"), "time": e.get("StartTime"), "location": e.get("Location"),
        "description": to_plain_text(e.get("Description")), "notes": to_plain_text(e.get("Notes"))[:600],
        "committee": committee.get("Description"),
        "inquiries": [i.get("Description") for i in committee.get("Inquiries") or []],
        "members": [m.get("Name") for m in e.get("Members") or [] if m.get("Name")],
        "summary": to_plain_text((e.get("SummarisedDetails") or "").replace("\\n", " "))[:600],
        "link": f"https://whatson.parliament.uk/event/cal{e.get('Id')}" if e.get("Id") else None,
    }.items() if v}


def whats_on(c: httpx.Client, today: str, gaps: list[str]) -> list[dict]:
    data = _get(c, f"{WHATSON_API}/calendar/events/list.json",
                {"queryParameters.startDate": today, "queryParameters.endDate": today}, gaps, f"What's On {today}")
    events = [_event(e) for e in data or [] if not e.get("CancelledDate")]
    return sorted(events, key=lambda e: (e.get("time") or "99", e.get("house") or ""))


def committees(c: httpx.Client, from_date: str, to_date: str, today: str, gaps: list[str]) -> list[dict]:
    out: list[dict] = []
    pubs = _get(c, f"{COMMITTEES_API}/Publications",
                {"StartDate": from_date, "EndDate": to_date, "Take": 200}, gaps, "Committee publications")
    for p in (pubs or {}).get("items", []):
        files = [f.get("url") for d in p.get("documents") or [] for f in d.get("files") or [] if f.get("url")]
        out.append({k: v for k, v in {
            "type": "committee_publication", "id": p.get("id"), "title": p.get("description"),
            "kind": (p.get("type") or {}).get("name"), "date": (p.get("publicationStartDate") or "")[:10],
            "committees": [x.get("name") for x in p.get("committees") or []],
            "inquiries": [b.get("title") for b in p.get("businesses") or []],
            "link": files[0] if files else f"https://committees.parliament.uk/publications/{p.get('id')}/",
        }.items() if v})
    events = _get(c, f"{COMMITTEES_API}/Events",
                  {"StartDateFrom": today, "StartDateTo": today, "Take": 100}, gaps, "Committee events today")
    for e in (events or {}).get("items", []):
        acts = e.get("activities") or []
        out.append({k: v for k, v in {
            "type": "committee_event", "id": e.get("id"), "title": e.get("name"),
            "start": e.get("startDate"), "location": e.get("location"),
            "committees": [x.get("name") for x in e.get("committees") or []],
            "inquiries": [b.get("title") for b in e.get("committeeBusinesses") or []],
            "witnesses": [f"{w.get('name')} ({w.get('position') or w.get('organisation') or ''})".strip()
                          for a in acts for w in (a.get("attendees") or a.get("witnesses") or []) if w.get("name")][:12],
            "link": f"https://committees.parliament.uk/event/{e.get('id')}" if e.get("id") else None,
        }.items() if v})
    return out


def gather(from_date: str, to_date: str, today: str) -> dict:
    gaps: list[str] = []
    with httpx.Client(timeout=90, headers=UA, follow_redirects=True) as c:
        bundle = {"hansard": hansard(c, from_date, to_date, gaps),
                  "today": whats_on(c, today, gaps),
                  "committees": committees(c, from_date, to_date, today, gaps)}
    bundle["gaps"] = gaps
    log.info("sources: %d Hansard contributions, %d events today, %d committee items, %d gaps",
             len(bundle["hansard"]), len(bundle["today"]), len(bundle["committees"]), len(gaps))
    return bundle
