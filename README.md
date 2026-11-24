# Parliamentary briefing

A daily briefing on UK Parliament activity relevant to Microsoft, for the reader. It replaces the suspended "Parliament Data Fetch Flow" in Power Automate and adds a profile of every member who asked a relevant question.

> **Before relying on this daily:** the Power Automate flow was suspended by organisational policy. This Action does the same job from GitHub's cloud. Confirm with the policy owner that running it here is acceptable.

## What runs, and when

The **Daily parliamentary briefing** GitHub Action runs at **06:00 UK time every day**. GitHub's timer uses UTC, so the workflow fires at both 05:02 and 06:02 UTC and only the run that lands at 06:xx London time goes ahead. That covers both GMT and BST. GitHub can start scheduled runs a few minutes late. A run takes roughly 10–20 minutes. You can also run it by hand from the Actions tab, for a past date or in another mode (see below).

Each run:

1. **Fetches** written questions answered or tabled in the previous working day (on a Monday: Friday to Sunday), split by House, plus written ministerial statements. The Parliament API is slow (10–40 seconds per request), so the client uses long timeouts and retries. A GitHub runner has no 15-second limit, unlike Copilot Cowork's web access.
2. **Screens** the *full* text of every question and answer with four layers, designed so nothing relevant is missed. Parliament's list endpoint cuts text off at about 255 characters, so the old flow only screened the start of each answer; on 23 November 2026, full-text screening found 102 matches where the cut-off text found 65. Each item records which layer caught it (`matchedBy`), and the counts per layer are in the feed's `layers` field.
   1. **Keyword rules** (`pipeline/topics.py`): about 400 terms across 11 topics. They cover:
      - Microsoft products and competitors;
      - procurement frameworks;
      - regulators and bodies;
      - spelling and hyphen variants;
      - ambiguous words, matched only in a technology context.

      Names that are also ordinary words (Apple, Meta, STEM) are matched case-sensitively.
   2. **Departments:** every question to DSIT, plus digital, data and IT questions to the Cabinet Office, DCMS, DBT, DESNZ, MHCLG, HMT, the Home Office, DHSC and DfE.
   3. **Watchlist:** every question from members who consistently drive these issues (`WATCH_MEMBERS`).
   4. **AI classifier** (`pipeline/semantic.py`, default `claude-haiku-5-5`): reads every question the first three layers missed, flags anything plausibly relevant and gives a reason.
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
5. **Writer agent** (`pipeline/agents.py`, default `claude-sonnet-5-5`) drafts the editorial sections to the reader's brief:
   - headline and summary;
   - very important items;
   - Parliament Today;
   - debates, questions, committees and other sources;
   - coverage notes;
   - a "likely drivers" note for every member.

   It works only from the evidence above.
6. **Validator agent** (default `claude-opus-5-5`, a separate call to a separate model) checks every claim in the draft against the same evidence: names, parties, numbers, dates, quotes and links. It corrects or removes anything unsupported and returns a log of its changes. The report header shows the verdict, and the coverage note lists every correction.
7. **Renders** `reports/<date>.html` (and `reports/latest.html`). It also prints a reading-edition PDF, `reports/<date>.pdf` and `reports/latest.pdf`: the briefing plus compact member profiles, without the full question list. OneDrive previews PDFs but won't render HTML. Everything is then committed back to the repo. The report is also attached to each run as a downloadable artifact.

**The validator is mandatory.** Rule checks (`pipeline/checks.py`) run every time. They confirm every link is an official Parliament page, every UIN quoted exists in the data, and every member's party matches the Members API. If the AI validator does not run (no `ANTHROPIC_API_KEY`, or three failed attempts), fails, or the rule checks find a problem, the run is marked failed so GitHub emails the repo owner, and the briefing and website are labelled **Not validated**. To change the models, set the repository variables `WRITER_MODEL`, `VALIDATOR_MODEL` and `CLASSIFIER_MODEL`.

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

## Private website

After each run, the `site` job builds `_site/`: a front page with the latest briefing and an archive of every past day, each linking to its full report. It deploys only to targets that are set up as private:

- **Azure Static Web Apps.** Recommended: the easiest to share inside Microsoft.
  1. Create a Static Web App (Free plan) in an approved Azure subscription.
  2. Copy its deployment token into the repository secret `AZURE_STATIC_WEB_APPS_API_TOKEN`.
  3. In the Azure portal, go to **Role management > Invite**. Invite the reader (and anyone else) by Microsoft email address with the role `briefing`.

  Viewers sign in with their Microsoft account. Anyone not invited sees a "no access" page, enforced by `staticwebapp.config.json`. To open it to the whole Microsoft tenant without invitations, move to the Standard plan and configure a custom Entra ID provider restricted to the tenant.
- **Private GitHub Pages.** Only possible in a GitHub Enterprise Cloud organisation, and every viewer needs read access to the repository.
  1. Move the repo into the organisation.
  2. Go to **Settings > Pages**, set the source to *GitHub Actions* and the visibility to *Private*.
  3. Only then set the repository variable `PAGES_PRIVATE_CONFIRMED` to `true`. Until that variable is set, the workflow never publishes to Pages, so nothing can go out publicly by accident.

## Getting it into OneDrive

OneDrive and SharePoint download HTML files rather than display them, so the OneDrive copy is the PDF. Power Automate's standard GitHub connector has no action that downloads a file, so it can't do the copy. Two routes that do work:

- **Scheduled `git pull` on a PC.** No scripts needed: create a sparse clone of `reports/` inside a OneDrive folder, then add a Windows Task Scheduler job at 06:45 running `git.exe` with the arguments `-C "<that folder>" pull --ff-only`. Share the folder with the reader.
  ```
  git clone --filter=blob:none --sparse https://github.com/crowdedLeopard/Parliamentary-Briefing.git "%OneDriveCommercial%\Parliament briefing"
  git -C "%OneDriveCommercial%\Parliament briefing" sparse-checkout set reports
  ```
- **Direct upload from the Action.** Needs an Entra app registration with OneDrive or SharePoint write permission, approved by IT. Ask and this step can be added.

## Copilot Cowork

`cowork-plugin/` is a skill-only Cowork plugin, so there is no connector to host. It writes and emails the reader's briefing from the feed file, Hansard, committees and What's On. Zip the folder's contents and upload it in Cowork under **Customize > Plugins**.

Cowork still needs a way to read `data/feed/`, for example:
- a GitHub connector in Cowork; or
- a permitted Power Automate flow that copies the day's file to OneDrive using the standard GitHub and OneDrive connectors rather than the blocked HTTP action.

## Setup checklist

1. Add the `ANTHROPIC_API_KEY` repository secret. **Required**: without it no edition can pass validation.
1. Invite the reader: **Settings > Collaborators > Add people**, and to the website (see Private website).
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
