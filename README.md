# Parliamentary briefing

A daily briefing on UK Parliament activity relevant to Microsoft, for the reader. It replaces the suspended "Parliament Data Fetch Flow" in Power Automate and adds a profile of every member who asked a relevant question.

> **Before relying on this daily:** the Power Automate flow was suspended by organisational policy. This Action does the same job from GitHub's cloud. Confirm with the policy owner that running it here is acceptable.

## What runs, and when

The **Daily parliamentary briefing** GitHub Action runs at 04:07 UTC on weekdays (05:07 during British Summer Time). You can also run it by hand from the Actions tab, optionally for a past date. Each run:

1. **Fetches** written questions answered or tabled in the previous working day (on a Monday: Friday to Sunday), split by House, plus written ministerial statements. The Parliament API is slow (10–40 seconds per request), so the client uses long timeouts and retries. A GitHub runner has no 15-second limit, unlike Copilot Cowork's web access.
2. **Screens** the *full* text of every question and answer against the topic list in `pipeline/topics.py`. Parliament's list endpoint cuts text off at about 255 characters, so the old flow only screened the start of each answer. On 23 November 2026, screening the full text found 102 matches where the cut-off text found 65.
3. **Profiles** every member who asked a matching question. Each profile is built from Parliament's public record and includes:
   - party, seat and when they joined Parliament;
   - current committees and posts;
   - registered interests that touch tech or data;
   - self-declared policy focus;
   - 12 months of their written questions, screened for the same topics;
   - rule-based "signals", each tied to its evidence;
   - links to their record.

   Member data is cached for 7 days in `data/members/`.
4. **Optionally adds a "likely drivers" note** to each profile, in two or three sentences, if the `ANTHROPIC_API_KEY` repository secret is set. The model sees only the gathered evidence and must mark anything it infers.
5. **Renders** `reports/<date>.html` (and `reports/latest.html`) and commits everything back to the repo. The report is also attached to each run as a downloadable artifact.

## Outputs

| Path | Contents |
|---|---|
| `data/feed/parliament-<date>.json` | Same shape as the old flow's file (`generatedUtc`, `fromDate`, `toDate`, `questionsScanned`, `writtenQuestions`, `writtenStatements`), plus `warnings`, `counts` and each item's `matched` topics |
| `data/profiles/<date>.json` | One evidence profile per asking member |
| `reports/<date>.html` | The briefing page. Download it and open it in a browser. |

`<date>` is the last day covered.

## Editorial sections

Written questions, statements and profiles come from the pipeline. The judgement-heavy sections come from `editorial/<date>.json` when someone writes one: headlines, Parliament Today, debates and committees. That someone could be a person, or the Copilot Cowork skill in `cowork-plugin/`. To add or refresh them, commit the JSON and re-run the Action with **render only** ticked. See `editorial/2026-11-23.json` for the format.

## Copilot Cowork

`cowork-plugin/` is a skill-only Cowork plugin, so there is no connector to host. It writes and emails the reader's briefing from the feed file, Hansard, committees and What's On. Zip the folder's contents and upload it in Cowork under **Customize > Plugins**.

Cowork still needs a way to read `data/feed/`, for example:
- a GitHub connector in Cowork; or
- a permitted Power Automate flow that copies the day's file to OneDrive using the standard GitHub and OneDrive connectors rather than the blocked HTTP action.

## Setup checklist

1. Invite the reader: **Settings > Collaborators > Add people**.
2. Optional: **Settings > Secrets and variables > Actions > New repository secret**, `ANTHROPIC_API_KEY`, to enable the "likely drivers" notes.
3. Check that **Actions** are enabled, then run **Daily parliamentary briefing** once by hand.

## Principles

- **Public record only.** Profiles use Parliament's official data about members' public roles. Nothing about private lives.
- **Evidence before inference.** Every signal names its source. Inferences are labelled "likely" or "appears".
- **Neutral.** The briefing describes what members asked and ministers answered, not their politics.

## Development

```bash
pip install -r requirements.txt pytest
pytest -q tests                                     # offline, uses a fake API
python pipeline/run.py --run-date 2026-11-24        # live run (needs normal internet access)
python pipeline/run.py --run-date 2026-11-24 --render-only
```
