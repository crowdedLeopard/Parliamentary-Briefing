"""Gather the source bundle the writer and validator agents both work from.

Only public Parliament web pages and APIs. Each source is reduced to the
passages that touch the topics, with speaker, debate title and a link, so the
agents see evidence rather than whole sitting days. Anything that cannot be
read is recorded in 'gaps' for the coverage note.
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from html import unescape

import httpx
from bs4 import BeautifulSoup

from topics import match_topics, to_plain_text

log = logging.getLogger("sources")
HANSARD = "https://hansard.parliament.uk"
WHATSON = "https://whatson.parliament.uk"
COMMITTEES = "https://committees.parliament.uk"
UA = {"User-Agent": "parliamentary-briefing/1.0 (daily public-affairs digest)"}
SECTIONS = {"Commons": ["CommonsChamber", "WestminsterHall", "GeneralCommittees", "PublicBillCommittees"],
            "Lords": ["LordsChamber", "GrandCommittee"]}



def _get(c: httpx.Client, url: str, gaps: list[str], label: str) -> str | None:
    for _ in range(3):
        try:
            r = c.get(url)
            if r.status_code == 200 and "Just a moment" not in r.text[:2000]:
                return r.text
            if r.status_code == 404:
                return None
        except httpx.HTTPError:
            pass
    gaps.append(f"{label} could not be read ({url})")
    return None


def _days(from_date: str, to_date: str) -> list[str]:
    d, end, out = date.fromisoformat(from_date), date.fromisoformat(to_date), []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _debate_links(html: str, house: str, day: str) -> dict[str, str]:
    """Map debate titles to their Hansard URLs from a day's overview page."""
    out = {}
    for href, text in re.findall(rf'href="(/{house}/{day}/debates/[^"]+)"[^>]*>(.*?)</a>', html, re.S):
        t = to_plain_text(text)
        t = re.sub(r"\(item number.*$", "", t).strip()
        if t and t not in out:
            out[t] = HANSARD + href
    return out


def hansard(c: httpx.Client, from_date: str, to_date: str, gaps: list[str], limit: int = 120) -> list[dict]:
    """Relevant contributions: speaker, debate, text (trimmed), link."""
    found: list[dict] = []
    for day in _days(from_date, to_date):
        for house, sections in SECTIONS.items():
            overview = _get(c, f"{HANSARD}/{house}/{day}", gaps, f"Hansard {house} {day}")
            if overview is None:
                continue
            links = _debate_links(overview, house, day)
            if not links:
                continue  # did not sit
            for sec in sections:
                page = _get(c, f"{HANSARD}/html/{house}/{day}/{sec}", [], "")
                if not page:
                    continue
                soup = BeautifulSoup(page, "html.parser")
                # Walk the page in document order, tracking the current debate title.
                title = sec
                for el in soup.find_all(["h1", "h2", "h3", "div"]):
                    cls = el.get("class") or []
                    if el.name in ("h1", "h2", "h3") or "debate-title" in cls:
                        t = el.get_text(" ", strip=True)
                        if t and len(t) < 200:
                            title = t
                        continue
                    if "contribution" not in cls:
                        continue
                    text = re.sub(r"\s+", " ", el.get_text(" ", strip=True))
                    text = re.sub(r"Share this specific contribution.*?Copy link", " ", text)
                    if len(text) < 40:
                        continue
                    topics = match_topics(text)
                    if not topics:
                        continue
                    speaker = text.split(" to contribution")[0][:120] if " to contribution" in text else text[:80]
                    found.append({"type": "hansard", "house": house, "date": day, "section": sec, "debate": title,
                                  "speaker": speaker, "topics": list(topics), "text": text[:1800],
                                  "link": links.get(title) or f"{HANSARD}/{house}/{day}"})
    found.sort(key=lambda x: -len(x["topics"]))
    if len(found) > limit:
        gaps.append(f"Hansard: {len(found)} relevant passages found; the {limit} most relevant were passed to the agents.")
    return found[:limit]


def whats_on(c: httpx.Client, today: str, gaps: list[str]) -> list[dict]:
    out = []
    for tab in ("commons", "lords", "committees"):
        page = _get(c, f"{WHATSON}/{tab}/{today}/", gaps, f"What's On {tab} {today}")
        if not page:
            continue
        main = page.split("<main", 1)[-1]
        for href, label in re.findall(r'href="(/event/[^"]+)"[^>]*>\s*View more information about\s*(.*?)</a>', main, re.S):
            out.append({"type": "whatson", "tab": tab, "title": to_plain_text(unescape(label)).rstrip(") ").strip(),
                        "link": WHATSON + href})
        out.append({"type": "whatson_page", "tab": tab, "text": to_plain_text(main)[:9000],
                    "link": f"{WHATSON}/{tab}/{today}/"})
    return out


def committee_publications(c: httpx.Client, from_date: str, to_date: str, gaps: list[str]) -> list[dict]:
    f = date.fromisoformat(from_date).strftime("%d/%m/%Y")
    t = date.fromisoformat(to_date).strftime("%d/%m/%Y")
    page = _get(c, f"{COMMITTEES}/publications/?DateFrom={f}&DateTo={t}", gaps, "Committee publications")
    if not page:
        return []
    text = to_plain_text(page.split("<main", 1)[-1])
    links = [COMMITTEES + h for h in sorted(set(re.findall(r'href="(/publications/\d+/[^"]+)"', page)))][:60]
    return [{"type": "committee_publications", "text": text[:12000], "links": links,
             "link": f"{COMMITTEES}/publications/?DateFrom={f}&DateTo={t}"}]


def gather(from_date: str, to_date: str, today: str) -> dict:
    gaps: list[str] = []
    with httpx.Client(timeout=60, headers=UA, follow_redirects=True) as c:
        bundle = {
            "hansard": hansard(c, from_date, to_date, gaps),
            "today": whats_on(c, today, gaps),
            "committees": committee_publications(c, from_date, to_date, gaps),
        }
    bundle["gaps"] = gaps
    log.info("sources: %d Hansard passages, %d What's On items, gaps: %d",
             len(bundle["hansard"]), len(bundle["today"]), len(gaps))
    return bundle
