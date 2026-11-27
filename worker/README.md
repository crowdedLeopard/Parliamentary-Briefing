# Regenerate service

Every briefing page has a **Tune keywords** panel. Re-screening the day's material on your own
keywords happens in the browser and costs nothing. **Rewrite with these keywords** asks an AI writer
to redraft the edition around them. That costs model time, so it goes through this service:

1. The visitor opens the service's page. **Cloudflare Access** asks them to sign in (a one-time code
   by email). Only addresses in the Access policy get through. **The list of approved addresses lives
   only in Cloudflare**, never in this repository, its secrets, its logs or the site.
2. The Worker (`src/index.js`) checks Access's signature, turns the address into a private keyed hash
   (the address itself is never stored), and allows **one rewrite per person per edition** (set
   `LIMIT_SCOPE = "ever"` for one in total), with a **daily cap across everyone** (`DAILY_CAP`).
3. It starts the separate GitHub workflow `regenerate.yml`, passing only an opaque job id, so the
   public run log shows no keywords and nothing about who asked.
4. The workflow fetches the job from `/hook/job/<id>`, rewrites the edition with the same writer as
   the daily build (GitHub Copilot), and posts the page back. Nothing is committed.
5. The visitor's page shows the result. Only the person who asked can see it; it is kept 14 days.
   If a rewrite fails, the person's allowance is given back.

## Set-up

In Cloudflare:

1. **API token**: My Profile > API Tokens > Create Token > *Edit Cloudflare Workers* template.
   Save it as the GitHub secret `CLOUDFLARE_API_TOKEN`, and the account id as `CLOUDFLARE_ACCOUNT_ID`.
2. Run the **Deploy the regenerate service** workflow once. It creates the Worker `briefing-regen`
   and its KV store. Note its address, `https://briefing-regen.<your-subdomain>.workers.dev`.
3. **Access**: Workers & Pages > briefing-regen > Settings > Domains & Routes > workers.dev >
   *Enable Cloudflare Access*. Then, in Zero Trust > Access > Applications > that application:
   - add a policy that **allows** the readers' emails (or an email domain). This is the only place
     they are kept;
   - create a **service token** (Access > Service credentials), and add a second policy with action
     *Service Auth* that includes it. The rewrite workflow uses it to reach `/hook/`;
   - copy the **Application Audience (AUD) tag** and your team domain (`<team>.cloudflareaccess.com`).

In GitHub (Settings > Secrets and variables > Actions):

| Kind | Name | Value |
|---|---|---|
| variable | `REGEN_URL` | the Worker's address |
| variable | `ACCESS_AUD` | the AUD tag |
| variable | `ACCESS_TEAM_DOMAIN` | `<team>.cloudflareaccess.com` |
| secret | `REGEN_HOOK_SECRET` | a long random string |
| secret | `REGEN_DISPATCH_TOKEN` | fine-grained token, this repository only, *Actions: read and write* |
| secret | `CF_ACCESS_CLIENT_ID`, `CF_ACCESS_CLIENT_SECRET` | the service token |

Then run **Deploy the regenerate service** again, and the daily build (or any rebuild of the site)
to add the rewrite button to the pages.

Optional: `REGEN_VALIDATE=true` (variable) also runs the independent validator on each rewrite, at
about twice the model cost. To exempt yourself from the one-rewrite limit, open
`<REGEN_URL>/api/me` while signed in, copy the `you` value (a hash, not your address) and add it to
the Worker secret `UNLIMITED` (comma-separated).

## Tests

`npm test` (no dependencies). The tests fake Access, KV and GitHub, and check that no address is
ever stored.
