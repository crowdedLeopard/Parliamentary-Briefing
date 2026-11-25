"""Decide whether this workflow run should build today's edition.

The workflow is scheduled every 30 minutes through the early morning because GitHub's scheduler
can start runs late or drop them. Each run asks:
  1. Is today's edition already published?          -> stop, nothing to do
  2. Have scheduled builds already failed 3 times?   -> stop (each failed build has raised an alert)
  3. Is the material published yet?                  -> Hansard for every day a House sat, and the
                                                        written questions service answering
     not yet, and before WAIT_UNTIL                  -> stop; a later run will check again
     not yet, after WAIT_UNTIL                       -> build anyway; the coverage note names the gap
Days when neither House sat are built too, as a short edition that says so.
If the edition is still missing at 09:00 UK the gate sets alert=true and the workflow opens an issue.
Standard library only. Writes build/run_date/reason to $GITHUB_OUTPUT and a line to the job summary.

Usage: python pipeline/gate.py [--event schedule|workflow_dispatch] [--run-date YYYY-MM-DD]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
from sitting import any_sat, describe, questions_service_up, readiness, sitting_status, window  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
LONDON = ZoneInfo("Europe/London")
EARLIEST = time(4, 15)    # nothing before this, London time
WAIT_UNTIL = time(5, 0)   # wait for missing material until this, then build with what there is
MAX_ATTEMPTS = 3          # scheduled builds per edition before stopping
ALERT_FROM = time(9, 0)   # edition still missing at or after this: raise an alert


def decide(event: str, now: datetime, run_date: date | None = None, root: Path = ROOT,
           status_fn=sitting_status, qs_fn=questions_service_up) -> dict:
    run_date = run_date or now.date()
    f, t = window(run_date)
    out = {"build": False, "run_date": run_date.isoformat(), "edition": t, "alert": False}
    if event != "schedule":
        return out | {"build": True, "reason": f"started by hand ({event})"}
    if now.time() < EARLIEST:
        return out | {"reason": f"{now:%H:%M} London is before the {EARLIEST:%H:%M} start"}
    if (root / "reports" / f"{t}.html").exists():
        return out | {"reason": f"the edition for {t} is already published"}
    st = json.loads(p.read_text()) if (p := root / "data" / "status" / f"{t}.json").exists() else {}
    out["alert"] = now.time() >= ALERT_FROM
    if st.get("attempts", 0) >= MAX_ATTEMPTS:
        return out | {"reason": f"{st['attempts']} builds of the {t} edition failed; stopped retrying"}
    status = status_fn(f, t)
    qs_ok, _ = qs_fn(f, t)
    ready, missing = readiness(status, qs_ok)
    who = describe(status)
    if ready:
        out["alert"] = False
        kind = "material is published" if any_sat(status) else "Parliament did not sit; building the short edition"
        return out | {"build": True, "reason": f"{kind}. {who}"}
    if now.time() < WAIT_UNTIL:
        return out | {"reason": f"waiting: {'; '.join(missing)}. {who}"}
    out["alert"] = False
    return out | {"build": True, "reason": f"building with gaps after {WAIT_UNTIL:%H:%M}: {'; '.join(missing)}. {who}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--event", default=os.environ.get("EVENT", "schedule"))
    ap.add_argument("--run-date")
    a = ap.parse_args(argv)
    run_date = date.fromisoformat(a.run_date) if a.run_date else None
    d = decide(a.event, datetime.now(LONDON), run_date)
    print(json.dumps(d, indent=1))
    if gh := os.environ.get("GITHUB_OUTPUT"):
        with open(gh, "a") as fh:
            for k in ("build", "alert"):
                fh.write(f"{k}={'true' if d[k] else 'false'}\n")
            fh.write(f"run_date={d['run_date']}\nedition={d['edition']}\nreason={d['reason']}\n")
    if s := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(s, "a") as fh:
            fh.write(f"**{'Building' if d['build'] else 'Not building'}** the {d['edition']} edition: {d['reason']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
