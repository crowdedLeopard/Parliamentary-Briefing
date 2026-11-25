"""Which days each House sat, and whether the material for the edition is published yet.

Standard library only, so the workflow's gate job can run it without installing anything.
  What's On   whatson-api.parliament.uk  scheduled Main Chamber business per House and day
                                         (the plan: tells us whether a House was due to sit)
  Hansard     hansard-api.parliament.uk  overview/sectionsforday: which Hansard sections exist
                                         for a House and day (the record: tells us it is published)
  Questions   questions-statements-api   one tiny request, to confirm the service is answering
A House "sat" on a day if What's On lists Main Chamber business for it, or Hansard has a debate
record for it. Material is "ready" when every day a House sat has its Hansard debate record and
the written questions service answers.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date, timedelta

WHATSON = "https://whatson-api.parliament.uk/calendar/events/list.json"
HANSARD_DAY = "https://hansard-api.parliament.uk/overview/sectionsforday.json"
QS_PROBE = "https://questions-statements-api.parliament.uk/api/writtenquestions/questions"
UA = {"User-Agent": "parliamentary-briefing/1.0 (daily public-affairs digest)"}
HOUSES = ("Commons", "Lords")


def window(run_date: date) -> tuple[str, str]:
    """Yesterday, or Friday to Sunday when run on a Monday."""
    to_d = run_date - timedelta(days=1)
    from_d = run_date - timedelta(days=3) if run_date.weekday() == 0 else to_d
    return from_d.isoformat(), to_d.isoformat()


def days(from_date: str, to_date: str) -> list[str]:
    d, end, out = date.fromisoformat(from_date), date.fromisoformat(to_date), []
    while d <= end:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def _get_json(url: str, params: dict, timeout: float = 60, tries: int = 3):
    full = f"{url}?{urllib.parse.urlencode(params)}"
    last = ""
    for _ in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(full, headers=UA), timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8")), ""
        except Exception as e:  # network, HTTP or JSON error: retry, then report
            last = f"{type(e).__name__}: {e}"
    return None, last


def sitting_status(from_date: str, to_date: str, get=_get_json) -> dict:
    """{"days": [{"date", "Commons": {...}, "Lords": {...}}], "errors": [...]} for the review period.

    Per House: scheduled (What's On had Main Chamber business), hansard (Hansard sections published),
    sat (either says so), ready (did not sit, or the Hansard debate record is published)."""
    out, errors = [], []
    for d in days(from_date, to_date):
        events, err = get(WHATSON, {"queryParameters.startDate": d, "queryParameters.endDate": d})
        if events is None:
            errors.append(f"What's On for {d} could not be read ({err})")
        day = {"date": d}
        for h in HOUSES:
            scheduled = None if events is None else any(
                e.get("House") == h and e.get("Type") == "Main Chamber" and not e.get("CancelledDate") for e in events)
            sections, err = get(HANSARD_DAY, {"house": h, "date": d})
            if sections is None:
                errors.append(f"{h} Hansard index for {d} could not be read ({err})")
            published = "Debate" in (sections or [])
            sat = bool(scheduled) or published
            day[h] = {"scheduled": scheduled, "hansard": sections, "sat": sat,
                      "ready": (not sat or published) and sections is not None}
        out.append(day)
    return {"days": out, "errors": errors}


def questions_service_up(from_date: str, to_date: str, get=_get_json) -> tuple[bool, str]:
    data, err = get(QS_PROBE, {"answeredWhenFrom": from_date, "answeredWhenTo": to_date, "take": 1}, timeout=90)
    return data is not None, err


def readiness(status: dict, qs_ok: bool) -> tuple[bool, list[str]]:
    """(ready, what is still missing)."""
    missing = list(status["errors"])
    for day in status["days"]:
        for h in HOUSES:
            if day[h]["sat"] and not day[h]["ready"] and day[h]["hansard"] is not None:
                missing.append(f"{h} Hansard for {day['date']} is not published yet")
    if not qs_ok:
        missing.append("the written questions service is not answering")
    return not missing, missing


def describe(status: dict) -> str:
    """One plain sentence on who sat, for the report and the coverage note."""
    parts = []
    for day in status["days"]:
        d = date.fromisoformat(day["date"]).strftime("%A %-d %B")
        sat = [h for h in HOUSES if day[h]["sat"]]
        unknown = [h for h in HOUSES if day[h]["scheduled"] is None and day[h]["hansard"] is None]
        if unknown:
            parts.append(f"{d}: sitting could not be confirmed for the {' and '.join(unknown)}")
        elif len(sat) == 2:
            parts.append(f"{d}: both Houses sat")
        elif sat:
            parts.append(f"{d}: only the {sat[0]} sat")
        else:
            parts.append(f"{d}: neither House sat")
    return "; ".join(parts) + "." if parts else ""


def any_sat(status: dict) -> bool:
    return any(day[h]["sat"] for day in status["days"] for h in HOUSES)
