"""Daily run: feed -> member profiles -> (optional AI reads) -> HTML report.

Usage: python pipeline/run.py [--run-date YYYY-MM-DD] [--render-only]
Writes, for the last day covered (toDate):
  data/feed/parliament-<toDate>.json      same shape as the old Power Automate file
  data/profiles/<toDate>.json             one evidence profile per asking member
  reports/<toDate>.html                   the briefing page
Editorial sections are merged from editorial/<toDate>.json when present.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

from analysis import add_reads  # noqa: E402
from api import Api  # noqa: E402
from feed import build_feed, window  # noqa: E402
from members import build_profiles  # noqa: E402
from render import render  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-date", help="Briefing date (UK); default today")
    ap.add_argument("--render-only", action="store_true", help="Re-render from saved data")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    run_date = date.fromisoformat(a.run_date) if a.run_date else datetime.now(ZoneInfo("Europe/London")).date()
    _, to_date = window(run_date)

    feed_path = ROOT / "data/feed" / f"parliament-{to_date}.json"
    prof_path = ROOT / "data/profiles" / f"{to_date}.json"
    for p in (feed_path, prof_path):
        p.parent.mkdir(parents=True, exist_ok=True)

    if a.render_only:
        feed = json.loads(feed_path.read_text())
        profiles = json.loads(prof_path.read_text())
    else:
        api = Api()
        try:
            feed = build_feed(api, run_date)
            feed_path.write_text(json.dumps(feed, ensure_ascii=False, indent=1))
            logging.info("feed: %d questions screened, %d matched, %d statements matched, %d API calls",
                         feed["questionsScanned"], len(feed["writtenQuestions"]), len(feed["writtenStatements"]), api.calls)
            profiles = build_profiles(api, feed, run_date, ROOT / "data/members")
            reads = add_reads(profiles, {q.get("uin"): q for q in feed["writtenQuestions"]})
            logging.info("profiles: %d (%d with AI reads)", len(profiles), reads)
            prof_path.write_text(json.dumps(profiles, ensure_ascii=False, indent=1))
        finally:
            api.close()

    ed_path = ROOT / "editorial" / f"{to_date}.json"
    editorial = json.loads(ed_path.read_text()) if ed_path.exists() else None
    out = ROOT / "reports" / f"{to_date}.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(render(feed, profiles, editorial, run_date))
    (ROOT / "reports" / "latest.html").write_text(out.read_text())
    logging.info("report: %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
