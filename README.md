# Parliamentary briefing

A daily briefing on UK Parliament activity relevant to Microsoft, for Hugh Milward (VP UK & Ireland, CELA). It replaces the suspended "Parliament Data Fetch Flow" in Power Automate and adds a profile of every member who asked a relevant question.

> **Before relying on this daily:** the Power Automate flow was suspended by organisational policy. This Action does the same job from GitHub's cloud. Confirm with the policy owner that running it here is acceptable.

## What runs, and when

The **Daily parliamentary briefing** GitHub Action starts at **04:32 UK time every day**, so the briefing is built and validated before the page refreshes just before 06:00. GitHub's timer uses UTC, so the workflow fires at both 03:32 and 04:32 UTC and only the run that lands at 04:xx London time goes ahead. That covers both GMT and BST. GitHub can start scheduled runs late. A run takes roughly 15–30 minutes. You can also run it by hand from the Actions tab, for a past date or in another mode (see below).

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
   4. **AI classifier** (`pipeline/semantic.py`, default Claude Haiku 5.5 via GitHub Copilot): reads every question the first three layers missed, flags anything plausibly relevant and gives a reason.
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
5. **Writer agent** (`pipeline/agents.py`, default Claude Opus 5.5 via GitHub Copilot) drafts the editorial sections to Hugh's brief:
   - headline and summary;
   - very important items;
   - Parliament Today;
   - debates, questions, committees and other sources;
   - coverage notes;
   - a "likely drivers" note for every member.

   It works only from the evidence above.
6. **Validator agent** (default GPT-6.1 Sol via GitHub Copilot: a separate call to a model from a different vendor, so it does not share the writer's blind spots) checks every claim in the draft against the same evidence: names, parties, numbers, dates, quotes and links. It corrects or removes anything unsupported and returns a log of its changes. The report header shows the verdict, and the coverage note lists every correction.
7. **Renders** `reports/<date>.html` (and `reports/latest.html`). It also prints a reading-edition PDF, `reports/<date>.pdf` and `reports/latest.pdf`: the briefing plus compact member profiles, without the full question list. OneDrive previews PDFs but won't render HTML. Everything is then committed back to the repo. The report is also attached to each run as a downloadable artifact.

**The validator is mandatory.** Rule checks (`pipeline/checks.py`) run every time. They confirm every link is an official Parliament page, every UIN quoted exists in the data, and every member's party matches the Members API. If the AI validator does not run (Copilot unreachable, or three failed attempts), fails, or the rule checks find a problem, the run is marked failed so GitHub emails the repo owner, and the briefing and website are labelled **Not validated**. To change the models, set the repository variables `WRITER_MODEL`, `VALIDATOR_MODEL` and `CLASSIFIER_MODEL`.

### Models: GitHub Copilot

All three agents run on GitHub Copilot's models through the Copilot CLI (`pipeline/llm.py`), which the workflow installs. (GitHub Models, the old HTTP inference API, was retired on 30 July 2026, so the CLI is the supported route from Actions.) Each call runs in an empty scratch folder: the task and evidence go in as files, and Copilot may read them and write `output.json`, with shell, web and memory tools denied.

| Role | Default, best first (falls back if a model isn't on the account) | Reasoning effort |
|---|---|---|
| Writer | `claude-opus-5.5`, `claude-fable-5.1`, `claude-sonnet-5`, `gpt-6.1-sol` | high |
| Validator | `gpt-6.1-sol`, `gpt-6-sol`, `claude-opus-5.5`, `claude-sonnet-5` (never the writer's model unless nothing else answers) | high |
| Classifier | `claude-haiku-5.5`, `gpt-5-mini`, `claude-haiku-4.5` | low |

Each variable takes a comma-separated list. If a model reports "not available", enable it for the token's account at github.com/settings/copilot (Claude Opus 5.5 needs enabling there). The validation log records which model actually ran, and the report warns if the validator had to fall back to the writer's model. `REASONING_EFFORT` overrides the effort. Set `MODEL_PROVIDER=anthropic` (with `ANTHROPIC_API_KEY`) to use the Anthropic API instead.

**Authentication.** The run first tries a `COPILOT_GITHUB_TOKEN` secret, then the run's own `GITHUB_TOKEN` (the workflow grants `copilot-requests: write`; in a personal repository usage is billed to the owner's Copilot seat). The most reliable option is the secret: a fine-grained personal access token with the **Copilot Requests** permission, created by an account with a Copilot seat. Before the briefing runs, a preflight step pings each model and fails loudly if the writer or validator can't be reached.

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

## Website (public GitHub Pages)

Every run publishes the website to GitHub Pages: the latest briefing at the top, then the archive with each edition's validation status. It is **public to anyone with the link**. Pages carry `noindex` and the site has a `robots.txt` that blocks crawlers, so it should not appear in search results, but treat the link as shareable, not secret. The run log prints the address as a notice; it is normally `https://crowdedleopard.github.io/Parliamentary-Briefing/`.

One-off setup: **Settings > Pages > Build and deployment > Source: GitHub Actions**. This repository is private, so GitHub Pages needs a paid plan on the owning account (GitHub Pro, Team or Enterprise); on GitHub Free the option is offered only for public repositories. To stop publishing, set the repository variable `PAGES_DISABLED` to `true`.

For a site that needs a Microsoft sign-in instead, add the `AZURE_STATIC_WEB_APPS_API_TOKEN` secret: the same job then also deploys to Azure Static Web Apps, using `staticwebapp.config.json` to admit only invited users.

## Getting it into OneDrive

OneDrive and SharePoint download HTML files rather than display them, so the OneDrive copy is the PDF. Power Automate's standard GitHub connector has no action that downloads a file, so it can't do the copy. Two routes that do work:

- **Scheduled `git pull` on a PC.** No scripts needed: create a sparse clone of `reports/` inside a OneDrive folder, then add a Windows Task Scheduler job at 06:45 running `git.exe` with the arguments `-C "<that folder>" pull --ff-only`. Share the folder with Hugh.
  ```
  git clone --filter=blob:none --sparse https://github.com/crowdedLeopard/Parliamentary-Briefing.git "%OneDriveCommercial%\Parliament briefing"
  git -C "%OneDriveCommercial%\Parliament briefing" sparse-checkout set reports
  ```
- **Direct upload from the Action.** Needs an Entra app registration with OneDrive or SharePoint write permission, approved by IT. Ask and this step can be added.

## Copilot Cowork

`cowork-plugin/` is a skill-only Cowork plugin, so there is no connector to host. It writes and emails Hugh's briefing from the feed file, Hansard, committees and What's On. Zip the folder's contents and upload it in Cowork under **Customize > Plugins**.

Cowork still needs a way to read `data/feed/`, for example:
- a GitHub connector in Cowork; or
- a permitted Power Automate flow that copies the day's file to OneDrive using the standard GitHub and OneDrive connectors rather than the blocked HTTP action.

## Setup checklist

1. Add the `COPILOT_GITHUB_TOKEN` repository secret: a fine-grained personal access token with the **Copilot Requests** permission (github.com/settings/personal-access-tokens/new). **Required** unless the run's own `GITHUB_TOKEN` gets Copilot access: without one of them no edition can pass validation.
1. Invite Hugh: **Settings > Collaborators > Add people**, and to the website (see Private website).
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
