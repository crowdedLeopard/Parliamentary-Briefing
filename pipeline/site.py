"""Build the briefing website into _site/.

  index.html                 latest briefing at the top, then the archive: a calendar and a search of every edition
  <date>.html                each day's full report, with a day bar added at the top (previous / next / date /
                             continuing threads). render.py is untouched; the bar is added here, so older editions get it too
  latest.html                opens the newest edition
  themes.html                what links questions across days (trends.py)
  timeline.html              questions by date tabled, against news and events (news.py)
  search.json                compact index of every screened question, loaded only when someone searches
  staticwebapp.config.json   access rules if hosted on Azure Static Web Apps

The analysis and news steps can fail without stopping the site: the pages then say what is missing.
Standard library only (the site job installs nothing).
"""

from __future__ import annotations

import json
import re
import os
import shutil
import sys
import traceback
from calendar import Calendar
from datetime import date, timedelta
from html import escape as e
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from redact import scrub  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_site"

SWA_CONFIG = {
    "routes": [
        {"route": "/.auth/login/github", "statusCode": 404},
        {"route": "/.auth/login/twitter", "statusCode": 404},
        {"route": "/login", "rewrite": "/.auth/login/aad"},
        {"route": "/logout", "redirect": "/.auth/logout"},
        {"route": "/*", "allowedRoles": ["briefing"]},
    ],
    "responseOverrides": {"401": {"redirect": "/.auth/login/aad?post_login_redirect_uri=.referrer", "statusCode": 302},
                          "403": {"rewrite": "/403.html"}},
    "globalHeaders": {"X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer",
                      "X-Content-Type-Options": "nosniff"},
}
KIND = {"followup": "Follow-up questions", "series": "Question series", "subject": "Shared subject", "wording": "Similar wording"}
KIND_HELP = {
    "followup": "Questions that cite an earlier answer, from the same member to the same department.",
    "series": "One member asking three or more questions on the same subject, or to one department on one day.",
    "subject": "Three or more members on the same Parliament subject heading, reaching the briefing within 14 days.",
    "wording": "Questions from different members with near-identical wording, tabled within 7 days of each other.",
}
STATE = {"new": "New", "continuing": "Continuing", "growing": "Growing"}


def nice(d: str) -> str:
    return date.fromisoformat(d).strftime("%A %-d %B %Y")


def short(d: str) -> str:
    return date.fromisoformat(d).strftime("%a %-d %b")


def status(v: dict | None) -> tuple[str, str]:
    if not v or v.get("verdict") in (None, "not run"):
        return "Not validated", "warn"
    rules = (v.get("ruleChecks") or {}).get("issues") or []
    if v.get("verdict") == "fail" or rules:
        return "Failed validation", "warn"
    return ("Validated with corrections" if v.get("verdict") == "pass_with_fixes" else "Validated"), ""


def clip(s: str, n: int) -> str:
    """Cut at a word boundary and mark the cut."""
    s = s or ""
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def jscript(obj) -> str:
    """JSON safe to place inside a <script> element."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")


# ---------- shared look (same tokens as the reports) ----------

CSS = """
:root{color-scheme:light dark;--bg:light-dark(#fff,#0b1411);--ink:light-dark(#121417,#e8efeb);--mut:light-dark(#4d5752,#a9b8b0);
--rule:light-dark(#d5ddd8,#24332c);--g:light-dark(#0b6b4b,#3fb487);--r:light-dark(#a2192f,#e0566c);--tint:light-dark(#eaf4ef,#12231c);
--t1:light-dark(#e3f1ea,#16372a);--t2:light-dark(#b9dccb,#1f5a43);--t3:light-dark(#6fb898,#2f8a66);--on3:light-dark(#fff,#06120d);
--card:light-dark(#fff,#0f1b16);--amber:light-dark(#8a5a00,#e3b25a);--abg:light-dark(#fdf2dc,#33270f)}
:root[data-theme=light]{color-scheme:light}:root[data-theme=dark]{color-scheme:dark}
*{box-sizing:border-box;min-width:0}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 "Source Sans 3",system-ui,sans-serif}
a{color:var(--g);text-underline-offset:2px}a:focus-visible,button:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--g);outline-offset:2px}
h1,h2,h3{font-family:"Source Serif 4",Georgia,serif;line-height:1.12;margin:0;text-wrap:balance}
.wrap{max-width:1100px;margin:0 auto}
.site{background:#0b6b4b;color:#fff;padding:10px max(5vw,16px)}.site .wrap{display:flex;flex-wrap:wrap;gap:4px 18px;align-items:center}
.site .brand{font:700 18px "Source Serif 4",Georgia,serif;color:#fff;text-decoration:none;margin-right:auto}
.site nav{display:flex;flex-wrap:wrap;gap:2px}.site nav a{color:#fff;text-decoration:none;font-weight:600;padding:6px 10px;border-radius:3px;opacity:.85}
.site nav a:hover,.site nav a[aria-current]{opacity:1;background:rgba(255,255,255,.18)}
main{padding:clamp(24px,4vw,44px) max(5vw,16px)}section+section{margin-top:40px}
h1{font-size:clamp(30px,4vw,42px);margin-bottom:10px}h2{font-size:26px;margin-bottom:12px}h3{font-size:19px}
.lede{font-size:18px;max-width:68ch;color:var(--mut);margin:0 0 8px}.note{font-size:14px;color:var(--mut);margin:6px 0}
.tbl{overflow-x:auto}table{border-collapse:collapse;width:100%;font-size:15px;font-variant-numeric:tabular-nums}
th{text-align:left;font-weight:600;color:var(--mut);font-size:14px;border-bottom:2px solid var(--ink);padding:6px 8px}
td{border-bottom:1px solid var(--rule);padding:7px 8px;vertical-align:top}td.n{text-align:center;font-weight:600}
.h1{background:var(--t1)}.h2{background:var(--t2)}.h3{background:var(--t3);color:var(--on3)}
.pill{display:inline-block;font-size:12px;font-weight:700;letter-spacing:.03em;padding:1px 8px;border-radius:3px;border:1px solid var(--rule);color:var(--mut)}
.pill.ms{color:var(--r);border-color:var(--r)}.pill.grow{color:var(--g);border-color:var(--g)}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,330px),1fr));gap:16px}
.card{border:1px solid var(--rule);border-radius:4px;padding:14px;background:var(--card);display:grid;gap:6px;align-content:start;scroll-margin-top:16px}
.card:target{outline:3px solid var(--g)}.card ul{margin:0;padding-left:18px;font-size:14px}.card li{margin:3px 0}
.meta{font-size:14px;color:var(--mut);margin:0}
footer{padding:24px max(5vw,16px);color:var(--mut);font-size:14px;border-top:1px solid var(--rule)}
@media (prefers-reduced-motion:reduce){*{scroll-behavior:auto!important}}
"""
FONTS = ('<link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700'
         '&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap" rel="stylesheet">')


def page(title: str, current: str, body: str, latest: str, extra_css: str = "", script: str = "") -> str:
    links = [("index.html", "Home"), (f"{latest}.html", "Latest briefing"), ("themes.html", "Themes"), ("timeline.html", "Timeline")]
    nav = "".join(f'<a href="{h}"{" aria-current=page" if h == current else ""}>{t}</a>' for h, t in links)
    return scrub(f"""<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><title>{e(title)}</title>{FONTS}<style>{CSS}{extra_css}</style></head><body>
<header class="site"><div class="wrap"><a class="brand" href="index.html">Parliamentary briefing</a><nav aria-label="Site">{nav}</nav></div></header>
{body}
<footer><div class="wrap">Built from the UK Parliament APIs. Themes and the timeline are pattern-finding from the public record, not conclusions about why members ask what they ask.</div></footer>
{f"<script>{script}</script>" if script else ""}</body></html>""")


# ---------- the day bar added to each report ----------

BAR_CSS = """<style>
.pb-bar{--pb-g:light-dark(#0b6b4b,#3fb487);--pb-rule:light-dark(#d5ddd8,#24332c);--pb-mut:light-dark(#4d5752,#a9b8b0);--pb-bg:light-dark(#f4f7f5,#111d18);
background:var(--pb-bg);border-bottom:1px solid var(--pb-rule);padding:8px max(5vw,16px);font:15px/1.4 "Source Sans 3",system-ui,sans-serif}
.pb-bar .pb-in{max-width:1240px;margin:0 auto;display:grid;grid-template-columns:1fr auto 1fr;gap:6px 12px;align-items:center}
.pb-bar a{color:var(--pb-g);font-weight:600;text-decoration:none}.pb-bar a:hover{text-decoration:underline}
.pb-bar .pb-next{text-align:right}.pb-bar .pb-off{color:var(--pb-mut)}
.pb-mid{display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center;justify-content:center}
.pb-mid input{font:inherit;font-size:14px;padding:2px 6px;border:1px solid var(--pb-rule);border-radius:3px;background:transparent;color:inherit}
.pb-msg{color:var(--pb-mut);font-size:13px}
.pb-threads{max-width:1240px;margin:8px auto 0;display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.pb-threads b{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--pb-mut);margin-right:4px}
.pb-chip{display:inline-block;border:1px solid var(--pb-rule);border-radius:99px;padding:2px 10px;font-size:14px;font-weight:400!important;color:inherit!important}
.pb-chip.pb-ms{border-color:light-dark(#a2192f,#e0566c)}.pb-chip i{font-style:normal;font-weight:700;color:var(--pb-g)}
@media(max-width:640px){.pb-bar .pb-in{grid-template-columns:1fr 1fr}.pb-mid{grid-column:1/-1;order:-1;justify-content:flex-start}}
@media print{.pb-bar{display:none}}
</style>"""


def day_bar(d: str, prev: str | None, nxt: str | None, dates: list[str], threads: list[dict]) -> str:
    p = f'<a href="{e(prev)}.html" rel="prev">‹ {e(short(prev))}</a>' if prev else '<span class="pb-off">First edition</span>'
    n = f'<a href="{e(nxt)}.html" rel="next">{e(short(nxt))} ›</a>' if nxt else '<span class="pb-off">Newest edition</span>'
    chips = "".join(
        f'<a class="pb-chip{" pb-ms" if t["microsoft"] else ""}" href="themes.html#{e(t["id"])}"><i>{e(STATE[t["state"]])}</i> {e(t["title"])}'
        f' <small>+{t["added"]} in this edition, {t["soFar"]} so far</small></a>'
        for t in threads[:4])
    strip = f'<div class="pb-threads"><b>Continuing threads</b>{chips}<a href="themes.html">All themes</a></div>' if chips else ""
    js = ("(function(){var d=" + jscript(dates) + ",i=document.getElementById('pb-date'),m=document.getElementById('pb-msg');"
          "i.addEventListener('change',function(){var v=i.value;if(d.indexOf(v)>=0){location.href=v+'.html'}"
          "else{var n=d.filter(function(x){return x<=v}).pop();m.textContent=n?'No briefing that day. Nearest earlier: ':'No briefing that day.';"
          "if(n){var a=document.createElement('a');a.href=n+'.html';a.textContent=n;m.appendChild(a)}}})})();")
    return (f'{BAR_CSS}<nav class="pb-bar" aria-label="Briefing editions"><div class="pb-in">{p}'
            f'<div class="pb-mid"><a href="index.html">Home</a><label>Go to <input id="pb-date" type="date" value="{e(d)}"'
            f' min="{e(dates[0])}" max="{e(dates[-1])}"></label><a href="timeline.html">Timeline</a><span class="pb-msg" id="pb-msg" aria-live="polite"></span></div>'
            f'<div class="pb-next">{n}</div></div>{strip}</nav><script>{js}</script>')


def add_bar(html: str, bar: str) -> str:
    i = html.find("<body>")
    return scrub(html[:i + 6] + bar + html[i + 6:] if i >= 0 else bar + html)


# ---------- index: latest + calendar + search ----------

INDEX_JS = r"""
(function(){var q=document.getElementById('q'),t=document.getElementById('t'),rows=document.getElementById('rows'),hits=document.getElementById('hits'),
cnt=document.getElementById('cnt'),data=null,waiting=[],eds=[].slice.call(rows.children);
function load(cb){if(data)return cb();waiting.push(cb);if(waiting.length>1)return;cnt.textContent='Loading the index…';
fetch('search.json').then(function(r){return r.json()}).then(function(j){data=j;var w=waiting;waiting=[];w.forEach(function(f){f()})}).catch(function(){cnt.textContent='The search index could not be loaded. The list of editions still works.'})}
function esc(s){var d=document.createElement('div');d.textContent=s==null?'':String(s);return d.innerHTML}
function run(){var v=q.value.trim().toLowerCase(),tp=t.value;
eds.forEach(function(li){li.hidden=!!tp&&(li.dataset.t||'').split('|').indexOf(tp)<0});
if(!v){hits.innerHTML='';hits.hidden=true;cnt.textContent='';return}
load(function(){var out=[],n=0;for(var i=0;i<data.length;i++){var r=data[i];
if(tp&&r.t.indexOf(tp)<0)continue;if((r.m+' '+r.u+' '+r.h+' '+r.x+' '+r.b).toLowerCase().indexOf(v)<0)continue;n++;
if(out.length<200)out.push('<li><div><p class="d">'+esc(r.e)+' edition · '+esc(r.m)+(r.p?' ('+esc(r.p)+')':'')+' · '+esc(r.b)+'</p><a class="h t" href="'+esc(r.l)+'">'+esc(r.h||r.x)+'</a> <a href="'+esc(r.e)+'.html">Briefing</a></div></li>')}
hits.innerHTML=out.join('');hits.hidden=false;cnt.textContent=n+(n===1?' question':' questions')+' match'+(n===1?'es':'')+(n>200?'. Showing the newest 200.':'.')})}
q.addEventListener('input',run);t.addEventListener('change',run);q.addEventListener('focus',function(){load(function(){if(!q.value.trim())cnt.textContent=''})},{once:true});})();
"""


def calendar_html(eds: list[dict]) -> str:
    by = {x["date"]: x for x in eds}
    months = sorted({x["date"][:7] for x in eds}, reverse=True)
    out = []
    for i, ym in enumerate(months):
        y, m = map(int, ym.split("-"))
        cells = "".join(f'<span class="hd">{c}</span>' for c in "MTWTFSS")
        for d in Calendar(0).itermonthdates(y, m):
            if d.month != m:
                cells += "<span></span>"
                continue
            x = by.get(d.isoformat())
            if not x:
                cells += f"<span>{d.day}</span>"
                continue
            n = x["questions"]
            lvl = "h3" if n > 240 else "h2" if n >= 120 else "h1"
            tip = f'{nice(x["date"])}: {n} questions{", Microsoft named" if x["microsoft"] else ""}'
            cells += f'<a class="{lvl}{" ms" if x["microsoft"] else ""}" href="{x["date"]}.html" title="{e(tip)}" aria-label="{e(tip)}">{d.day}</a>'
        month = date(y, m, 1).strftime("%B %Y")
        block = f'<div><h3 style="margin-bottom:8px">{month}</h3><div class="cal">{cells}</div></div>'
        out.append(block if i < 3 else f"<details><summary>{month}</summary>{block}</details>")
    return "".join(out)


def search_index(items: list[dict]) -> list[dict]:
    from topics import to_plain_text
    from trends import PREFIX, SHORT, link, substantive
    rows = []
    newest = max((q.get("_first") or "" for q in items), default="")
    cutoff = (date.fromisoformat(newest) - timedelta(days=365)).isoformat() if newest else ""
    for q in sorted(items, key=lambda q: (q.get("_first") or "", str(q.get("uin"))), reverse=True):
        if (q.get("_first") or "") < cutoff:
            continue
        m = q.get("askingMember") or {}
        rows.append({"e": q.get("_first"), "u": str(q.get("uin") or ""), "m": m.get("name") or "",
                     "p": m.get("partyAbbreviation") or m.get("party") or "", "b": q.get("answeringBodyName") or "",
                     "h": q.get("heading") or "", "x": PREFIX.sub("", to_plain_text(q.get("questionText")))[:240], "l": link(q),
                     "t": "|".join(SHORT.get(t, t) for t in substantive(q))})
    return rows


# ---------- themes ----------

THEMES_CSS = """.kinds{display:grid;gap:34px}.kinds h3{font-size:21px}"""


def themes_html(a: dict, latest: str) -> str:
    from trends import SHORT
    eds = a["editions"][-14:]
    topics = [t for t in SHORT if any(x["topics"].get(t) for x in eds)]
    head = "".join(f"<th>{e(short(x['date']))}</th>" for x in eds)
    rows = ""
    for t in topics:
        cells = ""
        for x in eds:
            n = x["topics"].get(t, 0)
            lvl = "h3" if n >= 30 else "h2" if n >= 15 else "h1" if n else ""
            cells += f'<td class="n {lvl}">{n or "·"}</td>'
        rows += f"<tr><td>{e(SHORT[t])}</td>{cells}</tr>"
    if a["rising"]:
        rising = "<ul>" + "".join(f"<li><b>{e(SHORT.get(r['topic'], r['topic']))}</b>: {r['last7']} questions tabled in the last 7 days, "
                                   f"against {r['avg7']} a week over the previous four weeks</li>" for r in a["rising"]) + "</ul>"
    else:
        rising = (f'<p class="note">Rising topics need at least three weeks of editions to compare against. '
                  f'There are {a.get("historyDays", 0)} days so far.</p>')
    kinds = ""
    for k in ("subject", "followup", "series", "wording"):
        ts = [t for t in a["threads"] if t["kind"] == k][:12]
        if not ts:
            continue
        cards = ""
        for t in ts:
            members = ", ".join(f'{m["name"]}{" (" + m["party"] + ")" if m["party"] else ""}' for m in t["members"][:8])
            more = f" and {len(t['members']) - 8} more" if len(t["members"]) > 8 else ""
            lis = "".join(f'<li><a href="{e(i["link"])}">{e(i["uin"])}</a> {e(i["member"])}, tabled {e(short(i["date"]))}: '
                          f'{e(clip(i["text"], 140))}</li>' for i in t["items"][:8])
            if len(t["items"]) > 8:
                lis += f"<li>and {len(t['items']) - 8} more</li>"
            pills = ('<span class="pill ms">Microsoft named</span> ' if t["microsoft"] else "") + \
                "".join(f'<span class="pill">{e(SHORT.get(x, x))}</span> ' for x in t["topics"])
            eds_txt = ", ".join(f'<a href="{x}.html">{e(short(x))}</a>' for x in t["editions"][-5:])
            cards += (f'<article class="card" id="{e(t["id"])}"><div>{pills}</div><h3>{e(t["title"])}</h3>'
                      f'<p class="meta">{len(t["items"])} questions · tabled {e(short(t["from"]))} to {e(short(t["to"]))} · '
                      f'in the briefings of {eds_txt}</p><p class="meta">{e(members)}{more}</p><ul>{lis}</ul></article>')
        kinds += f'<section><h3>{KIND[k]}</h3><p class="note">{KIND_HELP[k]}</p><div class="cards">{cards}</div></section>'
    askers = "".join(f'<tr><td><a href="{latest}.html#m-{e(r["id"])}">{e(r["name"])}</a></td><td>{e(r["party"])}</td>'
                     f'<td class="n">{r["items"]}</td><td class="n">{r["editions"]}</td><td>{e(", ".join(r["topics"]))}</td></tr>'
                     for r in a["askers"])
    body = f"""<main><div class="wrap">
<h1>Themes across the briefings</h1>
<p class="lede">What links the questions in the briefings from day to day. Every pattern here comes from rules applied to the public record and links to the questions behind it. It describes what was asked, not why.</p>
<section><h2>Topics by edition</h2><p class="note">Screened questions per edition, by keyword topic. A question can count under more than one topic.</p>
<div class="tbl"><table><thead><tr><th>Topic</th>{head}</tr></thead><tbody>{rows}</tbody></table></div></section>
<section><h2>Rising topics</h2>{rising}</section>
<section><h2>Threads</h2><p class="note">From questions tabled in the last 90 days. A thread is new, continuing or growing in the edition it appears in, and is shown at the top of that briefing.</p>
<div class="kinds">{kinds or '<p>No threads found yet.</p>'}</div></section>
<section id="askers"><h2>Recurring askers</h2><p class="note">Members with the most screened questions in the last seven editions. Names link to their profile card in the latest briefing, where they have one.</p>
<div class="tbl"><table><thead><tr><th>Member</th><th>Party</th><th>Questions</th><th>Editions</th><th>Main topics</th></tr></thead><tbody>{askers}</tbody></table></div></section>
</div></main>"""
    return page("Themes · Parliamentary briefing", "themes.html", body, latest, THEMES_CSS)


# ---------- timeline ----------

TL_CSS = """
.chart{width:100%;height:auto;display:block}.chart text{fill:var(--mut);font:12px "Source Sans 3",system-ui,sans-serif}
.chart .lbl{fill:var(--ink);font-weight:600}.chart .grid{stroke:var(--rule)}.chart .b1{fill:var(--g)}.chart .b2{fill:var(--t3)}
.chart .band{fill:var(--abg)}.chart rect:hover,.chart path:hover{opacity:.8}
.ev{display:grid;grid-template-columns:120px minmax(0,1fr);gap:4px 16px;border-top:1px solid var(--rule);padding:12px 0}
@media(max-width:560px){.ev{grid-template-columns:minmax(0,1fr)}}
.ev .when{font-weight:700;font-variant-numeric:tabular-nums}.kind{font-size:12px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--amber)}
.ev ul{margin:6px 0 0;padding-left:18px;font-size:15px}.lag{font-variant-numeric:tabular-nums;color:var(--mut);font-size:13px;margin-right:6px}
.heads{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,320px),1fr));gap:18px}.heads ul{margin:0;padding-left:18px;font-size:15px}
"""


def bars_svg(days: list[str], vals: list[int], cls: str, label: str, bands: list[tuple[str, str, str]]) -> str:
    W, H, L, R, T, B = 1000, 200, 40, 12, 24, 30
    n = len(days)
    bw = (W - L - R) / n
    top = max(vals + [1])
    step = 1 if top <= 5 else 2 if top <= 10 else 5 if top <= 25 else 10 if top <= 50 else 50 if top <= 250 else 100 if top <= 500 else 500
    top = ((top + step - 1) // step) * step
    y = lambda v: T + (H - T - B) * (1 - v / top)  # noqa: E731
    s = []
    for (d0, d1, name) in bands:
        if d1 < days[0] or d0 > days[-1]:
            continue
        i0 = max(0, days.index(d0) if d0 in days else 0)
        i1 = days.index(d1) if d1 in days else n - 1
        s.append(f'<rect class="band" x="{L + bw * i0:.1f}" y="{T}" width="{bw * (i1 - i0 + 1):.1f}" height="{H - T - B}"><title>{e(name)}</title></rect>')
        s.append(f'<text class="lbl" x="{L + bw * i0 + 3:.1f}" y="{T - 8}">{e(clip(name, 48))}</text>')
    for v in range(0, top + 1, step):
        s.append(f'<line class="grid" x1="{L}" x2="{W - R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/><text x="{L - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{v}</text>')
    for i, (d, v) in enumerate(zip(days, vals)):
        x, w = L + bw * i + bw * .18, bw * .64
        if v:
            yy = y(v)
            r = min(4, w / 2, (H - B - yy))
            s.append(f'<path class="{cls}" d="M{x:.1f} {H - B}V{yy + r:.1f}q0 -{r:.1f} {r:.1f} -{r:.1f}h{w - 2 * r:.1f}q{r:.1f} 0 {r:.1f} {r:.1f}V{H - B}Z">'
                     f'<title>{e(short(d))}: {v} {e(label)}</title></path>')
        if i % 2 == 0 or n <= 14:
            s.append(f'<text x="{x + w / 2:.1f}" y="{H - B + 16}" text-anchor="middle">{date.fromisoformat(d).day}</text>')
    return f'<svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{e(label)} per day">{"".join(s)}</svg>'


def timeline_html(a: dict, news: dict | None, news_err: str | None, latest: str) -> str:
    tab = a["tabled"]
    days = [r["date"] for r in tab]
    evs = (news or {}).get("events") or []
    bands = [(x["date"], x["endDate"], x["title"]) for x in evs if x.get("origin") == "events.json"]
    q_svg = bars_svg(days, [r["total"] for r in tab], "b1", "screened questions tabled", bands)
    vol = (news or {}).get("volume") or {}
    n_svg = bars_svg(days, [int(vol.get(d, 0)) for d in days], "b2", "UK news articles", bands) if vol else ""
    shown = [x for x in evs if x["endDate"] >= days[0] or any(r["date"] >= days[0] for r in x.get("direct") or [])]
    evhtml = ""
    for x in shown[:40]:
        when = short(x["date"]) + (f" to {short(x['endDate'])}" if x["endDate"] != x["date"] else "")
        src = f'<a href="{e(x["source"])}">{e(x["outlet"] or "Source")}</a>' if x["source"] else e(x["outlet"])
        direct = "".join(f'<li><span class="lag">+{r["lag"]} day{"" if r["lag"] == 1 else "s"}</span>{e(r["member"])}{" (" + e(r["party"]) + ")" if r["party"] else ""}: '
                         f'<a href="{e(r["link"])}">{e(r["uin"] or "Hansard")}</a> {e(clip(r["text"], 150))}</li>' for r in x["direct"][:10])
        poss = f'<p class="note">{x["possible"]} other questions on the same topics were tabled in the 21 days after. Shared topic and timing only, not a stated link.</p>' if x["possible"] else ""
        evhtml += (f'<div class="ev"><p class="when">{e(when)}</p><div><p class="kind">{e(x["kind"])}</p><h3>{e(x["title"])}</h3>'
                   f'<p class="meta">{src}</p>{"<ul>" + direct + "</ul>" if direct else ""}{poss}</div></div>')
    heads = (news or {}).get("headlines") or []
    hh = ""
    for g in sorted({h["group"] for h in heads}):
        lis = "".join(f'<li><a href="{e(h["source"])}">{e(h["title"])}</a> <span class="meta">{e(h["outlet"])}, {e(short(h["date"]))}</span></li>'
                      for h in [h for h in heads if h["group"] == g][:6])
        hh += f"<div><h3>{e(g)}</h3><ul>{lis}</ul></div>"
    gaps = list((news or {}).get("gaps") or []) + ([news_err] if news_err else [])
    body = f"""<main><div class="wrap">
<h1>Timeline</h1>
<p class="lede">Questions by the day they were tabled, set against news and tech events. Answers arrive days or weeks later, so the tabling date is what lines up with events.</p>
<section><h2>Screened questions tabled, last 28 days</h2>
<p class="note">Questions with a keyword topic, counted on the day tabled, from {e(short(days[0]))} to {e(short(days[-1]))}. Recent days fill in as questions are answered and reach later editions. Shaded bands are events from the hand-kept list.</p>{q_svg}</section>
{f'<section><h2>UK news coverage of the same topics</h2><p class="note">Articles per day from UK outlets matching the briefing topics, from the GDELT news index. Same dates as the chart above.</p>{n_svg}</section>' if n_svg else ""}
<section><h2>Events and what followed</h2><p class="note">A direct link means the question or speech names the event. Lags count days from the event's start to the date tabled or spoken.</p>{evhtml or "<p>No events in this period.</p>"}</section>
{f'<section><h2>Recent headlines</h2><div class="heads">{hh}</div></section>' if hh else ""}
<section><h2>Sources</h2><p class="note">Events: <code>data/events.json</code> in the repository, edited by hand; announcements from the GOV.UK search API for DSIT, CMA, Ofcom, ICO, NCSC, HM Treasury, the Cabinet Office and DESNZ; news from GDELT. Only headlines, outlets, dates and links are kept.</p>
{"".join(f'<p class="note"><b>Gap:</b> {e(g)}</p>' for g in gaps)}</section>
</div></main>"""
    return page("Timeline · Parliamentary briefing", "timeline.html", body, latest, TL_CSS)



# ---------- homepage: every feature visible, then read any day ----------

HOME_CSS = """
.top{background:#0b6b4b;color:#fff;padding:clamp(24px,4vw,44px) max(5vw,16px)}
.top .wrap{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.25fr);gap:clamp(20px,4vw,48px);align-items:start}
@media(max-width:860px){.top .wrap{grid-template-columns:minmax(0,1fr)}}
.top h1{color:#fff;font-size:clamp(30px,4vw,42px)}.top .k{margin:0 0 6px;opacity:.85}.top p{margin:0}
.pick{display:grid;gap:10px;margin-top:18px}.pick label{font-weight:700}
.pick .row{display:flex;flex-wrap:wrap;gap:8px}.pick select{flex:1 1 16em;font:inherit;padding:10px;border-radius:3px;border:0;background:#fff;color:#121417}
.btn{display:inline-block;background:#fff;color:#0b6b4b;font-weight:700;padding:10px 16px;border-radius:3px;text-decoration:none;border:0;font:inherit;font-weight:700;cursor:pointer}
.quick{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:15px}.quick a{color:#fff}
.latest{background:var(--bg);color:var(--ink);border-radius:4px;padding:18px 20px;display:grid;gap:10px}
.latest h2{font-size:clamp(20px,2.2vw,25px);margin:0}.latest .sum{color:var(--mut);font-size:15px}
.figs{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;font-variant-numeric:tabular-nums}
.figs div{background:var(--tint);padding:8px 10px;border-radius:3px}.figs b{display:block;font:700 22px/1.1 "Source Serif 4",serif}.figs span{font-size:13px;color:var(--mut)}
.latest .go{display:flex;flex-wrap:wrap;gap:10px;align-items:center}.latest .go a.btn{background:#0b6b4b;color:#fff}
.ok{color:var(--g);font-weight:600}.warn{color:var(--r);font-weight:600}
.feat{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:18px}
.tile{border:1px solid var(--rule);border-radius:4px;padding:16px;display:grid;gap:10px;align-content:start;background:var(--card)}
.tile h3{font-size:20px}.tile .more{font-weight:700;text-decoration:none}.tile .more:hover{text-decoration:underline}
.tile ul{margin:0;padding:0;list-style:none;display:grid;gap:8px;font-size:15px}.tile li{border-top:1px solid var(--rule);padding-top:8px}
.chip{display:inline-block;font-size:12px;font-weight:700;color:var(--g);margin-right:4px}.chip.ms{color:var(--r)}
.spark{display:grid;grid-template-columns:minmax(0,9em) minmax(0,1fr) 2.4em;gap:8px;align-items:center;font-size:14px;font-variant-numeric:tabular-nums}
.spark i{display:block;height:10px;background:var(--g);border-radius:0 3px 3px 0}.spark b{text-align:right}
.arch{display:grid;grid-template-columns:minmax(0,300px) minmax(0,1fr);gap:32px;align-items:start}
@media(max-width:780px){.arch{grid-template-columns:minmax(0,1fr)}}
.months{display:grid;gap:22px}.cal{display:grid;grid-template-columns:repeat(7,1fr);gap:4px;font-variant-numeric:tabular-nums}
.cal span,.cal a{aspect-ratio:1;max-width:100%;border-radius:4px;display:grid;place-items:center;font-size:14px;color:var(--mut);position:relative;text-decoration:none}
.cal .hd{font-size:12px;aspect-ratio:auto}.cal a{color:var(--ink);font-weight:600}.cal a:hover{outline:2px solid var(--g)}
.cal a.ms::after{content:"";position:absolute;top:3px;right:3px;width:6px;height:6px;border-radius:50%;background:var(--r)}
.legend{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:13px;color:var(--mut)}.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:4px;vertical-align:-2px}
.find{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:6px}.find input,.find select{font:inherit;padding:8px 10px;border:1px solid var(--rule);border-radius:3px;background:var(--card);color:var(--ink)}
.find input{flex:1 1 260px}
ul.rows{list-style:none;margin:0;padding:0}ul.rows li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 16px;padding:12px 0;border-top:1px solid var(--rule)}
.rows .d{font-size:14px;color:var(--mut)}.rows .h{font-weight:700;font-size:17px;color:var(--ink);text-decoration:none}.rows a.h:hover{color:var(--g);text-decoration:underline}
.rows .s{font-size:13px;color:var(--mut);text-align:right;font-variant-numeric:tabular-nums}
.hits li{grid-template-columns:minmax(0,1fr)!important}.hits .t{font-size:15px}
"""

HOME_JS = "(function(){var s=document.getElementById('day'),b=document.getElementById('go');" \
          "b.addEventListener('click',function(){location.href=s.value+'.html'});})();" + INDEX_JS


def title_of(ed: dict) -> str:
    """The edition's short title; older editions without one get the headline's first clause, cut to 8 words."""
    if ed.get("title"):
        return ed["title"]
    first = re.split(r"[:;,.]\s| as | while | alongside | and the ", ed.get("headline") or "", maxsplit=1)[0].strip()
    words = first.split()
    return " ".join(words[:8]) + ("…" if len(words) > 8 else "")


def home_html(latest: dict, facts: dict, dates: list[str], rows: list[str], a: dict | None, news: dict | None, a_err: str | None) -> str:
    from trends import SHORT
    d = latest["date"]
    f = facts.get(d, {})
    heads = {}
    for x in (a or {}).get("editions", []):
        heads[x["date"]] = title_of(x)
    opts = "".join(f'<option value="{x}">{e(nice(x))}{" · " + e(heads[x]) if heads.get(x) else ""}</option>'
                   for x in reversed(dates))
    prev = dates[-2] if len(dates) > 1 else None
    quick = f'<a href="{d}.html">Latest: {e(short(d))}</a>' + (f'<a href="{prev}.html">The day before: {e(short(prev))}</a>' if prev else "") + \
        '<a href="#archive">Calendar of every edition</a>'
    figs = (f'<div class="figs"><div><b>{f.get("scanned", 0):,}</b><span>questions screened</span></div>'
            f'<div><b>{f.get("questions", 0)}</b><span>relevant to our topics</span></div>'
            f'<div><b>{"Yes" if f.get("microsoft") else "No"}</b><span>Microsoft named</span></div></div>') if f else ""
    top = f"""<section class="top"><div class="wrap">
<div><p class="k">Daily UK Parliament briefing</p><h1>Parliamentary briefing</h1>
<p>Every day's written questions, debates, committees and statements on our issues, plus what links them across days and how they line up with the news.</p>
<div class="pick"><label for="day">Read the briefing for</label><div class="row"><select id="day">{opts}</select><button class="btn" id="go" type="button">Read</button></div>
<div class="quick">{quick}</div></div></div>
<div class="latest"><p class="meta">Latest edition · {e(nice(d))}</p><h2>{e(latest["title"])}</h2>
<p class="sum">{e(clip(latest["headline"], 260))}</p>{figs}
<div class="go"><a class="btn" href="{d}.html">Read this briefing</a><span class="{latest["cls"] or "ok"}">{e(latest["label"])}</span></div></div>
</div></section>"""

    # feature tiles, each a live preview of its page
    th = ((a or {}).get("byEdition") or {}).get(d, [])
    if th:
        t_lis = "".join(f'<li><span class="chip{" ms" if t["microsoft"] else ""}">{e(STATE[t["state"]])}</span>'
                        f'<a href="themes.html#{e(t["id"])}">{e(t["title"])}</a> <span class="meta">+{t["added"]} in this edition, {t["soFar"]} so far</span></li>'
                        for t in th[:5])
    else:
        t_lis = "<li>No continuing threads in the latest edition.</li>"
    threads_tile = (f'<article class="tile"><h3>Continuing threads</h3><p class="meta">Questions in the latest edition that link to earlier ones: '
                    f'follow-ups, series, shared subjects and similar wording.</p><ul>{t_lis}</ul><a class="more" href="themes.html">All themes ›</a></article>')

    evs = [x for x in (news or {}).get("events", []) if x.get("direct")][:3]
    if evs:
        ev_lis = "".join(f'<li><b>{e(short(x["date"]))}</b> {e(x["title"])}<br><span class="meta">Followed by '
                         + ", ".join(f'{e(r["member"])} (+{r["lag"]} day{"" if r["lag"] == 1 else "s"})' for r in x["direct"][:3]) + "</span></li>" for x in evs)
    else:
        ev_lis = "<li>No events with a direct parliamentary follow-up yet.</li>"
    news_tile = (f'<article class="tile"><h3>In the news, then in Parliament</h3><p class="meta">Tech events and announcements, and the questions '
                 f'and speeches that followed them.</p><ul>{ev_lis}</ul><a class="more" href="timeline.html">Timeline ›</a></article>')

    recent = (a or {}).get("editions", [])[-7:]
    tot = {}
    for x in recent:
        for t, n in x["topics"].items():
            tot[t] = tot.get(t, 0) + n
    top_t = sorted(tot.items(), key=lambda kv: -kv[1])[:6]
    mx = max([n for _, n in top_t] + [1])
    sp = "".join(f'<div class="spark"><span>{e(SHORT.get(t, t))}</span><i style="width:{max(4, round(100 * n / mx))}%"></i><b>{n}</b></div>' for t, n in top_t)
    topics_tile = (f'<article class="tile"><h3>Topics in the last {len(recent)} edition{"s" if len(recent) != 1 else ""}</h3>'
                   f'<p class="meta">Relevant questions by topic.</p><div style="display:grid;gap:6px">{sp or "<p>No data yet.</p>"}</div>'
                   f'<a class="more" href="themes.html">Topics by day ›</a></article>')

    ask = "".join(f'<li><a href="{d}.html#m-{e(r["id"])}">{e(r["name"])}</a> <span class="meta">{e(r["party"])} · {r["items"]} questions in '
                  f'{r["editions"]} edition{"s" if r["editions"] != 1 else ""} · {e(", ".join(r["topics"]))}</span></li>'
                  for r in (a or {}).get("askers", [])[:5])
    askers_tile = (f'<article class="tile"><h3>Who keeps asking</h3><p class="meta">Members with the most relevant questions in the last seven editions.</p>'
                   f'<ul>{ask or "<li>No data yet.</li>"}</ul><a class="more" href="themes.html#askers">All recurring askers ›</a></article>')

    topic_opts = "".join(f"<option>{e(x)}</option>" for x in SHORT.values())
    cal = calendar_html(a["editions"]) if a else ""
    body = f"""{top}<main><div class="wrap">
<section><h2>What's in the briefing</h2><div class="feat">{threads_tile}{news_tile}{topics_tile}{askers_tile}</div>
{f'<p class="note">{e(a_err)}</p>' if a_err else ""}</section>
<section><h2>Search every briefing</h2>
<div class="find"><input id="q" type="search" placeholder="Member, UIN, subject or any words" aria-label="Search every briefing">
<select id="t" aria-label="Topic"><option value="">All topics</option>{topic_opts}</select></div>
<p class="note" id="cnt" aria-live="polite"></p><ul class="rows hits" id="hits" hidden></ul></section>
<section id="archive"><h2>Every edition</h2><div class="arch">
<div class="months">{cal}<div class="legend"><span><i class="h1"></i>under 120 questions</span><span><i class="h2"></i>120 to 240</span><span><i class="h3"></i>over 240</span><span><i style="background:var(--r);border-radius:50%;width:8px;height:8px"></i>Microsoft named</span></div></div>
<ul class="rows" id="rows">{"".join(rows)}</ul></div></section>
</div></main>"""
    return page("Parliamentary briefing", "index.html", body, d, HOME_CSS, HOME_JS)

# ---------- build ----------

def build() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    reps = sorted((ROOT / "reports").glob("20??-??-??.html"))
    if not reps:
        print("no reports yet")
        return 1
    dates = [r.stem for r in reps]
    latest_d = dates[-1]

    analysis, a_err = None, None
    try:
        import trends
        analysis = trends.analyse(ROOT)
    except Exception:  # noqa: BLE001 - the archive must still publish
        a_err = "The cross-day analysis could not be built: " + traceback.format_exc(limit=1).strip().splitlines()[-1]
        print("::warning::" + a_err)
    by_ed = (analysis or {}).get("byEdition") or {}
    ed_facts = {x["date"]: x for x in (analysis or {}).get("editions", [])}

    rows, latest = [], None
    for i, rep in enumerate(reversed(reps)):
        d = rep.stem
        k = len(dates) - 1 - i
        html = rep.read_text(encoding="utf-8")
        bar = day_bar(d, dates[k - 1] if k > 0 else None, dates[k + 1] if k + 1 < len(dates) else None, dates, by_ed.get(d, []))
        edf = ROOT / "editorial" / f"{d}.json"
        vf = ROOT / "editorial" / f"{d}.validation.json"
        ed = json.loads(edf.read_text()) if edf.exists() else {}
        if ed.get("title") and f"<h1>{e(ed['title'])}</h1>" not in html:
            # reports rendered before titles existed: show the title, keep the headline beneath it
            html = re.sub(r"<h1>(.*?)</h1>", lambda m: f'<h1>{e(ed["title"])}</h1><p class="dek"><b>{m.group(1)}</b></p>', html, count=1, flags=re.S)
        (OUT / rep.name).write_text(add_bar(html, bar), encoding="utf-8")
        v = json.loads(vf.read_text()) if vf.exists() else None
        label, cls = status(v)
        f = ed_facts.get(d, {})
        item = {"date": d, "title": title_of(ed) or "Data-only briefing", "headline": ed.get("headline") or "Data-only briefing", "summary": ed.get("summary") or "", "label": label, "cls": cls}
        latest = latest or item
        from trends import SHORT
        tags = "|".join(SHORT.get(t, t) for t in (f.get("topics") or {})) + ("|Microsoft" if f.get("microsoft") else "")
        stat = (f'{f.get("questions", "?")} questions · {f.get("scanned", 0):,} screened<br>' if f else "")
        rows.append(f'<li data-t="{e(tags)}"><div><p class="d">{e(nice(d))}{" · Microsoft named" if f.get("microsoft") else ""}</p>'
                    f'<a class="h" href="{e(d)}.html">{e(item["title"])}</a><p class="s">{e(clip(item["headline"], 200))}</p></div><p class="s">{stat}<span class="{"warn" if cls else "ok"}">{e(label)}</span></p></li>')

    (OUT / "latest.html").write_text(f'<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8"><meta name="robots" content="noindex,nofollow">'
                                     f'<meta http-equiv="refresh" content="0;url={latest_d}.html"><title>Latest briefing</title></head>'
                                     f'<body><p><a href="{latest_d}.html">Open the latest briefing</a></p></body></html>')

    from trends import SHORT
    news, n_err = None, None
    if analysis:
        (OUT / "search.json").write_text(json.dumps(search_index(analysis["items"]), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        (OUT / "themes.html").write_text(themes_html(analysis, latest_d), encoding="utf-8")
        if os.environ.get("NEWS_DISABLED", "").lower() != "true":
            try:
                import news as newsmod
                import trends
                news = newsmod.collect(analysis["items"], date.fromisoformat(latest_d), speeches=trends.speeches(ROOT), root=ROOT)
            except Exception:  # noqa: BLE001
                n_err = "News and events could not be gathered: " + traceback.format_exc(limit=1).strip().splitlines()[-1]
                print("::warning::" + n_err)
        else:
            n_err = "News fetching is turned off (NEWS_DISABLED=true)."
        (OUT / "timeline.html").write_text(timeline_html(analysis, news, n_err, latest_d), encoding="utf-8")
    else:
        for name, title in (("themes.html", "Themes"), ("timeline.html", "Timeline")):
            (OUT / name).write_text(page(f"{title} · Parliamentary briefing", name,
                                         f'<main><div class="wrap"><h1>{title}</h1><p>{e(a_err or "Not available.")}</p></div></main>', latest_d))

    (OUT / "index.html").write_text(home_html(latest, ed_facts, dates, rows, analysis, news, a_err), encoding="utf-8")

    (OUT / "403.html").write_text("<!DOCTYPE html><html lang='en-GB'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>No access</title></head>"
                                  "<body style='font:17px system-ui;margin:10vh auto;max-width:36em;padding:0 16px'><h1>You don't have access yet</h1>"
                                  "<p>This site is private. Ask the owner to invite you to the briefing site, then sign in again with your Microsoft account.</p>"
                                  "<p><a href='/logout'>Sign out</a></p></body></html>")
    (OUT / "staticwebapp.config.json").write_text(json.dumps(SWA_CONFIG, indent=2))
    (OUT / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (OUT / ".nojekyll").write_text("")
    print(f"site: {len(rows)} briefings, {len((analysis or {}).get('threads', []))} threads")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
