"""News and events for the Timeline page. Standard library only; may fail without harm.

Three sources, each optional:
  1. data/events.json - a hand-kept list of tech events (outages, regulator decisions,
     consultations, conferences). Each entry can carry "terms": groups of words. A question
     that contains a word from every group (and shares a topic) is a "direct" link; otherwise
     a question on the same topic within 21 days is only a "possible" one.
  2. GOV.UK Search API - announcements by DSIT, CMA, Ofcom, ICO, NCSC, HMT, the Cabinet
     Office and DESNZ, kept only if the title or summary matches a briefing topic.
  3. GDELT DOC 2.0 API - UK news coverage: daily article volume and recent headlines
     per topic group. Free, no key; asks for one request every 5 seconds.

Everything fetched is data, never instructions: only titles, outlets, dates and links
are kept. Any failure becomes a gap note; the site still builds. Budget: ~90 seconds.
"""

from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

from topics import match_topics, to_plain_text
from trends import SHORT, _d, _member, link, substantive

ROOT = Path(__file__).resolve().parent.parent
UA = "parliamentary-briefing/1.0 (daily public-affairs digest)"
GOVUK_ORGS = ["department-for-science-innovation-and-technology", "competition-and-markets-authority", "ofcom",
              "information-commissioners-office", "national-cyber-security-centre", "hm-treasury", "cabinet-office",
              "department-for-energy-security-and-net-zero"]
GDELT_GROUPS = {
    "Microsoft": '(microsoft OR azure OR "microsoft 365" OR copilot)',
    "Cloud and data centres": '("data centre" OR "data centres" OR "data center" OR hyperscaler OR "cloud outage" OR "sovereign cloud")',
    "AI": '("AI regulation" OR "AI safety" OR "AI bill" OR "AI Growth Zone" OR "frontier AI")',
    "Cyber security": '(cyberattack OR "cyber attack" OR ransomware OR NCSC OR "cyber security bill")',
    "Online safety": '("online safety act" OR ofcom OR "online scams")',
    "Competition": '("competition and markets authority" OR "strategic market status")',
}
LAG_DAYS = 21


def _get(url: str, timeout: float = 25) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - fixed https hosts above
        return json.loads(r.read().decode("utf-8", "replace") or "{}")


def _safe_url(u: str) -> str:
    return u if isinstance(u, str) and u.startswith("https://") else ""


def hand_events(root: Path = ROOT) -> tuple[list[dict], list[str]]:
    p = root / "data" / "events.json"
    if not p.exists():
        return [], []
    try:
        rows = json.loads(p.read_text())
    except ValueError as exc:
        return [], [f"data/events.json could not be read ({exc})."]
    out = []
    for r in rows:
        if not r.get("date") or not r.get("title"):
            continue
        out.append({"date": r["date"][:10], "endDate": (r.get("endDate") or r["date"])[:10], "title": r["title"],
                    "kind": r.get("kind") or "news", "source": _safe_url(r.get("source") or ""),
                    "outlet": r.get("outlet") or "", "topics": r.get("topics") or list(match_topics(r["title"])),
                    "terms": [[t.lower() for t in ([g] if isinstance(g, str) else g)] for g in r.get("terms") or []],
                    "origin": "events.json"})
    return out, []


def govuk(start: date, get=_get) -> list[dict]:
    q = [("order", "-public_timestamp"), ("count", "200"), ("filter_public_timestamp", f"from:{start.isoformat()}"),
         ("fields", "title"), ("fields", "link"), ("fields", "public_timestamp"), ("fields", "description"),
         ("fields", "organisations")] + [("filter_organisations", o) for o in GOVUK_ORGS]
    data = get("https://www.gov.uk/api/search.json?" + urllib.parse.urlencode(q))
    out = []
    for r in data.get("results") or []:
        title, desc = to_plain_text(r.get("title")), to_plain_text(r.get("description"))
        topics = [t for t in match_topics(title, desc)]
        if not topics or not r.get("link") or not r.get("public_timestamp"):
            continue
        orgs = [o.get("title") or "" for o in r.get("organisations") or [] if isinstance(o, dict)]
        out.append({"date": r["public_timestamp"][:10], "endDate": r["public_timestamp"][:10], "title": title,
                    "kind": "government", "source": "https://www.gov.uk" + r["link"] if r["link"].startswith("/") else _safe_url(r["link"]),
                    "outlet": ", ".join(orgs[:2]) or "GOV.UK", "topics": topics, "terms": [], "origin": "GOV.UK"})
    return out


def _gdelt_date(s: str) -> str:
    try:
        return datetime.strptime(s[:8], "%Y%m%d").date().isoformat()
    except (TypeError, ValueError):
        return ""


def gdelt(days: int, get=_get, pause: float = 5.5) -> tuple[dict, list[dict]]:
    """Daily UK article volume across all groups, and up to 8 recent headlines per group."""
    base = "https://api.gdeltproject.org/api/v2/doc/doc?"
    allq = " OR ".join(GDELT_GROUPS.values())
    vol = get(base + urllib.parse.urlencode({"query": f"({allq}) sourcecountry:UK", "mode": "timelinevolraw",
                                               "format": "json", "timespan": f"{days}d"}))
    volume: dict[str, int] = defaultdict(int)
    for series in vol.get("timeline") or []:
        for pt in series.get("data") or []:
            d = _gdelt_date(pt.get("date") or "")
            if d:
                volume[d] += int(pt.get("value") or 0)
    heads = []
    for group, terms in GDELT_GROUPS.items():
        time.sleep(pause)
        try:
            res = get(base + urllib.parse.urlencode({"query": f"{terms} sourcecountry:UK sourcelang:english", "mode": "artlist",
                                                       "format": "json", "maxrecords": "8", "sort": "datedesc",
                                                       "timespan": f"{days}d"}))
        except Exception:  # noqa: BLE001 - one group failing is not fatal
            continue
        for a in res.get("articles") or []:
            url, d = _safe_url(a.get("url") or ""), _gdelt_date(a.get("seendate") or "")
            if url and d:
                heads.append({"date": d, "title": to_plain_text(a.get("title"))[:200], "outlet": a.get("domain") or "",
                              "source": url, "group": group})
    return dict(volume), heads


def link_events(events: list[dict], items: list[dict], speeches: list[dict] | None = None) -> list[dict]:
    """Parliamentary items tabled 0-21 days after each event that share a topic. Direct if they use the event's terms."""
    speeches = speeches or []
    for ev in events:
        start = date.fromisoformat(ev["date"])
        ev_topics = {SHORT.get(t, t) for t in ev["topics"]}
        direct, possible = [], []
        for q in items:
            d = _d(q.get("dateTabled"))
            if not d:
                continue
            lag = (date.fromisoformat(d) - start).days
            if lag < 0:
                continue
            text = to_plain_text(q.get("questionText")).lower()
            shared = ev_topics & {SHORT.get(t, t) for t in substantive(q)}
            row = {"uin": q.get("uin"), "date": d, "lag": lag, "member": _member(q)[1], "party": _member(q)[2],
                   "link": link(q), "text": to_plain_text(q.get("questionText"))[:200]}
            # direct: uses one of the event's own terms and shares a topic, at any later date (events get cited for months)
            if ev["terms"] and shared and all(any(t in text for t in grp) for grp in ev["terms"]):
                direct.append(row)
            elif shared and lag <= LAG_DAYS:
                possible.append(row)
        for h in speeches:
            lag = (date.fromisoformat(h["date"]) - start).days if h.get("date") else -1
            text = (h.get("text") or "").lower()
            if lag >= 0 and ev["terms"] and all(any(t in text for t in grp) for grp in ev["terms"]):
                direct.append({"uin": None, "date": h["date"], "lag": lag, "member": h.get("speaker") or "",
                               "party": "", "link": _safe_url(h.get("link") or ""),
                               "text": f"Speech in {(h.get('debate') or '').strip()}: " + (h.get("text") or "")[:160]})
        ev["direct"] = sorted(direct, key=lambda r: (r["lag"], str(r["uin"])))
        ev["possible"] = len(possible)
    return events


def collect(items: list[dict], end: date, speeches: list[dict] | None = None, days: int = 28, root: Path = ROOT, budget: float = 90, get=_get) -> dict:
    t0 = time.monotonic()
    start = end - timedelta(days=days - 1)
    gaps: list[str] = []
    events, g = hand_events(root)
    gaps += g
    events = [e for e in events if e["endDate"] >= (start - timedelta(days=365)).isoformat()]
    try:
        events += govuk(start, get=get)
    except Exception as exc:  # noqa: BLE001
        gaps.append(f"GOV.UK announcements could not be read ({type(exc).__name__}).")
    volume, heads = {}, []
    if time.monotonic() - t0 < budget:
        try:
            volume, heads = gdelt(days, get=get, pause=0 if get is not _get else 5.5)
        except Exception as exc:  # noqa: BLE001
            gaps.append(f"GDELT news coverage could not be read ({type(exc).__name__}).")
    events.sort(key=lambda e: e["date"], reverse=True)
    return {"events": link_events(events, items, speeches), "volume": volume, "headlines": heads, "gaps": gaps,
            "from": start.isoformat(), "to": end.isoformat()}
