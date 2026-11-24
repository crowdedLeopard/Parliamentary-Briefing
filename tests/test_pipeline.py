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


def test_end_to_end(tmp_path):
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
    assert not feed["warnings"]

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


def test_sources_parse_hansard_and_whatson(monkeypatch):
    import sources
    overview = '<a href="/Commons/2026-11-23/debates/AAA/FinanceBill">Finance Bill (item number 6)</a>'
    section = ('<h2>Finance Bill</h2><div class="contribution">Calum Miller (Bicester and Woodstock) (LD) to contribution 117 '
               'Share this specific contribution x Copy link There are two huge data centres proposed in my constituency.</div>'
               '<div class="contribution">Someone (Somewhere) (Lab) to contribution 118 Share this specific contribution x Copy link Potholes again and again.</div>')
    whatson = ('<main><a href="/event/cal1">View more information about Consideration of Lords Amendments to the Cyber Security and '
               'Resilience (Network and Information Systems) Bill ) (7)</a></main>')

    def h(req):
        u = str(req.url)
        if u.endswith("/Commons/2026-11-23"):
            return httpx.Response(200, text=overview)
        if "/html/Commons/2026-11-23/CommonsChamber" in u:
            return httpx.Response(200, text=section)
        if "whatson" in u and "/commons/" in u:
            return httpx.Response(200, text=whatson)
        return httpx.Response(404)

    real = httpx.Client
    monkeypatch.setattr(sources.httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(h), **{k: v for k, v in kw.items() if k != "transport"}))
    b = sources.gather("2026-11-23", "2026-11-23", "2026-11-24")
    assert len(b["hansard"]) == 1
    hp = b["hansard"][0]
    assert hp["debate"] == "Finance Bill" and hp["link"].endswith("/FinanceBill") and "Calum Miller" in hp["speaker"]
    assert any(x.get("title", "").startswith("Consideration of Lords Amendments to the Cyber") for x in b["today"])


def test_render_with_validation():
    from render import render
    feed = {"fromDate": "2026-11-23", "toDate": "2026-11-23", "generatedUtc": "x", "questionsScanned": 1,
            "statementsScanned": 0, "writtenQuestions": [], "writtenStatements": [], "warnings": []}
    page = render(feed, [], {"headline": "H"}, date(2026, 11, 24),
                  {"verdict": "pass_with_fixes", "checked": 40, "fixes": [{"where": "vi[0]", "was": "Lab", "now": "LD", "reason": "party"}],
                   "removed": [], "writer": "w", "validator": "v"})
    assert "Validated with corrections: 40 claims checked, 1 corrected" in page and "LD" in page
    assert "Not yet checked" in render(feed, [], {"headline": "H"}, date(2026, 11, 24))


def test_writer_then_validator(monkeypatch):
    import agents
    calls = []

    def fake_post(self, url, headers=None, json=None):
        calls.append(json["model"])
        if len(calls) == 1:   # writer
            body = '{"headline": "Draft", "very_important": [{"title": "X", "who": "A (Lab)", "link": "https://q"}]}'
        else:                 # validator
            body = ('Here you go: {"verdict": "pass_with_fixes", "checked": 3, "fixes": [{"where": "very_important[0].who", '
                    '"was": "A (Lab)", "now": "A (LD)", "reason": "party"}], "removed": [], '
                    '"editorial": {"headline": "Draft", "very_important": [{"title": "X", "who": "A (LD)", "link": "https://q"}]}}')
        return httpx.Response(200, json={"content": [{"type": "text", "text": body}]}, request=httpx.Request("POST", url))

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(agents.httpx.Client, "post", fake_post)
    feed = {"fromDate": "2026-11-23", "toDate": "2026-11-23", "questionsScanned": 1, "writtenQuestions": [], "writtenStatements": []}
    ed, v = agents.write_and_validate(feed, [], {"hansard": [], "today": [], "committees": [], "gaps": []}, "2026-11-24")
    assert calls == ["claude-sonnet-5-5", "claude-opus-5-5"]          # two separate agents
    assert ed["very_important"][0]["who"] == "A (LD)" and ed["today_date"] == "2026-11-24"
    assert v["verdict"] == "pass_with_fixes" and "editorial" not in v

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert agents.write_and_validate(feed, [], {}, "2026-11-24", draft={"headline": "H"}) == ({"headline": "H"}, None)
