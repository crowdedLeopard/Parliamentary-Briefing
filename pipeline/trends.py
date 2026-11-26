"""Cross-day analysis of the saved feed files: what links questions across days.

Reads every data/feed/parliament-<date>.json (and editorial/<date>.json for
headlines) and returns one dict used by site.py for the archive, Themes and
Timeline pages. Offline, standard library only, deterministic.

Kinds of thread, each resting on evidence that can be checked:
  followup  a question that cites an earlier answer ("pursuant to the answer ...")
  series    one member, 3+ questions on the same heading (or same department, same day)
  wording   different members asking near-identical questions within 7 days
  subject   3+ different members on the same Parliament heading within 14 days
Rising topics compare the last 7 days with the 28 days before, by date tabled.

Timing always uses the date a question was tabled, not answered: answers come
days or weeks later, so the tabling date is what lines up with events.
Wording is descriptive only. The site is public, so nothing here labels
members' motives or calls a pattern coordinated.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from topics import TOPICS, to_plain_text

ROOT = Path(__file__).resolve().parent.parent
SUBSTANTIVE = [t.label for t in TOPICS]  # keyword topics; excludes department / watchlist catch-alls
SHORT = {
    "Microsoft and its businesses": "Microsoft",
    "Other technology and AI companies": "Tech companies",
    "Artificial intelligence": "AI",
    "Cloud, data centres and compute": "Cloud and data centres",
    "Online safety and social media": "Online safety",
    "Copyright and intellectual property": "Copyright",
    "Data protection and privacy": "Data protection",
    "Cyber security and resilience": "Cyber security",
    "Digital competition and markets": "Competition",
    "Government digital, IT and procurement": "Government IT",
    "Digital skills and education technology": "Digital skills",
}
CORE = {"Microsoft", "Tech companies", "AI", "Cloud and data centres", "Cyber security", "Competition", "Government IT", "Copyright"}
WQ = "https://questions-statements.parliament.uk/written-questions/detail"

PREFIX = re.compile(r"^to ask (?:the [^,]{3,120}?,|his majesty'?s government,?|the hon\.? member for [^,]+,(?: representing [^,]+,)*)\s*", re.I)
FOLLOWUP = re.compile(r"\b(?:pursuant to|further to|with reference to|in the light of)\b[^.?]{0,80}?\b(?:answer|response|written answer)", re.I)
CITED = re.compile(r"\b(?:question|answer|uin)\s*(?:number\s*)?((?:HL)?\d{3,6})\b", re.I)
WORD = re.compile(r"[a-z]{3,}")


def _d(s: str | None) -> str:
    return (s or "")[:10]


def _member(q: dict) -> tuple[str, str, str]:
    m = q.get("askingMember") or {}
    party = m.get("partyAbbreviation") or m.get("party") or ""
    return str(q.get("askingMemberId") or m.get("id") or ""), m.get("name") or "Unknown member", party


def _body(q: dict) -> str:
    return PREFIX.sub("", to_plain_text(q.get("questionText")).lower()).strip()


def link(q: dict) -> str:
    return f"{WQ}/{_d(q.get('dateTabled'))}/{q.get('uin')}"


def substantive(q: dict) -> list[str]:
    return [t for t in (q.get("topics") or {}) if t in SUBSTANTIVE]


def load(root: Path = ROOT) -> tuple[list[dict], dict[str, dict]]:
    """All matched questions (latest record per UIN, with the first edition it appeared in) and per-edition facts."""
    items: dict[str, dict] = {}
    editions: dict[str, dict] = {}
    for p in sorted((root / "data" / "feed").glob("parliament-20??-??-??.json")):
        ed = p.stem.removeprefix("parliament-")
        try:
            feed = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        wq = feed.get("writtenQuestions") or []
        topic_counts = Counter(t for q in wq for t in substantive(q))
        ms = any("Microsoft and its businesses" in (q.get("topics") or {}) for q in wq)
        edit, val = {}, {}
        for name, target in ((f"{ed}.json", "edit"), (f"{ed}.validation.json", "val")):
            f = root / "editorial" / name
            if f.exists():
                try:
                    (edit if target == "edit" else val).update(json.loads(f.read_text()))
                except ValueError:
                    pass
        editions[ed] = {"date": ed, "fromDate": feed.get("fromDate") or ed, "scanned": feed.get("questionsScanned") or 0,
                        "questions": len(wq), "statements": len(feed.get("writtenStatements") or []),
                        "topics": dict(topic_counts), "microsoft": ms,
                        "headline": edit.get("headline") or "", "verdict": val.get("verdict")}
        for q in wq:
            uin = str(q.get("uin") or "")
            if not uin:
                continue
            rec = dict(q)
            rec["_first"] = items[uin]["_first"] if uin in items else ed
            rec["_eds"] = sorted(set((items.get(uin) or {}).get("_eds", [])) | {ed})
            items[uin] = rec
    return list(items.values()), editions


def speeches(root: Path = ROOT) -> list[dict]:
    """Hansard contributions saved by sources.py, de-duplicated by link."""
    seen, out = set(), []
    for p in sorted((root / "data" / "sources").glob("20??-??-??.json")):
        try:
            rows = json.loads(p.read_text()).get("hansard") or []
        except (OSError, ValueError):
            continue
        for h in rows:
            if h.get("link") and h["link"] not in seen:
                seen.add(h["link"])
                out.append({k: h.get(k) for k in ("date", "house", "debate", "speaker", "text", "link")})
    return out


def _thread(kind: str, key: str, qs: list[dict], title: str, label: str = "") -> dict:
    qs = sorted(qs, key=lambda q: (_d(q.get("dateTabled")), str(q.get("uin"))))
    members = {}
    for q in qs:
        mid, name, party = _member(q)
        members[mid] = {"id": mid, "name": name, "party": party}
    topics = Counter(t for q in qs for t in substantive(q))
    eds = sorted({e for q in qs for e in q["_eds"]})
    return {"id": f"{kind}-{re.sub(r'[^a-z0-9]+', '-', key.lower()).strip('-')[:60]}", "kind": kind, "title": title,
            "label": label or title,
            "members": list(members.values()), "topics": [t for t, _ in topics.most_common(3)],
            "microsoft": any("Microsoft and its businesses" in (q.get("topics") or {}) for q in qs),
            "from": _d(qs[0].get("dateTabled")), "to": _d(qs[-1].get("dateTabled")), "editions": eds,
            "items": [{"uin": q.get("uin"), "date": _d(q.get("dateTabled")), "member": _member(q)[1],
                       "heading": q.get("heading") or "", "body": q.get("answeringBodyName") or "",
                       "text": to_plain_text(q.get("questionText"))[:220], "link": link(q), "first": q["_first"],
                       "topics": [SHORT.get(t, t) for t in substantive(q)]}
                      for q in qs]}


def _within(qs: list[dict], days: int) -> list[list[dict]]:
    """Split date-sorted questions into runs where each is within `days` of the previous one."""
    qs = sorted(qs, key=lambda q: _d(q.get("dateTabled")))
    runs, cur = [], []
    for q in qs:
        if cur and (date.fromisoformat(_d(q["dateTabled"])) - date.fromisoformat(_d(cur[-1]["dateTabled"]))).days > days:
            runs.append(cur)
            cur = []
        cur.append(q)
    if cur:
        runs.append(cur)
    return runs


def _within_first(qs: list[dict], days: int) -> list[list[dict]]:
    """Like _within, but on the edition each question first appeared in."""
    qs = sorted(qs, key=lambda q: (q["_first"], _d(q.get("dateTabled"))))
    runs, cur = [], []
    for q in qs:
        if cur and (date.fromisoformat(q["_first"]) - date.fromisoformat(cur[-1]["_first"])).days > days:
            runs.append(cur)
            cur = []
        cur.append(q)
    if cur:
        runs.append(cur)
    return runs


def threads(items: list[dict], since: str | None = None) -> list[dict]:
    qs = [q for q in items if _d(q.get("dateTabled")) and (not since or _d(q["dateTabled"]) >= since)]
    out: list[dict] = []
    used: set[tuple[str, str]] = set()

    # follow-up chains: one member's questions that cite earlier answers, to the same department
    by_uin = {str(q.get("uin")): q for q in items}
    fu = defaultdict(list)
    for q in qs:
        text = to_plain_text(q.get("questionText"))
        if FOLLOWUP.search(text):
            fu[(_member(q)[0], q.get("answeringBodyName") or "")].append(q)
    for (mid, body), group in fu.items():
        for run in _within(group, 21):
            cited = {c for q in run for c in CITED.findall(to_plain_text(q.get("questionText")))}
            earlier = [by_uin[c] for c in cited if c in by_uin and by_uin[c] not in run]
            if len(run) + len(earlier) < 2:
                continue
            name = _member(run[0])[1]
            t = _thread("followup", f"{mid}-{body}-{_d(run[0]['dateTabled'])}", earlier + run,
                        f"{name}: follow-up questions to the {body or 'government'}")
            t["cited"] = sorted(cited)
            out.append(t)
            used |= {("m", str(q.get("uin"))) for q in run}

    # series: one member, same heading (or same department and same day when no heading yet)
    ser = defaultdict(list)
    for q in qs:
        mid = _member(q)[0]
        key = q.get("heading") or f"{q.get('answeringBodyName')}|{_d(q.get('dateTabled'))}"
        ser[(mid, key)].append(q)
    for (mid, key), group in ser.items():
        for run in _within(group, 14):
            fresh = [q for q in run if ("m", str(q.get("uin"))) not in used]
            if len(run) < 3 or len(fresh) < 2:
                continue
            name = _member(run[0])[1]
            label = f"on {key}" if "|" not in key else f"to the {key.split('|')[0]} on one day"
            out.append(_thread("series", f"{mid}-{key}-{_d(run[0]['dateTabled'])}", run, f"{name}: {len(run)} questions {label}",
                                f"{name}: questions {label}"))

    # subject: 3+ different members on the same Parliament subject heading, reaching the briefing within 14 days
    # of each other (grouped by edition, since answers to questions tabled weeks apart arrive together)
    head = defaultdict(list)
    for q in qs:
        if q.get("heading"):
            head[q["heading"].split(":")[0].strip()].append(q)
    for h, group in head.items():
        for run in _within_first(group, 14):
            n = len({_member(q)[0] for q in run})
            if n >= 3:
                out.append(_thread("subject", f"{h}-{run[0]['_first']}", run, f"{h}: {n} members", h))

    # Microsoft named: any 2+ members within 21 days
    ms = [q for q in qs if "Microsoft and its businesses" in (q.get("topics") or {})]
    for run in _within_first(ms, 21):
        n = len({_member(q)[0] for q in run})
        if n >= 2:
            out.append(_thread("subject", f"microsoft-{run[0]['_first']}", run,
                               f"Microsoft named: {len(run)} questions from {n} members", "Microsoft named"))

    # similar wording: different members, near-identical text, within 7 days
    pool = sorted([q for q in qs if len(_body(q)) > 60], key=lambda q: _d(q["dateTabled"]))
    toks = [set(WORD.findall(_body(q))) for q in pool]
    parent = list(range(len(pool)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(pool):
        da = date.fromisoformat(_d(a["dateTabled"]))
        for j in range(i + 1, len(pool)):
            b = pool[j]
            if (date.fromisoformat(_d(b["dateTabled"])) - da).days > 7:
                break
            if _member(a)[0] == _member(b)[0]:
                continue
            ta, tb = toks[i], toks[j]
            if not ta or not tb or len(ta & tb) / len(ta | tb) < 0.45:
                continue
            if SequenceMatcher(None, _body(a), _body(b)).ratio() >= 0.6:
                parent[find(i)] = find(j)
    groups = defaultdict(list)
    for i in range(len(pool)):
        groups[find(i)].append(pool[i])
    for g in groups.values():
        names = sorted({_member(q)[1] for q in g})
        if len(names) >= 2:
            out.append(_thread("wording", f"{names[0]}-{_d(g[0]['dateTabled'])}", g,
                               f"Similar wording from {len(names)} members: {g[0].get('heading') or _body(g[0])[:60]}",
                               f"Similar wording: {g[0].get('heading') or _body(g[0])[:60]}"))

    out = [t for t in out if t["microsoft"] or 2 * sum(1 for i in t["items"] if i["topics"]) >= len(t["items"])]

    def score(t):
        core = sum(1 for i in t["items"] if set(i["topics"]) & CORE)
        spread = len(t["members"]) if t["kind"] in ("subject", "wording") else 1
        return (t["microsoft"], core * spread, len(t["items"]), t["to"])
    out.sort(key=score, reverse=True)
    seen = set()
    uniq = []
    for t in out:
        if t["id"] not in seen:
            seen.add(t["id"])
            uniq.append(t)
    return uniq


def tabled_by_day(items: list[dict], end: date, days: int = 28) -> list[dict]:
    start = end - timedelta(days=days - 1)
    counts = defaultdict(Counter)
    for q in items:
        d = _d(q.get("dateTabled"))
        if d and start.isoformat() <= d <= end.isoformat() and substantive(q):
            for t in substantive(q):
                counts[d][t] += 1
            counts[d]["_all"] += 1
    return [{"date": (start + timedelta(days=i)).isoformat(), "total": counts[(start + timedelta(days=i)).isoformat()]["_all"],
             "topics": {t: c for t, c in counts[(start + timedelta(days=i)).isoformat()].items() if t != "_all"}}
            for i in range(days)]


def rising(items: list[dict], end: date, history_days: int) -> list[dict]:
    if history_days < 21:
        return []
    recent, base = Counter(), Counter()
    for q in items:
        d = _d(q.get("dateTabled"))
        if not d:
            continue
        age = (end - date.fromisoformat(d)).days
        for t in substantive(q):
            if 0 <= age < 7:
                recent[t] += 1
            elif 7 <= age < 35:
                base[t] += 1
    out = []
    for t, n in recent.items():
        avg7 = base[t] / 4
        if n >= 5 and n >= 2 * max(avg7, 1):
            out.append({"topic": t, "last7": n, "avg7": round(avg7, 1)})
    return sorted(out, key=lambda r: -r["last7"])


def askers(items: list[dict], editions: list[str], top: int = 12) -> list[dict]:
    recent = set(editions[-7:])
    per = defaultdict(lambda: {"n": 0, "eds": set(), "topics": Counter()})
    for q in items:
        eds = set(q["_eds"]) & recent
        if not eds:
            continue
        mid, name, party = _member(q)
        p = per[(mid, name, party)]
        p["n"] += 1
        p["eds"] |= eds
        p["topics"].update(substantive(q))
    rows = [{"id": k[0], "name": k[1], "party": k[2], "items": v["n"], "editions": len(v["eds"]),
             "topics": [SHORT.get(t, t) for t, _ in v["topics"].most_common(2)]} for k, v in per.items()]
    return sorted(rows, key=lambda r: (-r["editions"], -r["items"], r["name"]))[:top]


def analyse(root: Path = ROOT) -> dict:
    items, eds = load(root)
    order = sorted(eds)
    if not order:
        return {"editions": [], "threads": [], "byEdition": {}, "tabled": [], "rising": [], "askers": [], "items": []}
    end = date.fromisoformat(order[-1])
    span = (end - date.fromisoformat(order[0])).days + 1
    th = threads(items, since=(end - timedelta(days=90)).isoformat())
    # which threads each edition continues: an item in that edition, and either seen in an earlier edition or 3+ items
    by_ed = {}
    for ed in order:
        rows = []
        for t in th:
            here = [i for i in t["items"] if i["first"] == ed]
            before = [i for i in t["items"] if i["first"] < ed]
            if here and (before or len(t["items"]) >= 3):
                state = "growing" if before and len(here) >= 2 else ("continuing" if before else "new")
                # label carries no counts: an older edition must not show items that arrived later
                rows.append({"id": t["id"], "title": t["label"], "kind": t["kind"], "state": state, "added": len(here),
                             "soFar": len(here) + len(before),
                             "microsoft": t["microsoft"], "uins": [i["uin"] for i in here]})
        by_ed[ed] = rows[:6]
    return {"editions": [eds[e] for e in order], "threads": th, "byEdition": by_ed,
            "tabled": tabled_by_day(items, end), "rising": rising(items, end, span), "historyDays": span,
            "askers": askers(items, order), "items": items}
