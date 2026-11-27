// Run with: node --test test/   (no dependencies: fakes KV, GitHub and Cloudflare Access)
import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

const TEAM = "example.cloudflareaccess.com";
const AUD = "aud-123";
const kp = await crypto.subtle.generateKey(
  { name: "RSASSA-PKCS1-v1_5", modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: "SHA-256" }, true, ["sign", "verify"]);
const jwk = { ...(await crypto.subtle.exportKey("jwk", kp.publicKey)), kid: "k1", alg: "RS256" };
const b64 = b => Buffer.from(b).toString("base64url");

async function jwt(claims) {
  const h = b64(JSON.stringify({ alg: "RS256", kid: "k1" }));
  const p = b64(JSON.stringify({ aud: [AUD], iss: `https://${TEAM}`, exp: Math.floor(Date.now() / 1000) + 600, ...claims }));
  const s = await crypto.subtle.sign("RSASSA-PKCS1-v1_5", kp.privateKey, new TextEncoder().encode(`${h}.${p}`));
  return `${h}.${p}.${b64(s)}`;
}

function kv() {
  const m = new Map();
  return { m, get: async k => (m.has(k) ? m.get(k) : null), put: async (k, v) => void m.set(k, v), delete: async k => void m.delete(k) };
}

let dispatched = [], dispatchStatus = 204;
globalThis.fetch = async (url, opt = {}) => {
  url = String(url);
  if (url.endsWith("/cdn-cgi/access/certs")) return new Response(JSON.stringify({ keys: [jwk] }));
  if (url.includes("api.github.com")) { dispatched.push(JSON.parse(opt.body)); return new Response(null, { status: dispatchStatus }); }
  if (url.includes("/kw/")) return new Response("", { status: url.includes("2026-11-26") ? 200 : 404 });
  throw new Error("unexpected fetch " + url);
};

function env(extra = {}) {
  return { REGEN: kv(), ACCESS_TEAM_DOMAIN: TEAM, ACCESS_AUD: AUD, GITHUB_REPO: "o/r", GITHUB_TOKEN: "t",
           HOOK_SECRET: "hook-secret", USER_SALT: "salt", SITE_URL: "https://site.example/", DAILY_CAP: "3", ...extra };
}
async function call(e, path, { method = "GET", body, email = "reader@example.org", token, hook } = {}) {
  const headers = { "content-type": "application/json" };
  if (email !== null) headers["cf-access-jwt-assertion"] = token || (await jwt({ email }));
  if (hook) headers.authorization = `Bearer ${hook}`;
  const r = await worker.fetch(new Request("https://w.example" + path, { method, headers, body: body && JSON.stringify(body) }), e, {});
  const t = await r.text();
  try { return { s: r.status, j: JSON.parse(t), r }; } catch { return { s: r.status, t, r }; }
}

test("no Access token, no entry", async () => {
  const e = env();
  assert.equal((await call(e, "/api/me?e=2026-11-26", { email: null })).s, 401);
  const forged = (await jwt({ email: "x@y.z" })).replace(/\.[^.]+$/, ".AAAA");
  assert.equal((await call(e, "/api/me", { token: forged })).s, 401);
  const wrongAud = await jwt({ email: "x@y.z", aud: ["other"] });
  assert.equal((await call(e, "/api/me", { token: wrongAud })).s, 401);
});

test("one rewrite per person per edition, and no email is stored", async () => {
  const e = env(); dispatched = [];
  const a = await call(e, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["sovereign cloud", "<b>bad</b>"], off: [] } });
  assert.equal(a.s, 200);
  assert.equal(dispatched.length, 1);
  assert.deepEqual(dispatched[0].inputs, { job: a.j.job });          // GitHub sees only the job id
  const b = await call(e, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["other"] } });
  assert.equal(b.s, 409);
  assert.equal(b.j.job, a.j.job);
  const other = await call(e, "/api/request", { method: "POST", email: "someone@example.org", body: { e: "2026-11-26", k: ["x1"] } });
  assert.equal(other.s, 200);
  for (const [k, v] of e.REGEN.m) assert.ok(!String(k + v).includes("@"), "an address reached KV: " + k);
  const job = JSON.parse(e.REGEN.m.get(`job:${a.j.job}`));
  assert.deepEqual(job.keywords, ["sovereign cloud"]);              // the bad keyword was dropped
});

test("daily cap across everyone", async () => {
  const e = env({ DAILY_CAP: "1" });
  assert.equal((await call(e, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["a1"] } })).s, 200);
  assert.equal((await call(e, "/api/request", { method: "POST", email: "b@example.org", body: { e: "2026-11-26", k: ["a1"] } })).s, 429);
});

test("unknown edition refused; failed dispatch gives the allowance back", async () => {
  const e = env();
  assert.equal((await call(e, "/api/request", { method: "POST", body: { e: "2020-01-01", k: ["a1"] } })).s, 400);
  dispatchStatus = 500;
  assert.equal((await call(e, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["a1"] } })).s, 502);
  dispatchStatus = 204;
  assert.equal((await call(e, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["a1"] } })).s, 200);
});

test("hook: needs the secret; result shown only to its owner; failure refunds", async () => {
  const e = env();
  const { j } = await call(e, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["cloud"] } });
  assert.equal((await call(e, `/hook/job/${j.job}`, { email: null, hook: "wrong" })).s, 401);
  const spec = await call(e, `/hook/job/${j.job}`, { email: null, hook: "hook-secret" });
  assert.deepEqual(spec.j, { edition: "2026-11-26", keywords: ["cloud"], off: [] });
  assert.equal((await call(e, `/api/job/${j.job}`)).j.status, "running");
  await call(e, `/hook/job/${j.job}`, { method: "POST", email: null, hook: "hook-secret", body: { status: "done", html: "<p>hi</p>", title: "T" } });
  const mine = await call(e, `/api/job/${j.job}`);
  assert.equal(mine.j.status, "done");
  assert.equal(mine.j.uid, undefined);
  const page = await call(e, `/r/${j.job}`);
  assert.equal(page.t, "<p>hi</p>");
  assert.match(page.r.headers.get("content-security-policy"), /sandbox/);
  assert.equal((await call(e, `/r/${j.job}`, { email: "intruder@example.org" })).s, 404);

  const e2 = env();
  const r2 = await call(e2, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["cloud"] } });
  await call(e2, `/hook/job/${r2.j.job}`, { method: "POST", email: null, hook: "hook-secret", body: { status: "failed", error: "boom" } });
  assert.equal((await call(e2, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["cloud"] } })).s, 200);
});

test("owner exemption by hash", async () => {
  const e = env();
  const me = await call(e, "/api/me?e=2026-11-26");
  e.UNLIMITED = me.j.you;
  assert.equal((await call(e, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["a1"] } })).s, 200);
  assert.equal((await call(e, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["a2"] } })).s, 200);
});

test("the page itself renders", async () => {
  const r = await call(env(), "/");
  assert.equal(r.s, 200);
  assert.match(r.t, /Rewrite a briefing/);
});
