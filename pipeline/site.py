"""Build the private briefing website into _site/.

  index.html                 latest briefing at the top, then the archive
  <date>.html                each day's full report
  staticwebapp.config.json   access rules if hosted on Azure Static Web Apps
                             (only people invited to the 'briefing' role, Microsoft sign-in)
"""

from __future__ import annotations

import json
import shutil
from datetime import date
from html import escape as e
from pathlib import Path

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


def nice(d: str) -> str:
    return date.fromisoformat(d).strftime("%A %-d %B %Y")


def status(v: dict | None) -> tuple[str, str]:
    if not v or v.get("verdict") in (None, "not run"):
        return "Not validated", "warn"
    rules = (v.get("ruleChecks") or {}).get("issues") or []
    if v.get("verdict") == "fail" or rules:
        return "Failed validation", "warn"
    return ("Validated with corrections" if v.get("verdict") == "pass_with_fixes" else "Validated"), ""


def build() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()
    rows, latest = [], None
    for rep in sorted((ROOT / "reports").glob("20??-??-??.html"), reverse=True):
        d = rep.stem
        shutil.copy(rep, OUT / rep.name)
        ed = json.loads((ROOT / "editorial" / f"{d}.json").read_text()) if (ROOT / "editorial" / f"{d}.json").exists() else {}
        v = json.loads((ROOT / "editorial" / f"{d}.validation.json").read_text()) if (ROOT / "editorial" / f"{d}.validation.json").exists() else None
        label, cls = status(v)
        item = {"date": d, "headline": ed.get("headline") or "Data-only briefing", "summary": ed.get("summary") or "",
                "label": label, "cls": cls}
        latest = latest or item
        rows.append(f'<li><a href="{e(d)}.html"><span class="d">{e(nice(d))}</span><span class="h">{e(item["headline"])}</span></a>'
                    f'<span class="s {cls}">{e(label)}</span></li>')
    if not latest:
        print("no reports yet")
        return 1
    (OUT / "index.html").write_text(f"""<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>Parliamentary briefings</title>
<link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&family=Source+Serif+4:opsz,wght@8..60,700&display=swap" rel="stylesheet">
<style>
:root{{color-scheme:light dark;--bg:light-dark(#fff,#0b1411);--ink:light-dark(#121417,#e8efeb);--mut:light-dark(#4d5752,#a9b8b0);--rule:light-dark(#d5ddd8,#24332c);--g:light-dark(#0b6b4b,#3fb487);--r:light-dark(#a2192f,#e0566c)}}
:root[data-theme=light]{{color-scheme:light}}:root[data-theme=dark]{{color-scheme:dark}}
*{{box-sizing:border-box;min-width:0}}body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 "Source Sans 3",system-ui,sans-serif}}
header{{background:#0b6b4b;color:#fff;padding:clamp(28px,5vw,60px) max(5vw,16px)}}.wrap{{max-width:1000px;margin:0 auto}}
h1,h2{{font-family:"Source Serif 4",Georgia,serif;line-height:1.1;margin:0;text-wrap:balance}}h1{{font-size:clamp(30px,4vw,44px);margin:6px 0 12px}}
.k{{margin:0;opacity:.85}}.sum{{max-width:65ch;font-size:18px;margin:0 0 20px}}
.btn{{display:inline-block;background:#fff;color:#0b6b4b;font-weight:700;padding:12px 18px;border-radius:3px;text-decoration:none}}
.badge{{display:inline-block;margin-left:10px;font-weight:700}}.badge.warn{{background:#fff;color:#a2192f;padding:4px 10px;border-radius:3px}}
main{{padding:clamp(24px,4vw,48px) max(5vw,16px)}}h2{{font-size:26px;margin-bottom:12px}}
ul{{list-style:none;margin:0;padding:0}}li{{display:flex;flex-wrap:wrap;gap:6px 16px;align-items:baseline;padding:14px 0;border-top:1px solid var(--rule)}}
li a{{flex:1 1 30em;text-decoration:none;color:var(--ink)}}li a:hover .h,li a:focus-visible .h{{color:var(--g);text-decoration:underline}}
.d{{display:block;font-size:14px;color:var(--mut)}}.h{{font-weight:700;font-size:18px}}
.s{{font-size:14px;font-weight:600;color:var(--g);white-space:nowrap}}.s.warn{{color:var(--r)}}
footer{{padding:24px max(5vw,16px);color:var(--mut);font-size:14px;border-top:1px solid var(--rule)}}
</style></head><body>
<header><div class="wrap"><p class="k">Latest briefing · {e(nice(latest["date"]))}</p><h1>{e(latest["headline"])}</h1>
<p class="sum">{e(latest["summary"])}</p><a class="btn" href="{e(latest["date"])}.html">Read the briefing</a>
<span class="badge {latest["cls"]}">{e(latest["label"])}</span></div></header>
<main><div class="wrap"><h2>All briefings</h2><ul>{"".join(rows)}</ul></div></main>
<footer><div class="wrap">Private: for Microsoft UK. Built daily at 06:00 UK time from the UK Parliament APIs; each edition is drafted by a writer agent and checked by an independent validator agent and rule checks.</div></footer>
</body></html>""")
    (OUT / "403.html").write_text("<!DOCTYPE html><html lang='en-GB'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>No access</title></head>"
                                  "<body style='font:17px system-ui;margin:10vh auto;max-width:36em;padding:0 16px'><h1>You don't have access yet</h1>"
                                  "<p>This site is private. Ask the owner to invite you to the briefing site, then sign in again with your Microsoft account.</p>"
                                  "<p><a href='/logout'>Sign out</a></p></body></html>")
    (OUT / "staticwebapp.config.json").write_text(json.dumps(SWA_CONFIG, indent=2))
    (OUT / "robots.txt").write_text("User-agent: *\nDisallow: /\n")
    (OUT / ".nojekyll").write_text("")
    print(f"site: {len(rows)} briefings")
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
