// Regenerate service for the parliamentary briefing: a Cloudflare Worker.
//
// The visitor presses "Rewrite" on a briefing page and types their email address. The Worker
// checks it against ALLOWED_EMAILS. The owner keeps that list only as the GitHub secret
// REGEN_ALLOWED_EMAILS; deploy-worker.yml copies it into this Worker as an encrypted secret. It is
// never in the repository, the logs or the site. Entries are
// addresses, or "@domain" to allow a whole domain. An address that is not on the list gets no
// rewrite. Addresses are never stored: the Worker keeps only a keyed hash (USER_SALT) to enforce
// one rewrite per person per edition (LIMIT_SCOPE=edition) or one ever (LIMIT_SCOPE=ever), plus a
// hard daily cap across everyone (DAILY_CAP). Wrong guesses are limited per network address.
//
// Flow:  page -> POST /api/request {e, k, off, email} -> job saved in KV -> GitHub workflow
//        "regenerate.yml" started with only the job id -> it fetches the job from /hook/job/<id>
//        (HOOK_SECRET), rewrites the edition and posts the page back -> the visitor's page polls
//        /api/job/<id>?key=<view key> and opens /r/<id>?key=<view key>. Results are kept RESULT_DAYS.
//
// Bindings (wrangler.toml): KV namespace REGEN.
// Vars: GITHUB_REPO, SITE_URL (its origin is the only one allowed to call the API), DAILY_CAP,
//       LIMIT_SCOPE, RESULT_DAYS.
// Secrets: ALLOWED_EMAILS (copied from the GitHub secret REGEN_ALLOWED_EMAILS), GITHUB_TOKEN (fine-grained,
//          Actions read/write on GITHUB_REPO only), HOOK_SECRET (shared with the workflow),
//          USER_SALT (random, made once), UNLIMITED_EMAILS (optional: addresses with no per-person limit).

const TERM = /^[\p{L}\p{N} .&'’\-]{2,40}$/u;
const EDITION = /^\d{4}-\d{2}-\d{2}$/;
const JOB_ID = /^[A-Za-z0-9_-]{8,64}$/;
const EMAIL = /^[^\s@,;<>"]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,}$/;
const STUCK_MS = 50 * 60 * 1000;
const MAX_MISSES = 5; // wrong addresses per network address per hour
const enc = new TextEncoder();

export default {
  async fetch(req, env, ctx) {
    const cors = corsHeaders(req, env);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    let res;
    try {
      res = await route(req, env, ctx);
    } catch (e) {
      if (e instanceof Reply) res = e.res;
      else {
        console.log("error", e && e.message); // never the request body
        res = json({ error: "Something went wrong. Please try again later." }, 500);
      }
    }
    if (new URL(req.url).pathname.startsWith("/api/")) for (const [k, v] of Object.entries(cors)) res.headers.set(k, v);
    return res;
  },
};

class Reply { constructor(res) { this.res = res; } }
const fail = (status, error, more = {}) => { throw new Reply(json({ error, ...more }, status)); };

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" } });
}

function corsHeaders(req, env) {
  const origin = req.headers.get("origin") || "";
  let allowed = "";
  try { allowed = new URL(env.SITE_URL).origin; } catch { /* not set */ }
  return origin && origin === allowed
    ? { "access-control-allow-origin": origin, "access-control-allow-methods": "GET, POST, OPTIONS",
        "access-control-allow-headers": "content-type", "access-control-max-age": "600", vary: "origin" }
    : { vary: "origin" };
}

async function route(req, env) {
  const url = new URL(req.url);
  const p = url.pathname;

  // ---- the workflow's side
  const hook = p.match(/^\/hook\/job\/([A-Za-z0-9_-]{8,64})$/);
  if (hook) {
    await hookAuth(req, env);
    const job = await getJob(env, hook[1]);
    if (!job) fail(404, "no such job");
    if (req.method === "GET") {
      if (job.status === "queued") { job.status = "running"; job.updated = Date.now(); await putJob(env, job); }
      return json({ edition: job.edition, keywords: job.keywords, off: job.off });
    }
    if (req.method === "POST") {
      const body = await req.json().catch(() => ({}));
      if (job.status === "done") return json({ ok: true }); // the first result wins
      if (body.status === "done" && typeof body.html === "string" && body.html.length < 4_000_000) {
        await env.REGEN.put(`res:${job.id}`, body.html, { expirationTtl: days(env) * 86400 });
        Object.assign(job, { status: "done", updated: Date.now(), title: str(body.title, 200), headline: str(body.headline, 400) });
      } else {
        Object.assign(job, { status: "failed", updated: Date.now(), error: str(body.error, 300) || "The rewrite failed." });
        await refund(env, job);
      }
      await putJob(env, job);
      return json({ ok: true });
    }
    fail(405, "method not allowed");
  }

  // ---- the visitor's side
  if (p === "/" && req.method === "GET") {
    return new Response("This service rewrites briefings on request. Use the Tune keywords panel on a briefing page.",
                        { headers: { "content-type": "text/plain; charset=utf-8", "x-robots-tag": "noindex" } });
  }

  if (p === "/api/status" && req.method === "GET") {
    const today = Number(await env.REGEN.get(dayKey())) || 0;
    return json({ scope: scope(env), dailyLeft: Math.max(0, cap(env) - today) });
  }

  if (p === "/api/request" && req.method === "POST") {
    if (req.headers.get("content-type")?.split(";")[0] !== "application/json") fail(415, "send JSON");
    const body = await req.json().catch(() => fail(400, "bad request"));
    const email = String(body.email || "").trim().toLowerCase();
    const edition = String(body.e || "");
    if (!EDITION.test(edition)) fail(400, "Unknown edition.");
    const keywords = [...new Set((Array.isArray(body.k) ? body.k : []).map(x => String(x).replace(/\s+/g, " ").trim()).filter(x => TERM.test(x)))].slice(0, 12);
    const off = (Array.isArray(body.off) ? body.off : []).map(x => String(x).slice(0, 80)).slice(0, 20);
    if (!keywords.length && !off.length) fail(400, "Choose at least one keyword or switch off a topic.");

    // Who: the address must be on the owner's list. Wrong guesses are limited per network address.
    const ip = await hmac(env.USER_SALT, "ip:" + (req.headers.get("cf-connecting-ip") || "unknown"));
    const mk = `miss:${ip}:${new Date().toISOString().slice(0, 13)}`;
    const misses = Number(await env.REGEN.get(mk)) || 0;
    if (misses >= MAX_MISSES) fail(429, "Too many attempts. Please try again in an hour.");
    if (!EMAIL.test(email) || !listed(env.ALLOWED_EMAILS, email)) {
      await env.REGEN.put(mk, String(misses + 1), { expirationTtl: 3700 });
      fail(403, "That address is not on the list for rewrites.");
    }
    if (!(await editionExists(env, edition))) fail(400, "That edition is not on the site.");
    const uid = await hmac(env.USER_SALT, email);
    const unlimited = listed(env.UNLIMITED_EMAILS, email);

    const uk = usedKey(env, uid, edition);
    if (!unlimited) {
      const prev = await env.REGEN.get(uk);
      if (prev) {
        const old = await getJob(env, prev);
        fail(409, "You have already used your rewrite" + (scope(env) === "ever" ? "." : " for this edition."),
             old ? { job: old.id, key: old.key } : {});
      }
    }
    const dk = dayKey();
    const today = Number(await env.REGEN.get(dk)) || 0;
    if (today >= cap(env)) fail(429, "Today's limit on rewrites has been reached. Please try again tomorrow.");

    const id = rand(16), key = rand(24);
    const job = { id, key, uid, edition, keywords, off, status: "queued", created: Date.now(), updated: Date.now() };
    await putJob(env, job);
    // Claim the allowance before starting, so two quick clicks cannot both run.
    if (!unlimited) await env.REGEN.put(uk, id, scope(env) === "ever" ? {} : { expirationTtl: 40 * 86400 });
    await env.REGEN.put(dk, String(today + 1), { expirationTtl: 2 * 86400 });

    const r = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/actions/workflows/regenerate.yml/dispatches`, {
      method: "POST",
      headers: {
        authorization: `Bearer ${env.GITHUB_TOKEN}`, accept: "application/vnd.github+json",
        "x-github-api-version": "2022-11-28", "user-agent": "briefing-regen-worker", "content-type": "application/json",
      },
      body: JSON.stringify({ ref: "main", inputs: { job: id } }),
    });
    if (r.status !== 204) {
      console.log("dispatch failed", r.status);
      Object.assign(job, { status: "failed", error: "The rewrite could not be started.", updated: Date.now() });
      await putJob(env, job);
      await refund(env, job);
      await env.REGEN.put(dk, String(today), { expirationTtl: 2 * 86400 });
      fail(502, "The rewrite could not be started. Your allowance has not been used.");
    }
    return json({ job: id, key });
  }

  const jm = p.match(/^\/api\/job\/([A-Za-z0-9_-]{8,64})$/);
  if (jm && req.method === "GET") {
    const job = await keyedJob(env, jm[1], url.searchParams.get("key"));
    if ((job.status === "queued" || job.status === "running") && Date.now() - job.created > STUCK_MS) {
      Object.assign(job, { status: "failed", error: "The rewrite took too long and was stopped.", updated: Date.now() });
      await putJob(env, job);
      await refund(env, job);
    }
    const { uid, key, ...pub } = job;
    return json(pub);
  }

  const rm = p.match(/^\/r\/([A-Za-z0-9_-]{8,64})$/);
  if (rm && req.method === "GET") {
    await keyedJob(env, rm[1], url.searchParams.get("key"));
    const html = await env.REGEN.get(`res:${rm[1]}`);
    if (!html) return new Response("This rewrite is not ready or has expired.", { status: 404 });
    return new Response(html, {
      headers: {
        "content-type": "text/html; charset=utf-8", "cache-control": "private, no-store", "referrer-policy": "no-referrer",
        // shown as a document only: no scripts, no forms
        "content-security-policy": "sandbox allow-popups allow-popups-to-escape-sandbox; default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src data:",
        "x-robots-tag": "noindex",
      },
    });
  }

  return new Response("Not found", { status: 404 });
}

// ---------------------------------------------------------------------------------------------

function listed(list, email) {
  const domain = email.slice(email.lastIndexOf("@"));
  return String(list || "").split(/[\s,;]+/).map(s => s.trim().toLowerCase()).filter(Boolean)
    .some(x => x === email || (x.startsWith("@") && x === domain));
}

async function hookAuth(req, env) {
  const got = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!env.HOOK_SECRET || !(await same(got, env.HOOK_SECRET))) fail(401, "unauthorised");
}

const scope = env => (env.LIMIT_SCOPE === "ever" ? "ever" : "edition");
const cap = env => Math.max(0, Number(env.DAILY_CAP) || 10);
const days = env => Math.min(60, Math.max(1, Number(env.RESULT_DAYS) || 14));
const usedKey = (env, uid, edition) => (scope(env) === "ever" ? `used:${uid}` : `used:${uid}:${edition}`);
const dayKey = () => `day:${new Date().toISOString().slice(0, 10)}`;
const str = (s, n) => (typeof s === "string" ? s.slice(0, n) : "");
const rand = n => [...crypto.getRandomValues(new Uint8Array(n))].map(b => b.toString(16).padStart(2, "0")).join("");

async function getJob(env, id) {
  if (!JOB_ID.test(id)) return null;
  return JSON.parse((await env.REGEN.get(`job:${id}`)) || "null");
}
async function putJob(env, job) {
  await env.REGEN.put(`job:${job.id}`, JSON.stringify(job), { expirationTtl: days(env) * 86400 });
}
async function keyedJob(env, id, key) {
  const job = await getJob(env, id);
  if (!job || !key || !(await same(key, job.key))) fail(404, "No such rewrite.");
  return job;
}
async function refund(env, job) {
  const k = usedKey(env, job.uid, job.edition);
  if ((await env.REGEN.get(k)) === job.id) await env.REGEN.delete(k);
}
async function editionExists(env, edition) {
  if (!env.SITE_URL) return true;
  const r = await fetch(new URL(`kw/${edition}.json`, env.SITE_URL), { method: "HEAD" });
  return r.ok;
}
async function hmac(secret, text) {
  if (!secret) fail(500, "The service is not set up yet.");
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(text)));
  return [...sig.slice(0, 16)].map(b => b.toString(16).padStart(2, "0")).join("");
}
async function same(a, b) {
  const [x, y] = await Promise.all([a, b].map(s => crypto.subtle.digest("SHA-256", enc.encode(String(s)))));
  const u = new Uint8Array(x), v = new Uint8Array(y);
  let d = 0;
  for (let i = 0; i < u.length; i++) d |= u[i] ^ v[i];
  return d === 0;
}
