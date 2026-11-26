# Parliamentary briefing (Copilot Cowork plugin)

Packages Hugh Milward's daily parliamentary briefing as a Copilot Cowork skill, so the scheduled task can be a one-line prompt and the full instructions live in one place that can be shared and updated.

## How it works

1. **05:00, Power Automate** ("Parliament Data Fetch Flow"): fetches written questions (answered and newly tabled) and written statements from the UK Parliament API, keeps keyword matches, fetches their full text, and saves `parliament-YYYY-MM-DD.json` to OneDrive in `Documents 1/Cowork/Parliament feed`.
2. **Weekday morning, Copilot Cowork scheduled task**: runs this skill. The skill:
   - reads the data file;
   - covers Hansard, committees, the Libraries and POST from the web;
   - previews Parliament Today;
   - screens everything through Hugh's lens;
   - emails him a formatted HTML briefing.

No connector or hosting is needed. Cowork's built-in OneDrive, web and Outlook abilities do the work.

## Contents

| File | Purpose |
|---|---|
| `skills/parliamentary-briefing/SKILL.md` | The workflow: dates, gathering order, screening, writing, delivery, schedule |
| `references/data-file.md` | The OneDrive data file: location, fields, link formats, known limits, fallback |
| `references/sources.md` | Hansard, committee, Library, What's On and business-paper sources, and the committees to check |
| `references/topics-and-lens.md` | Topics to screen for, Hugh's lens, what to skip, and how to weigh items |
| `references/briefing-format.md` | Section order, item layout, subject line and coverage note |

## Setup

1. In Copilot Cowork, open **Plugins** (or **Customize > Plugins**) and remove the earlier "Parliament tech monitor" upload.
2. Choose **Upload plugin** and select `parliamentary-briefing.zip`.
3. Test it: in a new Cowork task, ask "Run the parliamentary briefing for yesterday and show it to me here." The skill won't email anyone unless asked.
4. Replace the long scheduled prompt in **Automations** with: "Run the parliamentary briefing for the previous working day and today's Parliament Today preview, and email it to [recipient address]." Schedule it for weekdays after the flow has finished, for example 06:30.

## Changing it

- **Topics, lens or format:** edit the matching file in `references/`, re-zip and re-upload.
- **Recipients:** name them in the scheduled prompt. The skill sends to whoever the request names. The address is kept out of this repository, so put it in the scheduled prompt.
