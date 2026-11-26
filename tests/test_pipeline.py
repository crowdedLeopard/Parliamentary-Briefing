"""Offline end-to-end test with a fake Parliament API (no network)."""

import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))

from api import Api  # noqa: E402
from feed import build_feed, window  # noqa: E402
from members import build_profiles  # noqa: E402
from render import render  # noqa: E402

LONG = "x " * 200


def q(i, house, text, answered=True, member=7):
    return {"id": i, "uin": f"{'HL' if house == 'Lords' else ''}{40000 + i}", "house": house,
            "heading": f"Heading {i}" if answered else "", "askingMemberId": member,
            "askingMember": {"id": member, "name": f"Member {member}", "partyAbbreviation": "Lab", "partyColour": "d50000"},
            "answeringBodyName": "Department for Science, Innovation and Technology",
            "dateTabled": "2026-11-20T00:00:00", "questionText": text,
            "dateAnswered": "2026-11-23T00:00:00" if answered else None,
            "answerText": ("<p>We work with cloud providers. " + LONG + "</p>") if answered else None}


ANSWERED = {"Commons": [q(i, "Commons", "Question on potholes") for i in range(1, 1201)]
            + [q(5000, "Commons", "Question on data centres in Slough")],
            "Lords": [q(6000, "Lords", "Question on artificial intelligence", member=8)]}
TABLED = {"Commons": [q(7000, "Commons", "Question on AI in schools " + LONG, answered=False, member=8),
                      q(5000, "Commons", "Question on data centres in Slough", answered=False)],
          "Lords": []}
STATEMENTS = [{"id": 1, "uin": "HCWS1", "house": "Commons", "title": "Farming", "text": "Cows", "dateMade": "2026-11-23T00:00:00"}]


def handler(request: httpx.Request):
    u = urlparse(str(request.url))
    p = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert "includeTotalResults" not in p
    path = u.path
    if path.endswith("/writtenquestions/questions"):
        if "askingMemberId" in p:
            data = [{"value": x} for x in ANSWERED["Commons"][:30]] + [{"value": q(9, "Commons", "Cloud first policy")}]
        else:
            src = ANSWERED if "answeredWhenFrom" in p else TABLED
            data = [{"value": x} for x in src[p["house"]]]
        s, t = int(p["skip"]), int(p["take"])
        return httpx.Response(200, json={"results": data[s:s + t]})
    if "/writtenquestions/questions/" in path:
        qid = int(path.rsplit("/", 1)[1])
        for x in ANSWERED["Commons"] + ANSWERED["Lords"] + TABLED["Commons"]:
            if x["id"] == qid:
                full = dict(x)
                full["answerText"] = (full.get("answerText") or "") + " Microsoft Azure"
                return httpx.Response(200, json={"value": full})
    if path.endswith("/writtenstatements/statements"):
        return httpx.Response(200, json={"results": [{"value": s} for s in STATEMENTS]})
    if path.startswith("/api/Members/"):
        parts = path.split("/")
        mid, sub = int(parts[3]), (parts[4] if len(parts) > 4 else "")
        if sub == "":
            return httpx.Response(200, json={"value": {"id": mid, "nameDisplayAs": f"Member {mid}",
                "latestParty": {"name": "Labour"}, "latestHouseMembership": {"membershipFrom": "Slough", "house": 1,
                "membershipStartDate": "2017-06-08T00:00:00"}}})
        if sub == "Biography":
            return httpx.Response(200, json={"value": {"committeeMemberships": [
                {"name": "Science, Innovation and Technology Committee", "startDate": "2024-10-01", "endDate": None}],
                "oppositionPosts": [], "governmentPosts": [], "otherPosts": []}})
        if sub == "RegisteredInterests":
            return httpx.Response(200, json={"value": [{"name": "Employment", "interests": [{"interest": "Adviser to a cloud software start-up"}]}]})
        if sub == "Focus":
            return httpx.Response(200, json={"value": [{"category": "Policy", "focus": ["Technology", "Housing"]}]})
        if sub == "Synopsis":
            return httpx.Response(200, json={"value": "Labour MP"})
    return httpx.Response(404)


def test_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("COPILOT_BIN", str(tmp_path / "no-copilot"))
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    api = Api(backoff=(0, 0), transport=httpx.MockTransport(handler))
    run = date(2026, 11, 24)
    assert window(run) == ("2026-11-23", "2026-11-23")
    assert window(date(2026, 11, 23)) == ("2026-11-20", "2026-11-22")

    feed = build_feed(api, run)
    assert feed["questionsScanned"] == 1203            # 1201 + 1 Lords + 1 tabled-only; id 5000 de-duplicated
    uins = {x["uin"] for x in feed["writtenQuestions"]}
    # Every answered question gets 'Microsoft Azure' only in the full text, so all are screened in via the detail fetch
    assert "45000" in uins and "HL46000" in uins and "47000" in uins
    assert feed["writtenStatements"] == [] and feed["statementsScanned"] == 1
    assert feed["warnings"] == ["AI classifier not run (Copilot CLI not installed)"]
    # DSIT is a watched department, so every question to it is screened in even without keywords
    assert feed["layers"]["department"] == 1203 and feed["layers"]["semantic"] == 0

    profiles = build_profiles(api, feed, run, tmp_path / "members")
    assert {p["id"] for p in profiles} == {7, 8}
    p8 = next(p for p in profiles if p["id"] == 8)
    assert any("Science, Innovation and Technology" in s for s in p8["signals"])
    assert p8["interests"] and p8["history"]["total"] == 31
    assert (tmp_path / "members" / "8.json").exists()

    page = render(feed, profiles, {"headline": "Test <b>headline</b>", "member_notes": {"8": "Likely driven by committee role."},
                                   "today": [{"time": "10:15", "venue": "Lords", "title": "Compute inquiry", "why": "x", "link": "https://example.org"}]}, run)
    assert "Test &lt;b&gt;headline&lt;/b&gt;" in page and 'id="m-8"' in page and "Likely driven" in page
    assert page.startswith("<!DOCTYPE html>")
    (tmp_path / "page.html").write_text(page)


def test_sources_use_parliament_apis(monkeypatch):
    import sources

    def h(req):
        u = str(req.url)
        if "hansard-api" in u and "Spoken.json" in u:
            if "data+centres" in u or "data%20centres" in u:
                return httpx.Response(200, json={"Results": [{
                    "MemberName": "Calum Miller", "AttributedTo": "Calum Miller (Bicester and Woodstock) (LD)",
                    "ContributionExtId": "C1", "ContributionTextFull": "Two huge data centres are proposed in my constituency.",
                    "DebateSection": "Finance Bill", "DebateSectionExtId": "D1", "House": "Commons",
                    "SittingDate": "2026-11-23T00:00:00"}]})
            return httpx.Response(200, json={"Results": []})
        if "whatson-api" in u:
            return httpx.Response(200, json=[{"Id": 57223, "House": "Commons", "Type": "Main Chamber", "StartTime": "15:00",
                                              "Description": "Cyber Security and Resilience Bill: Lords amendments", "CancelledDate": None}])
        if "committees-api" in u and "Publications" in u:
            return httpx.Response(200, json={"items": [{"id": 55946, "description": "Letter on Government Cyber Resilience",
                                                        "committees": [{"name": "Public Accounts Committee"}]}]})
        if "committees-api" in u and "Events" in u:
            return httpx.Response(200, json={"items": [{"id": 28501, "name": "Children's TV", "committees": [{"name": "DCMS Committee"}]}]})
        return httpx.Response(404)

    real = httpx.Client
    monkeypatch.setattr(sources.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(h), **{k: v for k, v in kw.items() if k != "transport"}))
    b = sources.gather("2026-11-23", "2026-11-23", "2026-11-24")
    assert len(b["hansard"]) == 1 and b["hansard"][0]["link"] == "https://hansard.parliament.uk/Commons/2026-11-23/debates/D1/x#contribution-C1"
    assert b["today"][0]["link"] == "https://whatson.parliament.uk/event/cal57223"
    assert {c["type"] for c in b["committees"]} == {"committee_publication", "committee_event"}
    assert not b["gaps"]


def test_rule_checks_catch_errors():
    from checks import run_checks
    feed = {"writtenQuestions": [{"uin": "43125"}], "writtenStatements": []}
    profiles = [{"name": "Adam Dance", "party": "Liberal Democrat"}]
    ed = {"very_important": [{"title": "Outage", "who": "Adam Dance (Lab, Yeovil)", "date": "UIN 43125 and UIN 99999",
                              "link": "https://example.com/x"}]}
    issues = [i["issue"] for i in run_checks(ed, feed, profiles)["issues"]]
    assert any("not an official Parliament site" in i for i in issues)
    assert any("UIN 99999" in i for i in issues) and not any("43125" in i for i in issues)
    assert any("Adam Dance is listed as Lab" in i for i in issues)


def test_render_with_validation():
    from render import render
    feed = {"fromDate": "2026-11-23", "toDate": "2026-11-23", "generatedUtc": "x", "questionsScanned": 1,
            "statementsScanned": 0, "writtenQuestions": [], "writtenStatements": [], "warnings": []}
    page = render(feed, [], {"headline": "H"}, date(2026, 11, 24),
                  {"verdict": "pass_with_fixes", "checked": 40, "fixes": [{"where": "vi[0]", "was": "Lab", "now": "LD", "reason": "party"}],
                   "removed": [], "writer": "w", "validator": "v"})
    assert "Validated with corrections: 40 claims checked, 1 corrected" in page and "LD" in page
    assert "Not yet checked" in render(feed, [], {"headline": "H"}, date(2026, 11, 24))


FAKE_COPILOT = r"""#!/usr/bin/env python3
import json, os, pathlib, sys
a = sys.argv
model = a[a.index("--model") + 1]
log = pathlib.Path(os.environ["FAKE_LOG"])
log.write_text(log.read_text() + model + "\n" if log.exists() else model + "\n")
assert "--deny-tool=shell" in a and "--allow-tool=read" in a
task = pathlib.Path("TASK.md").read_text()
if model == "gone-model":
    sys.stderr.write("Error: Model gone-model is not available"); sys.exit(1)
parts = sorted(p.name for p in pathlib.Path(".").glob("evidence*.txt"))
assert all(p in task for p in parts)
if "draft.json" in task:
    out = {"verdict": "pass_with_fixes", "checked": 3, "fixes": [{"where": "very_important[0].who", "was": "A (Lab)",
           "now": "A (LD)", "reason": "party"}], "removed": [], "parts": len(parts),
           "editorial": {"headline": "Draft", "very_important": [{"title": "X", "who": "A (LD)", "link": "https://q"}]}}
else:
    out = {"headline": "Draft", "very_important": [{"title": "X", "who": "A (Lab)", "link": "https://q"}]}
pathlib.Path("output.json").write_text(json.dumps(out))
"""


def test_writer_then_validator(monkeypatch, tmp_path):
    import agents
    import llm
    bin_ = tmp_path / "copilot"
    bin_.write_text(FAKE_COPILOT)
    bin_.chmod(0o755)
    calls = tmp_path / "calls"
    monkeypatch.setenv("COPILOT_BIN", str(bin_))
    monkeypatch.setenv("FAKE_LOG", str(calls))
    monkeypatch.setenv("COPILOT_GITHUB_TOKEN", "test")
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.setenv("WRITER_MODEL", "claude-opus-5.5")
    # validator list starts with an unavailable model, then the writer's own model, which it must skip
    monkeypatch.setenv("VALIDATOR_MODEL", "gone-model, claude-opus-5.5, gpt-6.1-sol")
    monkeypatch.setattr(llm, "PART", 200)                                  # force the evidence into several parts
    feed = {"fromDate": "2026-11-23", "toDate": "2026-11-23", "questionsScanned": 1, "writtenQuestions": [], "writtenStatements": []}
    ed, v = agents.write_and_validate(feed, [], {"hansard": [], "today": [], "committees": [], "gaps": []}, "2026-11-24")
    assert calls.read_text().split() == ["claude-opus-5.5", "gone-model", "gpt-6.1-sol"]
    assert ed["very_important"][0]["who"] == "A (LD)" and ed["today_date"] == "2026-11-24"
    assert v["verdict"] == "pass_with_fixes" and "editorial" not in v and v["parts"] > 1
    assert v["writer"] == "claude-opus-5.5" and v["validator"] == "gpt-6.1-sol" and v["independent"] and v["provider"] == "copilot"

    monkeypatch.setenv("COPILOT_BIN", str(tmp_path / "missing"))
    assert agents.write_and_validate(feed, [], {}, "2026-11-24", draft={"headline": "H"}) == ({"headline": "H"}, None)


def _fake_get(sat: dict, published: dict, qs_up: bool = True):
    """sat/published: {(house, date): bool}. Returns a get() for sitting.py."""
    import sitting

    def get(url, params, timeout=60, tries=3):
        if url == sitting.WHATSON:
            d = params["queryParameters.startDate"]
            return [{"House": h, "Type": "Main Chamber", "CancelledDate": None} for h in sitting.HOUSES if sat.get((h, d))], ""
        if url == sitting.HANSARD_DAY:
            return (["Debate", "WMS"] if published.get((params["house"], params["date"])) else []), ""
        return ({"results": []}, "") if qs_up else (None, "HTTPError 500")
    return get


def test_sitting_and_readiness():
    import sitting
    get = _fake_get({("Commons", "2026-11-24"): True, ("Lords", "2026-11-24"): True},
                    {("Commons", "2026-11-24"): True})
    st = sitting.sitting_status("2026-11-24", "2026-11-24", get=get)
    ready, missing = sitting.readiness(st, True)
    assert not ready and missing == ["Lords Hansard for 2026-11-24 is not published yet"]
    assert sitting.describe(st) == "Tuesday 24 November: both Houses sat."
    weekend = sitting.sitting_status("2026-11-20", "2026-11-22", get=_fake_get({("Lords", "2026-11-20"): True},
                                                                                {("Lords", "2026-11-20"): True}))
    assert sitting.readiness(weekend, True)[0] and sitting.any_sat(weekend)
    assert sitting.describe(weekend).startswith("Friday 20 November: only the Lords sat; Saturday 21 November: neither House sat")


def test_gate_decisions(tmp_path):
    import gate
    import sitting
    from datetime import datetime
    L = gate.LONDON
    sat = {("Commons", "2026-11-24"): True}
    late = lambda f, t: sitting.sitting_status(f, t, get=_fake_get(sat, {}))
    done = lambda f, t: sitting.sitting_status(f, t, get=_fake_get(sat, {("Commons", "2026-11-24"): True}))
    none = lambda f, t: sitting.sitting_status(f, t, get=_fake_get({}, {}))
    up = lambda f, t: (True, "")
    at = lambda h, m: datetime(2026, 11, 25, h, m, tzinfo=L)
    d = lambda now, st, **k: gate.decide("schedule", now, root=tmp_path, status_fn=st, qs_fn=up, **k)
    assert not d(at(3, 37), done)["build"]                                    # too early
    r = d(at(4, 37), late)
    assert not r["build"] and r["reason"].startswith("waiting: Commons Hansard for 2026-11-24")
    assert d(at(4, 37), done)["build"]                                        # material ready
    assert d(at(5, 7), late)["build"]                                         # past the wait: build with gaps
    assert "did not sit" in d(at(4, 37), none)["reason"] and d(at(4, 37), none)["build"]
    assert gate.decide("workflow_dispatch", at(13, 0), root=tmp_path)["build"]
    (tmp_path / "data/status").mkdir(parents=True)
    (tmp_path / "data/status/2026-11-24.json").write_text('{"attempts": 3}')
    r = d(at(9, 7), done)
    assert not r["build"] and r["alert"]                                      # gave up; alert after 09:00
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports/2026-11-24.html").write_text("x")
    r = d(at(9, 7), done)
    assert not r["build"] and not r["alert"] and "already published" in r["reason"]
