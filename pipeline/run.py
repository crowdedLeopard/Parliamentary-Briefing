"""Daily run: feed -> member profiles -> sources -> writer agent -> validator agent -> HTML report.

Usage: python pipeline/run.py [--run-date YYYY-MM-DD] [--mode full|validate|render] [--scheduled]
  full      fetch everything, write (unless an editorial exists) and validate, render   (default)
  validate  reuse saved data; re-gather sources; validate the existing editorial; render
  render    re-render from saved data and editorial only
  --scheduled  exit quietly unless it is 04:xx in London (the workflow fires at 03:32 and
               04:32 UTC so that one of them is 04:32 UK time in both GMT and BST; the
               briefing is then ready well before the page refresh just before 06:00)
Writes, for the last day covered (toDate):
  data/feed/parliament-<toDate>.json, data/profiles/<toDate>.json, data/sources/<toDate>.json,
  editorial/<toDate>.json, editorial/<toDate>.validation.json, reports/<toDate>.html, reports/latest.html
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

from agents import write_and_validate  # noqa: E402
from api import Api  # noqa: E402
from checks import run_checks  # noqa: E402
from feed import build_feed, window  # noqa: E402
from members import build_profiles  # noqa: E402
from render import render  # noqa: E402
from sources import gather  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LONDON = ZoneInfo("Europe/London")


def jload(p: Path):
    return json.loads(p.read_text()) if p.exists() else None


def jsave(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-date", help="Briefing date (UK); default today")
    ap.add_argument("--mode", choices=["full", "validate", "render"], default="full")
    ap.add_argument("--scheduled", action="store_true")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    now = datetime.now(LONDON)
    if a.scheduled and now.hour != 4:
        logging.info("Scheduled trigger at %s London time: not 04:xx, nothing to do.", now.strftime("%H:%M"))
        return 0
    run_date = date.fromisoformat(a.run_date) if a.run_date else now.date()
    from_date, to_date = window(run_date)
    paths = {k: ROOT / v for k, v in {
        "feed": f"data/feed/parliament-{to_date}.json", "profiles": f"data/profiles/{to_date}.json",
        "sources": f"data/sources/{to_date}.json", "editorial": f"editorial/{to_date}.json",
        "validation": f"editorial/{to_date}.validation.json", "report": f"reports/{to_date}.html"}.items()}

    if a.mode == "full":
        api = Api()
        try:
            feed = build_feed(api, run_date)
            jsave(paths["feed"], feed)
            logging.info("feed: %d screened, %d questions and %d statements matched", feed["questionsScanned"],
                         len(feed["writtenQuestions"]), len(feed["writtenStatements"]))
            profiles = build_profiles(api, feed, run_date, ROOT / "data/members")
            jsave(paths["profiles"], profiles)
            logging.info("profiles: %d", len(profiles))
        finally:
            api.close()
    else:
        feed, profiles = jload(paths["feed"]), jload(paths["profiles"])
        if feed is None or profiles is None:
            logging.error("No saved data for %s; run --mode full first.", to_date)
            return 1

    editorial, validation = jload(paths["editorial"]), jload(paths["validation"])
    if a.mode in ("full", "validate"):
        sources = gather(from_date, to_date, run_date.isoformat())
        jsave(paths["sources"], sources)
        editorial, validation = write_and_validate(feed, profiles, sources, run_date.isoformat(), draft=editorial)
        if editorial is not None:
            jsave(paths["editorial"], editorial)
        if validation is not None:
            jsave(paths["validation"], validation)

    # Rule-based checks always run, with or without the AI validator.
    rules = run_checks(editorial, feed, profiles)
    validation = dict(validation or {"verdict": "not run", "error": "AI validator did not run (no model could be reached: check the Copilot token)",
                                     "checked": 0, "fixes": [], "removed": []})
    validation["ruleChecks"] = rules
    if editorial is not None:
        jsave(paths["validation"], validation)

    html = render(feed, profiles, editorial, run_date, validation)
    paths["report"].parent.mkdir(exist_ok=True)
    paths["report"].write_text(html)
    (ROOT / "reports" / "latest.html").write_text(html)
    logging.info("report: %s", paths["report"])

    # The validator is mandatory: fail the run (so GitHub notifies) if it did not pass.
    ok = validation.get("verdict") in ("pass", "pass_with_fixes") and not rules["issues"]
    if editorial is not None and not ok:
        logging.error("VALIDATION NOT PASSED: verdict=%s, rule issues=%d. The report is marked unvalidated.",
                      validation.get("verdict"), len(rules["issues"]))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
