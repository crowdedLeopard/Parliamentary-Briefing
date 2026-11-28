// Run with: npm test   (no dependencies: fakes KV and GitHub)
import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/index.js";

function kv() {
  const m = new Map();
  return { m, get: async k => (m.has(k) ? m.get(k) : null), put: async (k, v) => void m.set(k, v), delete: async k => void m.delete(k) };
}

let dispatched = [], dispatchStatus = 204;
globalThis.fetch = async (url, opt = {}) => {
  url = String(url);
  if (url.includes("api.github.com")) { dispatched.push(JSON.parse(opt.body)); return new Response(null, { status: dispatchStatus }); }
  if (url.includes("/kw/")) return new Response("", { status: url.includes("2026-11-26") ? 200 : 404 });
  throw new Error("unexpected fetch " + url);
};

const SITE = "https://site.example/briefing/";
function env(extra = {}) {
  return { REGEN: kv(), GITHUB_REPO: "o/r", GITHUB_TOKEN: "t", HOOK_SECRET: "hook-secret", USER_SALT: "salt",
           SITE_URL: SITE, DAILY_CAP: "3", ALLOWED_EMAILS: "reader@example.org, Second@Example.org,@team.example", ...extra };
}
async function call(e, path, { method = "GET", body, hook, ip = "1.2.3.4", origin = "https://site.example" } = {}) {
  const headers = { "content-type": "application/json", "cf-connecting-ip": ip, origin };
  if (hook) headers.authorization = `Bearer ${hook}`;
  const r = await worker.fetch(new Request("https://w.example" + path, { method, headers, body: body && JSON.stringify(body) }), e, {});
  const t = await r.text();
  try { return { s: r.status, j: JSON.parse(t), r }; } catch { return { s: r.status, t, r }; }
}
const ask = (e, email, k = ["sovereign cloud"], ed = "2026-11-26", ip) =>
  call(e, "/api/request", { method: "POST", body: { e: ed, k, off: [], email }, ip });

test("only listed addresses get a rewrite (exact, any case, or a listed domain)", async () => {
  const e = env();
  assert.equal((await ask(e, "stranger@example.org")).s, 403);
  assert.equal((await ask(e, "READER@example.org")).s, 200);
  assert.equal((await ask(e, "second@example.org")).s, 200);
  assert.equal((await ask(e, "anyone@team.example")).s, 200);
  assert.equal((await ask(e, "anyone@evilteam.example")).s, 403);
  assert.equal((await ask(env({ ALLOWED_EMAILS: " " }), "reader@example.org")).s, 403);   // empty list: nobody
});

test("wrong guesses are limited per network address", async () => {
  const e = env();
  for (let i = 0; i < 5; i++) assert.equal((await ask(e, `x${i}@example.org`)).s, 403);
  assert.equal((await ask(e, "reader@example.org")).s, 429);
  assert.equal((await ask(e, "reader@example.org", undefined, undefined, "5.6.7.8")).s, 200);
});

test("one rewrite per person per edition; GitHub sees only the job id; no address stored", async () => {
  const e = env(); dispatched = [];
  const a = await ask(e, "reader@example.org", ["sovereign cloud", "<b>bad</b>"]);
  assert.equal(a.s, 200);
  assert.deepEqual(dispatched.at(-1).inputs, { job: a.j.job });
  const b = await ask(e, "reader@example.org", ["other"]);
  assert.equal(b.s, 409);
  assert.equal(b.j.job, a.j.job);
  assert.equal(b.j.key, a.j.key);
  for (const [k, v] of e.REGEN.m) assert.ok(!String(k + v).includes("@"), "an address reached KV: " + k);
  assert.deepEqual(JSON.parse(e.REGEN.m.get(`job:${a.j.job}`)).keywords, ["sovereign cloud"]);
});

test("daily cap across everyone; unknown edition refused; failed dispatch refunds", async () => {
  const e = env({ DAILY_CAP: "1" });
  assert.equal((await ask(e, "reader@example.org")).s, 200);
  assert.equal((await ask(e, "second@example.org")).s, 429);
  const e2 = env();
  assert.equal((await ask(e2, "reader@example.org", ["a1"], "2020-01-01")).s, 400);
  dispatchStatus = 500;
  assert.equal((await ask(e2, "reader@example.org")).s, 502);
  dispatchStatus = 204;
  assert.equal((await ask(e2, "reader@example.org")).s, 200);
});

test("hook needs the secret; result needs the view key; a failure refunds", async () => {
  const e = env();
  const { j } = await ask(e, "reader@example.org", ["cloud"]);
  assert.equal((await call(e, `/hook/job/${j.job}`, { hook: "wrong" })).s, 401);
  const spec = await call(e, `/hook/job/${j.job}`, { hook: "hook-secret" });
  assert.deepEqual(spec.j, { edition: "2026-11-26", keywords: ["cloud"], off: [] });
  assert.equal((await call(e, `/api/job/${j.job}?key=${j.key}`)).j.status, "running");
  assert.equal((await call(e, `/api/job/${j.job}?key=nope`)).s, 404);
  await call(e, `/hook/job/${j.job}`, { method: "POST", hook: "hook-secret", body: { status: "done", html: "<p>hi</p>", title: "T" } });
  const st = await call(e, `/api/job/${j.job}?key=${j.key}`);
  assert.equal(st.j.status, "done");
  assert.equal(st.j.uid, undefined);
  assert.equal(st.j.key, undefined);
  const page = await call(e, `/r/${j.job}?key=${j.key}`);
  assert.equal(page.t, "<p>hi</p>");
  assert.match(page.r.headers.get("content-security-policy"), /sandbox/);
  assert.equal((await call(e, `/r/${j.job}`)).s, 404);

  const e2 = env();
  const r2 = await ask(e2, "reader@example.org", ["cloud"]);
  await call(e2, `/hook/job/${r2.j.job}`, { method: "POST", hook: "hook-secret", body: { status: "failed", error: "boom" } });
  assert.equal((await ask(e2, "reader@example.org", ["cloud"])).s, 200);
});

test("unlimited addresses skip the per-person limit", async () => {
  const e = env({ UNLIMITED_EMAILS: "reader@example.org" });
  assert.equal((await ask(e, "reader@example.org", ["a1"])).s, 200);
  assert.equal((await ask(e, "reader@example.org", ["a2"])).s, 200);
});

test("the API answers the site's origin only", async () => {
  const e = env();
  const ok = await call(e, "/api/status");
  assert.equal(ok.r.headers.get("access-control-allow-origin"), "https://site.example");
  const other = await call(e, "/api/status", { origin: "https://evil.example" });
  assert.equal(other.r.headers.get("access-control-allow-origin"), null);
});

test("with a mail sender set, a rewrite needs the emailed code (one use, five tries)", async () => {
  const mail = [];
  const e = env({ EMAIL: { send: async m => { mail.push(m); return { messageId: "m1" }; } }, EMAIL_FROM: "briefing@site.example" });
  assert.equal((await call(e, "/api/code", { method: "POST", body: { email: "stranger@example.org" } })).s, 403);
  assert.equal(mail.length, 0);
  assert.equal((await ask(e, "reader@example.org")).s, 401);                     // no code yet
  const c = await call(e, "/api/code", { method: "POST", body: { email: "reader@example.org" } });
  assert.deepEqual(c.j, { needCode: true, sent: true });
  assert.equal(mail[0].to, "reader@example.org");
  const code = mail[0].subject.match(/\d{6}/)[0];
  const wrong = code === "000000" ? "111111" : "000000";
  const bad = await call(e, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["cloud"], email: "reader@example.org", code: wrong } });
  assert.equal(bad.s, 401);
  const good = await call(e, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["cloud"], email: "reader@example.org", code } });
  assert.equal(good.s, 200);
  for (const [k, v] of e.REGEN.m) assert.ok(!String(k + v).includes(code), "the code was stored in clear");
  const again = await call(e, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["cloud"], email: "second@example.org", code } });
  assert.equal(again.s, 401);                                                    // not that person's code
});

test("without a mail sender, no code is asked for", async () => {
  const c = await call(env(), "/api/code", { method: "POST", body: { email: "reader@example.org" } });
  assert.deepEqual(c.j, { needCode: false });
});

test("a personal access code in the list must match; entries without one need only the address", async () => {
  const e = env({ ALLOWED_EMAILS: "ann@example.org:river-lamp-42, reader@example.org" });
  const c = await call(e, "/api/code", { method: "POST", body: { email: "ann@example.org" } });
  assert.deepEqual(c.j, { needCode: true, personal: true });
  const req = code => call(e, "/api/request", { method: "POST", body: { e: "2026-11-26", k: ["cloud"], email: "Ann@example.org", code } });
  assert.equal((await req("")).s, 401);
  assert.equal((await req("river-lamp-41")).s, 401);
  assert.equal((await req("river-lamp-42")).s, 200);
  assert.equal((await ask(e, "reader@example.org")).s, 200);
  for (const [k, v] of e.REGEN.m) assert.ok(!String(k + v).includes("river"), "a code reached KV");
});

test("an entry marked :unlimited skips the per-person limit but keeps its own daily guard", async () => {
  const e = env({ ALLOWED_EMAILS: "ann@example.org:river-lamp-42:unlimited, reader@example.org", DAILY_CAP: "1", UNLIMITED_CAP: "3" });
  const req = (k, code = "river-lamp-42") => call(e, "/api/request", { method: "POST", body: { e: "2026-11-26", k: [k], email: "ann@example.org", code } });
  assert.equal((await req("a1", "river-lamp-42:unlimited")).s, 401);   // the flag is not part of the code
  assert.equal((await req("a1")).s, 200);
  assert.equal((await req("a2")).s, 200);
  assert.equal((await req("a3")).s, 200);
  assert.equal((await req("a4")).s, 429);
  assert.equal((await ask(e, "reader@example.org")).s, 200);           // others still share DAILY_CAP
  assert.equal((await ask(e, "reader@example.org", ["xy"])).s, 409);
});
