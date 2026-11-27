# Regenerate service

Every briefing page has a **Tune keywords** panel. Re-screening the day's material on your own
keywords happens in the browser and costs nothing. **Rewrite with these keywords** asks an AI writer
to redraft the edition around them. That costs model time, so it is gated:

1. The visitor types their email address and presses the button. The page sends it, with the
   keywords, to this small Cloudflare Worker (`src/index.js`). A static GitHub Pages site cannot
   hold the token that starts a workflow, so this relay is the one piece that has to live elsewhere.
2. The Worker checks the address against the approved list. **The list is kept only as the GitHub
   secret `REGEN_ALLOWED_EMAILS`**; `deploy-worker.yml` copies it into the Worker's encrypted
   secrets on every deploy and daily. It is never in the repository, the logs or the site. An
   address not on the list gets no rewrite, and wrong guesses are limited to 5 an hour per network.
3. Addresses are never stored. The Worker keeps a keyed hash to allow **one rewrite per person per
   edition** (`LIMIT_SCOPE = "ever"` for one in total), with a **daily cap across everyone**
   (`DAILY_CAP`, default 10). A failed rewrite gives the allowance back.
4. It starts the separate workflow `regenerate.yml` with only an opaque job id, so the public run
   log shows no keywords and nothing about who asked. The workflow fetches the job from
   `/hook/job/<id>` (shared secret), rewrites the edition with the same writer as the daily build
   (GitHub Copilot) and posts the page back. Nothing is committed.
5. The page waits and then links to the result, which only holds a private link and is kept 14 days.

The address check on its own proves only that someone knows an approved address, not that they own
it; the one-per-person limit and the daily cap bound what a guesser could spend. To make visitors
prove it, turn on **emailed codes**: onboard a domain you have on Cloudflare DNS under Email Service >
Email Sending, then set the repository variable `REGEN_EMAIL_FROM` (e.g. `briefing@yourdomain`) and
deploy. Each rewrite then needs a six-digit code sent to the address (10 minutes, one use, five
tries, three codes an hour). On the free Workers plan Cloudflare only mails addresses verified in
the account first; the paid plan lifts that. With `REGEN_EMAIL_FROM` blank, no code is asked for.

## Set-up

All in GitHub (Settings > Secrets and variables > Actions), apart from one Cloudflare token:

| Kind | Name | Value |
|---|---|---|
| secret | `CLOUDFLARE_API_TOKEN` | Cloudflare > My Profile > API Tokens > Create Token > *Edit Cloudflare Workers* template |
| secret | `CLOUDFLARE_ACCOUNT_ID` | the Cloudflare account id |
| secret | `REGEN_ALLOWED_EMAILS` | approved addresses, comma-separated; `@example.com` allows a whole domain. Add `:code` after an address (`ann@example.org:river-lamp-42`) to give that person their own access code, which they must type too |
| secret | `REGEN_UNLIMITED_EMAILS` | optional: addresses with no per-person limit |
| secret | `REGEN_DISPATCH_TOKEN` | fine-grained GitHub token, this repository only, *Actions: read and write* |
| secret | `REGEN_HOOK_SECRET` | a long random string |
| variable | `REGEN_URL` | the Worker's address, once deployed |

Then run **Deploy the regenerate service** (it creates the Worker `briefing-regen` and its storage,
and prints nothing secret), set `REGEN_URL`, and rebuild the site so the pages get the rewrite box.
After editing the list, run the deploy again (or wait for the daily run).

Optional: `REGEN_VALIDATE=true` (variable) also runs the independent validator on each rewrite, at
about twice the model cost.

## Tests

`npm test` (no dependencies; fakes KV and GitHub, and checks no address is ever stored).
`node test/serve-local.mjs 8787 http://localhost:8765/` runs a local stand-in for trying the page.
