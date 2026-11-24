# Parliamentary briefing

A daily briefing on UK Parliament activity relevant to Microsoft, for Hugh Milward (VP UK & Ireland, CELA). It replaces the suspended "Parliament Data Fetch Flow" in Power Automate and adds a profile of every member who asked a relevant question.

> **Before relying on this daily:** the Power Automate flow was suspended by organisational policy. This Action does the same job from GitHub's cloud. Confirm with the policy owner that running it here is acceptable.

## What runs, and when

The **Daily parliamentary briefing** GitHub Action runs at **06:00 UK time every day**. GitHub's timer uses UTC, so the workflow fires at both 05:02 and 06:02 UTC and only the run that lands at 06:xx London time goes ahead. That covers both GMT and BST. GitHub can start scheduled runs a few minutes late. A run takes roughly 10–20 minutes. You can also run it by hand from the Actions tab, for a past date or in another mode (see below).

Each run:

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
4. **Gathers sources** (`pipeline/sources.py`): relevant Hansard passages from both Houses, with speaker, debate and link; today's What's On for the Commons, Lords and committees; and the period's committee publications. Pages that can't be read are recorded as gaps.
5. **Writer agent** (`pipeline/agents.py`, default `claude-sonnet-5-5`) drafts the editorial sections to Hugh's brief:
   - headline and summary;
   - very important items;
   - Parliament Today;
   - debates, questions, committees and other sources;
   - coverage notes;
   - a "likely drivers" note for every member.

   It works only from the evidence above.
6. **Validator agent** (default `claude-opus-5-5`, a separate call to a separate model) checks every claim in the draft against the same evidence: names, parties, numbers, dates, quotes and links. It corrects or removes anything unsupported and returns a log of its changes. The report header shows the verdict, and the coverage note lists every correction.
7. **Renders** `reports/<date>.html` (and `reports/latest.html`) and commits everything back to the repo. The report is also attached to each run as a downloadable artifact.

Steps 5 and 6 need the `ANTHROPIC_API_KEY` repository secret. Without it, the report still has the data sections and profiles, and its header says it has not been validated. To change the models, set the repository variables `WRITER_MODEL` and `VALIDATOR_MODEL`.

**Manual modes** (Actions > Daily parliamentary briefing > Run workflow):
- `full` runs everything.
- `validate` reuses the saved data, re-gathers sources and validates the existing editorial. Use it after a person has written or edited one.
- `render` re-renders only.

## Outputs

| Path | Contents |
|---|---|
| `data/feed/parliament-<date>.json` | Same shape as the old flow's file (`generatedUtc`, `fromDate`, `toDate`, `questionsScanned`, `writtenQuestions`, `writtenStatements`), plus `warnings`, `counts` and each item's `matched` topics |
| `data/profiles/<date>.json` | One evidence profile per asking member |
| `reports/<date>.html` | The briefing page. Download it and open it in a browser. |

`<date>` is the last day covered.

## Editorial sections

`editorial/<date>.json` holds the writer's sections. Its validation log sits beside it as `<date>.validation.json`. If an editorial already exists for a date, for example one a person wrote, the writer is skipped and the validator checks that version instead. See `editorial/2026-11-23.json` for the format. That edition was written by hand in the session that built this repository, before the agents were enabled, so it has not yet been through the validator.

## Copilot Cowork

`cowork-plugin/` is a skill-only Cowork plugin, so there is no connector to host. It writes and emails Hugh's briefing from the feed file, Hansard, committees and What's On. Zip the folder's contents and upload it in Cowork under **Customize > Plugins**.

Cowork still needs a way to read `data/feed/`, for example:
- a GitHub connector in Cowork; or
- a permitted Power Automate flow that copies the day's file to OneDrive using the standard GitHub and OneDrive connectors rather than the blocked HTTP action.

## Setup checklist

1. Invite Hugh: **Settings > Collaborators > Add people**.
2. **Settings > Secrets and variables > Actions > New repository secret**: add `ANTHROPIC_API_KEY` to turn on the writer and validator agents.
3. Check that **Actions** are enabled, then run **Daily parliamentary briefing** once by hand.

## Principles

- **Public record only.** Profiles use Parliament's official data about members' public roles. Nothing about private lives.
- **Evidence before inference.** Every signal names its source. Inferences are labelled "likely" or "appears".
- **Neutral.** The briefing describes what members asked and ministers answered, not their politics.

## Development

```bash
pip install -r requirements.txt pytest
pytest -q tests                                     # offline: fake Parliament API and fake model API
python pipeline/run.py --run-date 2026-11-24        # live run (needs normal internet access)
python pipeline/run.py --run-date 2026-11-24 --mode render
```
