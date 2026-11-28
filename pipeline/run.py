"""Daily run: feed -> member profiles -> sources -> writer agent -> validator agent -> HTML report.

Usage: python pipeline/run.py [--run-date YYYY-MM-DD] [--mode full|validate|render] [--scheduled]
  full      fetch everything, write (unless an editorial exists) and validate, render   (default)
  validate  reuse saved data; re-gather sources; validate the existing editorial; render
  render    re-render from saved data and editorial only
  --scheduled  accepted for compatibility; whether to build is now decided by pipeline/gate.py
               (the workflow's gate job), which checks the edition is missing and the material
               is published before this script runs
Writes, for the last day covered (toDate):
  data/feed/parliament-<toDate>.json, data/profiles/<toDate>.json, data/sources/<toDate>.json,
  editorial/<toDate>.json, editorial/<toDate>.validation.json, reports/<toDate>.html, reports/latest.html,
  data/status/<toDate>.json (attempts, outcome, and which days each House sat),
  data/corpus/<toDate>.json (every question and statement read) and data/keywords/<toDate>.json (suggested keywords)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))

from agents import write_and_validate  # noqa: E402
from api import Api  # noqa: E402
from checks import run_checks  # noqa: E402
from feed import build_feed, window  # noqa: E402
from members import build_profiles  # noqa: E402
from render import render  # noqa: E402
from sitting import any_sat, describe, readiness, sitting_status  # noqa: E402
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
    run_date = date.fromisoformat(a.run_date) if a.run_date else now.date()
    from_date, to_date = window(run_date)
    paths = {k: ROOT / v for k, v in {
        "feed": f"data/feed/parliament-{to_date}.json", "profiles": f"data/profiles/{to_date}.json",
        "sources": f"data/sources/{to_date}.json", "editorial": f"editorial/{to_date}.json",
        "validation": f"editorial/{to_date}.validation.json", "report": f"reports/{to_date}.html",
        "status": f"data/status/{to_date}.json"}.items()}
    status = jload(paths["status"]) or {"edition": to_date, "attempts": 0}
    status.update(runDate=run_date.isoformat(), state="building", attempts=status.get("attempts", 0) + 1,
                  startedUtc=datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    jsave(paths["status"], status)
    try:
        code, status = build(a, run_date, from_date, to_date, paths, status)
    except Exception:
        status["state"] = "failed"
        raise
    finally:
        status["finishedUtc"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        jsave(paths["status"], status)
    return code


def build(a, run_date: date, from_date: str, to_date: str, paths: dict, status: dict) -> tuple[int, dict]:

    if a.mode == "full":
        api = Api()
        try:
            feed = build_feed(api, run_date)
            corpus = feed.pop("corpus", None)
            jsave(paths["feed"], feed)
            if corpus:
                import keywords
                jsave(ROOT / f"data/corpus/{to_date}.json", keywords.compact_corpus(corpus))
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
            status["state"] = "failed"
            return 1, status

    editorial, validation = jload(paths["editorial"]), jload(paths["validation"])
    if a.mode in ("full", "validate"):
        sources = gather(from_date, to_date, run_date.isoformat())
        # Which days each House sat, and whether their Hansard is published: stated plainly in the
        # report, and any Hansard still missing is recorded as a gap in the coverage note.
        sitting = sitting_status(from_date, to_date)
        _, missing = readiness(sitting, True)
        sitting["summary"] = describe(sitting)
        sitting["anySat"] = any_sat(sitting)
        sources["sitting"] = sitting
        sources.setdefault("gaps", []).extend(f"{m} (checked {datetime.now(LONDON):%H:%M} UK time)" for m in missing)
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

    # Keyword suggestions for the page's keyword picker: mined from everything read, ranked by a
    # small model where one is available. Never fatal: the page falls back to the mined list.
    if a.mode == "full":
        try:
            import keywords
            jsave(ROOT / f"data/keywords/{to_date}.json", keywords.suggest(ROOT, to_date, use_ai=True))
        except Exception as e:  # noqa: BLE001
            logging.warning("keyword suggestions failed: %s", e)

    sitting = (jload(paths["sources"]) or {}).get("sitting")
    html = render(feed, profiles, editorial, run_date, validation, sitting=sitting)
    paths["report"].parent.mkdir(exist_ok=True)
    paths["report"].write_text(html)
    (ROOT / "reports" / "latest.html").write_text(html)
    logging.info("report: %s", paths["report"])

    # The validator is mandatory: fail the run (so GitHub notifies) if it did not pass.
    ok = validation.get("verdict") in ("pass", "pass_with_fixes") and not rules["issues"]
    status.update(state="published" if ok else "published_unvalidated", sitting=(sitting or {}).get("summary"),
                  questionsMatched=len(feed["writtenQuestions"]), statementsMatched=len(feed["writtenStatements"]),
                  questionsScanned=feed["questionsScanned"])
    if editorial is not None and not ok:
        logging.error("VALIDATION NOT PASSED: verdict=%s, rule issues=%d. The report is marked unvalidated.",
                      validation.get("verdict"), len(rules["issues"]))
        return 2, status
    return 0, status


if __name__ == "__main__":
    raise SystemExit(main())
