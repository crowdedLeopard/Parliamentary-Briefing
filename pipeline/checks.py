"""Deterministic checks on the editorial, run every time alongside the AI validator.

Catches the errors that matter most and are checkable by rule:
  * every link points to an official Parliament site
  * every written question or statement link and every UIN quoted exists in the data
  * every "Name (Party ...)" pairing matches the member's party in the profiles
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

PARTY = {"Labour": "Lab", "Labour (Co-op)": "Lab", "Conservative": "Con", "Liberal Democrat": "LD",
         "Reform UK": "Reform", "Independent": "Ind", "Crossbench": "CB", "Non-affiliated": "Non-affiliated",
         "Scottish National Party": "SNP", "Green Party": "Green", "Plaid Cymru": "PC",
         "Democratic Unionist Party": "DUP", "Your Party": "Your Party", "Bishops": "Bishops"}
ALIASES = {"Lab": "Lab", "Labour": "Lab", "Lab/Co-op": "Lab", "Con": "Con", "Conservative": "Con", "LD": "LD",
           "Lib Dem": "LD", "Liberal Democrat": "LD", "Reform UK": "Reform", "Reform": "Reform", "Ind": "Ind",
           "Independent": "Ind", "CB": "CB", "Crossbench": "CB", "Non-affiliated": "Non-affiliated",
           "SNP": "SNP", "Green": "Green", "PC": "PC", "DUP": "DUP", "Your Party": "Your Party"}
OK_HOSTS = ("parliament.uk",)
UIN_RE = re.compile(r"\b(HL\d{3,5}|HCWS\d{2,4}|HLWS\d{2,4}|\d{5,6})\b")
WHO_RE = re.compile(r"([A-Z][A-Za-z'’\-\. ]{2,60}?) \((Lab(?:/Co-op)?|Labour|Con|Conservative|LD|Lib Dem|Liberal Democrat|"
                    r"Reform UK|Reform|Ind|Independent|CB|Crossbench|Non-affiliated|SNP|Green|PC|DUP|Your Party)\b")


def _items(ed: dict):
    for sec in ("very_important", "today", "debates", "questions", "committees", "other"):
        for i, it in enumerate(ed.get(sec) or []):
            yield f"{sec}[{i}]", it


def run_checks(editorial: dict | None, feed: dict, profiles: list[dict]) -> dict:
    if not editorial:
        return {"checked": 0, "issues": []}
    uins = {str(q.get("uin")) for q in feed.get("writtenQuestions", [])} | {str(s.get("uin")) for s in feed.get("writtenStatements", [])}
    party = {}
    for p in profiles:
        if p.get("name"):
            party[p["name"].replace("Mr ", "").replace("Dr ", "").strip()] = PARTY.get(p.get("party") or "", p.get("party"))
    issues, checked = [], 0
    for where, it in _items(editorial):
        text = " ".join(str(it.get(k) or "") for k in ("title", "who", "where", "date", "body", "why", "lead"))
        link = it.get("link")
        if link:
            checked += 1
            host = urlparse(link).hostname or ""
            if not host.endswith(OK_HOSTS):
                issues.append({"where": where, "issue": f"link is not an official Parliament site: {link}"})
            m = re.search(r"/written-(questions|statements)/detail/\d{4}-\d{2}-\d{2}/([A-Z]*\d+)", link)
            if m and m.group(2) not in uins:
                issues.append({"where": where, "issue": f"linked {m.group(1)[:-1]} {m.group(2)} is not in the period's data"})
        for u in sorted(set(UIN_RE.findall(" ".join(str(it.get(k) or "") for k in ("date", "who", "title"))))):
            checked += 1
            if u not in uins:
                issues.append({"where": where, "issue": f"UIN {u} is not in the period's data"})
        for seen, pty in WHO_RE.findall(text):
            seen = seen.replace("Mr ", "").replace("Dr ", "").strip()
            names = [n for n in party if seen == n or seen.endswith(" " + n)]
            for name in names[:1]:
                checked += 1
                want, got = party[name], ALIASES.get(pty, pty)
                if want and got and want != got and not (want == "Lab" and got == "Lab"):
                    issues.append({"where": where, "issue": f"{name} is listed as {pty}; the Members API says {want}"})
    return {"checked": checked, "issues": issues}
