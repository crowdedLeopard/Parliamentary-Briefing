"""Render the daily briefing as one self-contained HTML page.

Data sections (written questions, statements, member profiles, coverage) come
from the pipeline. Editorial sections (headlines, Parliament Today, debates,
committees) come from editorial/<toDate>.json when someone - a person or the
Cowork skill - has written one; otherwise they are left out.
"""

from __future__ import annotations

import html
from collections import Counter
from datetime import date

from topics import TOPICS, to_plain_text

WQ = "https://questions-statements.parliament.uk/written-questions/detail"
WS = "https://questions-statements.parliament.uk/written-statements/detail"
ORDER = [t.label for t in TOPICS]


def e(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def nice(d: str) -> str:
    try:
        return date.fromisoformat(d[:10]).strftime("%A %-d %B %Y")
    except Exception:
        return d or ""


def short(d: str) -> str:
    try:
        return date.fromisoformat(d[:10]).strftime("%-d %b")
    except Exception:
        return d or ""


def first_topic(item) -> str:
    keys = list((item.get("topics") or {}).keys())
    return min(keys, key=lambda k: ORDER.index(k) if k in ORDER else 99) if keys else "Other"


def status(q) -> str:
    if q.get("isWithdrawn"):
        return "Withdrawn"
    if q.get("answerIsHolding"):
        return "Holding answer"
    if q.get("dateAnswered") or q.get("answerText"):
        return f"Answered {short(q.get('dateAnswered') or '')}"
    return f"Tabled {short(q.get('dateTabled') or '')}"


def q_url(q) -> str:
    return f"{WQ}/{(q.get('dateTabled') or '')[:10]}/{q.get('uin')}"


def item_html(it: dict) -> str:
    meta = " · ".join(e(x) for x in (it.get("who"), it.get("where"), it.get("date")) if x)
    link = f'<a class="src" href="{e(it["link"])}">{e(it.get("linkText") or "Source")}</a>' if it.get("link") else ""
    why = f'<p class="why"><b>Why it matters.</b> {e(it["why"])}</p>' if it.get("why") else ""
    tags = "".join(f'<span class="tag">{e(t)}</span>' for t in it.get("tags", []))
    return (f'<article class="item"><h3>{e(it.get("title"))}</h3>'
            f'{f"<p class=meta>{meta}</p>" if meta else ""}<p>{e(it.get("body"))}</p>{why}'
            f'<p class="foot">{tags}{link}</p></article>')


def today_html(it: dict) -> str:
    link = f'<a href="{e(it["link"])}">{e(it.get("title"))}</a>' if it.get("link") else e(it.get("title"))
    return (f'<li><span class="t">{e(it.get("time") or "")}</span><div><p class="venue">{e(it.get("venue"))}'
            f'{" · " + e(it["lead"]) if it.get("lead") else ""}</p><p class="tt">{link}</p>'
            f'<p>{e(it.get("why"))}</p></div></li>')


def chart(feed: dict) -> str:
    rows = Counter()
    for q in feed["writtenQuestions"]:
        rows[(first_topic(q), q.get("house") or "Commons")] += 1
    for s in feed["writtenStatements"]:
        rows[(first_topic(s), s.get("house") or "Commons")] += 1
    labels = [l for l in ORDER + ["Other keywords"] if rows[(l, "Commons")] + rows[(l, "Lords")]]
    peak = max([rows[(l, "Commons")] + rows[(l, "Lords")] for l in labels] or [1])
    out = []
    for l in sorted(labels, key=lambda l: -(rows[(l, "Commons")] + rows[(l, "Lords")])):
        c, lo = rows[(l, "Commons")], rows[(l, "Lords")]
        out.append(f'<div class="bar"><span class="bl">{e(l)}</span><span class="bt">'
                   f'<i class="c" style="width:{100*c/peak:.1f}%"></i><i class="l" style="width:{100*lo/peak:.1f}%"></i></span>'
                   f'<span class="bn">{c + lo}</span></div>')
    return "".join(out)


def question_rows(feed: dict, pid: set[int]) -> str:
    groups: dict[str, list] = {}
    for q in feed["writtenQuestions"]:
        groups.setdefault(first_topic(q), []).append(q)
    out = []
    for label in [l for l in ORDER + ["Other keywords", "Other"] if l in groups]:
        rows = []
        for q in sorted(groups[label], key=lambda q: (not q.get("answerText"), q.get("uin") or "")):
            m = q.get("askingMember") or {}
            mid = q.get("askingMemberId") or m.get("id")
            who = f'<a href="#m-{mid}">{e(m.get("name"))}</a>' if mid in pid else e(m.get("name"))
            qt = to_plain_text(q.get("questionText"))
            at = to_plain_text(q.get("answerText"))
            rows.append(
                f'<tr><td><a href="{e(q_url(q))}">{e(q.get("uin"))}</a></td>'
                f'<td><b>{e(q.get("heading") or "Newly tabled")}</b><details><summary>Question and answer</summary>'
                f'<p>{e(qt)}</p>{f"<p class=ans>{e(at[:1600])}</p>" if at else ""}</details></td>'
                f'<td>{who}<br><small>{e(m.get("partyAbbreviation") or m.get("party") or "")}</small></td>'
                f'<td>{e(q.get("answeringBodyName"))}</td><td class="nw">{e(status(q))}</td></tr>')
        out.append(f'<h3 class="grp">{e(label)} <small>{len(rows)}</small></h3><div class="scroll">'
                   f'<table class="stack"><thead><tr><th>UIN</th><th>Question</th><th>Asked by</th><th>To</th><th>Status</th></tr></thead>'
                   f'<tbody>{"".join(rows)}</tbody></table></div>')
    return "".join(out) or "<p>No matching written questions in this period.</p>"


def profile_card(p: dict, colour: str, notes: dict) -> str:
    h = p["history"]
    tb = "".join(f'<div class="mini"><span>{e(k)}</span><i style="width:{min(100, 100*v/max(h["byTopic"].values())):.0f}%"></i><b>{v}</b></div>'
                 for k, v in list(h["byTopic"].items())[:4])
    recent = "".join(f'<li><a href="{e(r["url"])}">{e(r["heading"])}</a> <small>{e(short(r["date"]))}</small></li>' for r in h["recent"])
    read = notes.get(str(p["id"])) or p.get("read")
    lst = lambda xs: "".join(f"<li>{e(x)}</li>" for x in xs)
    today = ", ".join(e(u) for u in p["today"])
    links = " ".join(f'<a href="{e(u)}">{e(k.title())}</a>' for k, u in p["links"].items())
    return f'''<article class="card" id="m-{p["id"]}" data-q="{e((p["name"] or "") + " " + (p["party"] or "") + " " + (p["seat"] or "") + " " + " ".join(h["byTopic"]))}">
<header><span class="dot" style="background:#{e(colour or "888")}"></span><div><h3>{e(p["name"])}</h3>
<p class="meta">{e(p["party"])} · {e(p["seat"])} · {e(p["house"])}{" since " + e(short(p["since"]) + " " + p["since"][:4]) if p["since"] else ""}</p></div></header>
<p class="this">This period: {today}</p>
{f'<p class="read"><b>Likely drivers.</b> {e(read)}</p>' if read else ""}
<ul class="sig">{lst(p["signals"])}</ul>
<div class="stats"><p><b>{h["relevant"]}</b> of {h["total"]} written questions in the past year on these topics{" (history incomplete)" if not h["complete"] else ""}</p>{tb}</div>
{f'<p class="lab">Committees</p><ul class="pl">{lst(p["committees"])}</ul>' if p["committees"] else ""}
{f'<p class="lab">Posts</p><ul class="pl">{lst(p["posts"])}</ul>' if p["posts"] else ""}
{f'<p class="lab">Relevant registered interests</p><ul class="pl">{lst(p["interests"])}</ul>' if p["interests"] else ""}
{f'<p class="lab">Self-declared focus</p><p class="small">{e(", ".join(p["focus"]))}</p>' if p["focus"] else ""}
{f'<details><summary>Recent relevant questions</summary><ul class="pl">{recent}</ul></details>' if recent else ""}
<p class="links">{links}</p></article>'''


def validation_html(v: dict | None, ed: dict) -> tuple[str, str]:
    """(header badge, coverage block) describing the independent validation pass."""
    if not ed:
        return "", ""
    rules = (v or {}).get("ruleChecks") or {"checked": 0, "issues": []}
    rule_html = (f"<p><b>Rule checks.</b> {rules['checked']} links, UINs and member parties checked against the official data: "
                 + ("all correct.</p>" if not rules["issues"] else
                    f"{len(rules['issues'])} problem(s):</p><ul>" + "".join(f"<li>{e(i['where'])}: {e(i['issue'])}</li>" for i in rules["issues"]) + "</ul>"))
    if not v or v.get("verdict") in (None, "not run"):
        why = e((v or {}).get("error") or "the validator agent has not run")
        return ('<p class="vb warn">Not yet checked by the validator agent</p>',
                f"<p><b>Validation.</b> The editorial has NOT been through the independent validator agent ({why}).</p>" + rule_html)
    fixes, removed = v.get("fixes", []), v.get("removed", [])
    verdict = {"pass": "Validated", "pass_with_fixes": "Validated with corrections", "fail": "Failed validation"}.get(v.get("verdict"), "Validation not completed")
    cls = "warn" if v.get("verdict") in ("fail", None, "not run") else ""
    badge = f'<p class="vb {cls}">{e(verdict)}: {e(v.get("checked", 0))} claims checked, {len(fixes)} corrected, {len(removed)} removed</p>'
    rows = "".join(f"<li><b>{e(f.get('where'))}</b>: {e(f.get('was'))} &rarr; {e(f.get('now'))} <small>({e(f.get('reason'))})</small></li>" for f in fixes)
    rows += "".join(f"<li><b>{e(r.get('where'))}</b> removed <small>({e(r.get('reason'))})</small></li>" for r in removed)
    block = (f"<p><b>Validation.</b> Drafted by the writer agent ({e(v.get('writer', 'n/a'))}) and checked claim by claim against the "
             f"same source material by an independent validator agent ({e(v.get('validator', 'n/a'))}). Verdict: {e(verdict)}.</p>"
             + (f"<details><summary>Corrections and removals</summary><ul>{rows}</ul></details>" if rows else "") + rule_html)
    if rules["issues"]:
        badge = badge.replace('class="vb', 'class="vb warn').replace("</p>", f" · {len(rules['issues'])} rule-check problem(s)</p>")
    return badge, block


def render(feed: dict, profiles: list[dict], editorial: dict | None, run_date: date, validation: dict | None = None) -> str:
    ed = editorial or {}
    vbadge, vblock = validation_html(validation, ed)
    pid = {p["id"] for p in profiles}
    colours = {}
    for q in feed["writtenQuestions"]:
        m = q.get("askingMember") or {}
        colours[q.get("askingMemberId") or m.get("id")] = m.get("partyColour")
    notes = ed.get("member_notes", {})
    period = nice(feed["fromDate"]) if feed["fromDate"] == feed["toDate"] else f'{nice(feed["fromDate"])} to {nice(feed["toDate"])}'
    nq, ns = len(feed["writtenQuestions"]), len(feed["writtenStatements"])
    headline = ed.get("headline") or f"{nq} written questions on Microsoft's issues from {len(profiles)} members"
    summary = ed.get("summary") or "Written questions and statements screened for Microsoft's policy issues, with a profile of every member who asked."

    def section(key, title, body):
        return f'<section class="band" id="{key}"><div class="wrap"><h2>{e(title)}</h2>{body}</div></section>' if body else ""

    vi = "".join(item_html(i) for i in ed.get("very_important", []))
    today = f'<ol class="today">{"".join(today_html(i) for i in ed.get("today", []))}</ol>' if ed.get("today") else ""
    debates = "".join(item_html(i) for i in ed.get("debates", []))
    qed = "".join(item_html(i) for i in ed.get("questions", []))
    committees = "".join(item_html(i) for i in ed.get("committees", []))
    other = "".join(item_html(i) for i in ed.get("other", []))
    stm = "".join(f'<li><a href="{WS}/{e((s.get("dateMade") or "")[:10])}/{e(s.get("uin"))}">{e(s.get("title"))}</a> '
                  f'<small>{e(s.get("uin"))} · {e(s.get("house"))}</small></li>' for s in feed["writtenStatements"])
    warn = "".join(f"<li>{e(w)}</li>" for w in feed.get("warnings", []))
    cov_extra = "".join(f"<p>{e(x)}</p>" for x in ed.get("coverage", []))
    nav = [("vi", "Immediate attention", vi), ("today", "Parliament Today", today), ("debates", "Debates", debates),
           ("questions", "Questions", "1"), ("committees", "Committees", committees), ("other", "Other sources", "1"),
           ("members", "Who asked", "1"), ("coverage", "Coverage", "1")]
    navhtml = "".join(f'<a href="#{k}">{e(t)}</a>' for k, t, b in nav if b)

    return f"""<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,nofollow,noarchive">
<title>Parliamentary briefing {e(feed["toDate"])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap" rel="stylesheet">
<style>
/* VOICE work: a daily brief edited like a newspaper graphics desk, calm and exact
   IDEA the Commons Order Paper and Hansard daily part: ruled columns, the two Houses' own colours
   PICTURE where the day's relevant business fell, by topic, Commons green and Lords red bars
   COLOUR white ground, ink, Commons green #0b6b4b leading, Lords red #a2192f, green tint fields; night #0b1411
   TYPE Source Serif 4 for headings, Source Sans 3 for text
   LAYOUT green title band with the finding and figures; chart beside on laptop, beneath on phone; ruled sections */
:root{{color-scheme:light dark;--bg:light-dark(#ffffff,#0b1411);--ink:light-dark(#121417,#e8efeb);--mut:light-dark(#4d5752,#a9b8b0);--rule:light-dark(#d5ddd8,#24332c);--g:light-dark(#0b6b4b,#3fb487);--gd:light-dark(#0b6b4b,#0f3d2d);--r:light-dark(#a2192f,#e0566c);--tint:light-dark(#eaf4ef,#12231c);--card:light-dark(#fff,#0f1b16)}}
:root[data-theme=light]{{color-scheme:light}}:root[data-theme=dark]{{color-scheme:dark}}
*{{box-sizing:border-box;min-width:0}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 "Source Sans 3",system-ui,sans-serif;overflow-x:clip}}
a{{color:var(--g);text-underline-offset:2px}}
h1,h2,h3{{font-family:"Source Serif 4",Georgia,serif;line-height:1.1;letter-spacing:-.01em;text-wrap:balance;margin:0}}
.wrap{{max-width:1240px;margin:0 auto}}
.band{{padding:clamp(28px,4vw,56px) max(5vw,16px);border-top:1px solid var(--rule)}}
.top{{background:var(--gd);color:#fff;padding:clamp(28px,4vw,52px) max(5vw,16px)}}
.top a{{color:#fff}}
.grid{{display:grid;grid-template-columns:minmax(0,1.05fr) minmax(0,1fr);gap:clamp(24px,4vw,56px);align-items:start}}
.kick{{font-size:15px;opacity:.85;margin:0 0 10px}}
h1{{font-size:clamp(32px,4.2vw,48px);margin-bottom:14px}}
.dek{{font-size:18px;max-width:62ch;opacity:.95;margin:0 0 22px}}
.figs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(8.5em,1fr));gap:2px;background:rgba(255,255,255,.22);border:1px solid rgba(255,255,255,.22)}}
.figs div{{background:var(--gd);padding:12px 14px}}.figs b{{display:block;font:700 clamp(26px,3vw,34px)/1 "Source Serif 4",serif}}.figs span{{font-size:14px;opacity:.85}}
.pic{{background:var(--bg);color:var(--ink);padding:20px 22px;border-radius:4px}}
.pic h2{{font-size:20px;margin-bottom:4px}}.pic .key{{font-size:14px;color:var(--mut);margin:0 0 14px}}
.key i{{display:inline-block;width:11px;height:11px;margin:0 5px -1px 10px;border-radius:2px}}
.bar{{display:grid;grid-template-columns:minmax(0,12.5em) minmax(0,1fr) 2.2em;gap:10px;align-items:center;padding:5px 0;border-bottom:1px solid var(--rule);font-size:15px}}
.bt{{display:flex;height:16px}}.bt i{{display:block;height:100%}}.bt .c{{background:var(--g)}}.bt .l{{background:var(--r)}}
.bn{{text-align:right;font-variant-numeric:tabular-nums;font-weight:700}}
nav.scroll{{display:flex;gap:4px;overflow-x:auto;padding:10px max(5vw,16px);background:var(--bg);border-bottom:1px solid var(--rule)}}
nav.scroll a{{flex:none;padding:8px 12px;border-radius:3px;text-decoration:none;font-weight:600;font-size:15px}}
nav.scroll a:hover,nav.scroll a:focus-visible{{background:var(--tint)}}
@media(min-width:900px){{nav.scroll{{position:sticky;top:0;z-index:5}}}}
html{{scroll-padding-top:64px}}
h2{{font-size:clamp(26px,3vw,34px);margin-bottom:18px}}
.item{{display:grid;grid-template-columns:minmax(0,1fr);padding:16px 0;border-top:1px solid var(--rule);max-width:82ch}}
.item h3{{font-size:21px;margin-bottom:4px}}.item p{{margin:4px 0}}.meta{{color:var(--mut);font-size:15px}}
.why{{background:var(--tint);padding:8px 12px;border-left:3px solid var(--g)}}
.foot{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}}.src{{font-weight:600}}
.tag{{font-size:13px;padding:2px 8px;border:1px solid var(--rule);border-radius:99px;color:var(--mut)}}
#vi .item h3::before{{content:"";display:inline-block;width:10px;height:10px;background:var(--r);margin-right:8px;border-radius:2px}}
.today{{list-style:none;margin:0;padding:0;max-width:90ch}}
.today li{{display:grid;grid-template-columns:5.5em minmax(0,1fr);gap:16px;padding:12px 0;border-top:1px solid var(--rule)}}
.today .t{{font:700 22px/1.1 "Source Serif 4",serif;color:var(--g);white-space:nowrap}}.today p{{margin:2px 0}}
.today .venue{{font-size:14px;color:var(--mut)}}.today .tt{{font-weight:700}}
.grp{{font-size:19px;margin:26px 0 8px}}.grp small{{color:var(--mut);font-family:"Source Sans 3",sans-serif;font-size:15px}}
.scroll{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;font-size:15px}}th{{text-align:left;font-weight:600;color:var(--mut);border-bottom:2px solid var(--ink);padding:6px 8px}}
td{{border-bottom:1px solid var(--rule);padding:8px;vertical-align:top}}td:first-child{{white-space:nowrap}}.nw{{white-space:nowrap}}
details summary{{cursor:pointer;color:var(--g);font-size:14px;margin-top:4px}}details p{{margin:6px 0;font-size:15px}}.ans{{border-left:3px solid var(--g);padding-left:10px}}
.filter{{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:18px}}
.filter input{{font:16px "Source Sans 3",sans-serif;padding:10px 12px;min-width:min(100%,22em);border:1px solid var(--rule);border-radius:3px;background:var(--card);color:var(--ink)}}
.filter input:focus-visible{{outline:2px solid var(--g)}}
.cards{{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,360px),1fr));gap:16px}}
.card{{background:var(--card);border:1px solid var(--rule);border-top:4px solid var(--g);padding:16px;border-radius:3px}}
.card header{{display:flex;gap:10px;align-items:flex-start}}.dot{{width:12px;height:12px;border-radius:50%;margin-top:7px;flex:none}}
.card h3{{font-size:20px}}.card .meta{{margin:2px 0 0}}.this{{font-size:14px;color:var(--mut);margin:10px 0}}
.read{{background:var(--tint);padding:8px 10px;margin:8px 0}}
.sig{{margin:8px 0;padding-left:18px}}.sig li{{margin:3px 0}}
.stats p{{margin:8px 0 4px;font-size:15px}}.mini{{display:grid;grid-template-columns:minmax(0,11em) minmax(0,1fr) 2em;gap:8px;align-items:center;font-size:13px}}
.mini i{{height:8px;background:var(--g);display:block}}.mini b{{text-align:right}}
.lab{{font-weight:700;font-size:14px;margin:10px 0 2px}}.pl{{margin:0;padding-left:18px;font-size:15px}}.small{{font-size:15px;margin:0}}
.links{{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:14px;margin:12px 0 0;padding-top:10px;border-top:1px solid var(--rule)}}
.vb{{display:inline-block;margin:0 0 18px;padding:6px 12px;background:#fff;color:#0b6b4b;font-weight:700;border-radius:3px;font-size:15px}}.vb.warn{{color:#a2192f}}
.printonly{{display:none}}
.cov{{max-width:82ch}}.cov li{{margin:4px 0}}
@media(max-width:860px){{.grid{{grid-template-columns:minmax(0,1fr)}}}}
@media(max-width:600px){{table{{font-size:13px}}.stack thead{{display:none}}.stack tr{{display:grid;padding-block:10px;border-bottom:1px solid var(--rule)}}.stack td{{border:0;padding:3px 0}}.bar{{grid-template-columns:minmax(0,9em) minmax(0,1fr) 2em;font-size:14px}}.today li{{grid-template-columns:minmax(0,1fr);gap:2px}}}}
</style></head><body>
<header class="top"><div class="wrap grid">
<div><p class="kick">Parliamentary briefing · {e(period)}{f" · Parliament Today {e(nice(ed['today_date']))}" if ed.get("today_date") else ""}</p>
<h1>{e(headline)}</h1><p class="dek">{e(summary)}</p>{vbadge}
<div class="figs"><div><b>{feed["questionsScanned"]:,}</b><span>written questions screened</span></div>
<div><b>{nq}</b><span>items screened in</span></div><div><b>{len(profiles)}</b><span>members profiled</span></div>
<div><b>{ns}</b><span>relevant statements of {feed.get("statementsScanned", "?")}</span></div></div></div>
<div class="pic"><h2>Where the matches fell</h2><p class="key">Written questions and statements by first topic<i style="background:var(--g)"></i>Commons<i style="background:var(--r)"></i>Lords</p>{chart(feed)}</div>
</div></header>
<nav class="scroll" aria-label="Sections">{navhtml}</nav>
{section("vi", "Very important: for immediate attention", vi)}
{section("today", f"Parliament Today{(' · ' + nice(ed['today_date'])) if ed.get('today_date') else ''}", today)}
{section("debates", "Issues arising in debates", debates)}
<section class="band" id="questions"><div class="wrap"><h2>Questions</h2>{qed}
<div class="allq"><h3 class="grp" style="margin-top:28px">All screened written questions, by topic</h3><p class="meta">Every item the screening layers caught, including some that review shows are only incidentally relevant. Open a row for the full text.</p>{question_rows(feed, pid)}</div>
<p class="printonly meta">The full list of all {nq} screened written questions, with question and answer text, is in the HTML edition of this briefing.</p></div></section>
{section("committees", "Committees", committees)}
<section class="band" id="other"><div class="wrap"><h2>Other sources</h2>{other}
<h3 class="grp">Written ministerial statements</h3>{f"<ul>{stm}</ul>" if stm else f"<p>None of the {feed.get('statementsScanned', 0)} written statements made in the period touched these topics.</p>"}</div></section>
<section class="band" id="members"><div class="wrap"><h2>Who asked: member profiles</h2>
<p class="meta" style="max-width:82ch">Built from Parliament's public record: the Members API (roles, committees, registered interests, self-declared focus) and each member's written questions over the past 12 months. Signals are readings of that evidence, not statements of fact about motives.</p>
<div class="filter"><label for="mf">Filter members</label><input id="mf" type="search" placeholder="Name, party, seat or topic"><span id="mc" class="meta"></span></div>
<div class="cards" id="cards">{"".join(profile_card(p, colours.get(p["id"]), notes) for p in profiles)}</div></div></section>
<section class="band" id="coverage"><div class="wrap cov"><h2>Coverage note</h2>
<p>Period covered: {e(period)}. Generated {e(feed["generatedUtc"])} from the UK Parliament written questions and statements service and Members API.</p>
<p>Screened {feed["questionsScanned"]:,} written questions answered or newly tabled in the period (Commons and Lords), using full question and answer text, and {feed.get("statementsScanned", 0)} written statements.</p>
{cov_extra}{vblock}{f"<p><b>Data warnings</b></p><ul>{warn}</ul>" if warn else "<p>No data warnings: every request completed.</p>"}</div></section>
<script>{{const i=document.getElementById('mf'),c=[...document.querySelectorAll('#cards .card')],n=document.getElementById('mc');
const f=()=>{{const q=i.value.trim().toLowerCase();let k=0;for(const x of c){{const s=!q||x.dataset.q.toLowerCase().includes(q);x.hidden=!s;if(s)k++}}n.textContent=k+' of '+c.length+' members'}};
i.addEventListener('input',f);f();}}</script>
</body></html>"""
