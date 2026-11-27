// Regenerate service for the parliamentary briefing: a Cloudflare Worker behind Cloudflare Access.
//
// Who may ask is decided only by the Cloudflare Access policy on this Worker: the approved email
// addresses live there and nowhere else. This code never stores or sends an address. It turns the
// signed-in address into a keyed hash (USER_SALT) and uses that alone to enforce one rewrite per
// person per edition (LIMIT_SCOPE=edition) or one ever (LIMIT_SCOPE=ever), plus a hard daily cap
// across everyone (DAILY_CAP).
//
// Flow:  visitor (signed in by Access) -> POST /api/request -> job saved in KV -> GitHub workflow
//        "regenerate.yml" started with only the job id -> it fetches the job from /hook/job/<id>,
//        rewrites the edition and posts the page back -> visitor's page polls /api/job/<id> and
//        shows the result from /r/<id>. Results are kept for RESULT_DAYS and shown only to the
//        person who asked.
//
// Bindings (wrangler.toml): KV namespace REGEN.
// Vars: GITHUB_REPO, ACCESS_TEAM_DOMAIN, ACCESS_AUD, SITE_URL, DAILY_CAP, LIMIT_SCOPE, RESULT_DAYS.
// Secrets: GITHUB_TOKEN (fine-grained, Actions read/write on GITHUB_REPO only), HOOK_SECRET (shared
//          with the workflow), USER_SALT (random), UNLIMITED (optional: comma-separated user hashes
//          exempt from the per-person limit, e.g. the owner's; see /api/me for your own hash).

const TERM = /^[\p{L}\p{N} .&'’\-]{2,40}$/u;
const EDITION = /^\d{4}-\d{2}-\d{2}$/;
const JOB_ID = /^[A-Za-z0-9_-]{8,64}$/;
const STUCK_MS = 50 * 60 * 1000;
const enc = new TextEncoder();

export default {
  async fetch(req, env, ctx) {
    try {
      return await route(req, env, ctx);
    } catch (e) {
      if (e instanceof Reply) return e.res;
      console.log("error", e && e.message);
      return json({ error: "Something went wrong. Please try again later." }, 500);
    }
  },
};

class Reply { constructor(res) { this.res = res; } }
const fail = (status, error) => { throw new Reply(json({ error }, status)); };

function json(obj, status = 200, extra = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": "no-store", ...extra },
  });
}

async function route(req, env, ctx) {
  const url = new URL(req.url);
  const p = url.pathname;

  // ---- the workflow's side (shared secret; the path can also sit behind an Access service token)
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
      if (job.status === "done") return json({ ok: true }); // first result wins
      if (body.status === "done" && typeof body.html === "string" && body.html.length < 4_000_000) {
        const ttl = days(env) * 86400;
        await env.REGEN.put(`res:${job.id}`, body.html, { expirationTtl: ttl });
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

  // ---- the visitor's side: everything needs a signed-in person
  const me = await identify(req, env);

  if (p === "/" && req.method === "GET") return page(env);

  if (p === "/api/me" && req.method === "GET") {
    const e = url.searchParams.get("e") || "";
    const used = EDITION.test(e) ? await env.REGEN.get(usedKey(env, me.uid, e)) : null;
    const today = Number(await env.REGEN.get(dayKey())) || 0;
    return json({
      you: me.uid, unlimited: me.unlimited, scope: scope(env), usedJob: me.unlimited ? null : used,
      dailyLeft: Math.max(0, cap(env) - today), site: env.SITE_URL || "",
    });
  }

  if (p === "/api/request" && req.method === "POST") {
    if (req.headers.get("content-type")?.split(";")[0] !== "application/json") fail(415, "send JSON");
    const body = await req.json().catch(() => fail(400, "bad request"));
    const edition = String(body.e || "");
    if (!EDITION.test(edition)) fail(400, "Unknown edition.");
    const keywords = [...new Set((Array.isArray(body.k) ? body.k : []).map(x => String(x).replace(/\s+/g, " ").trim()).filter(x => TERM.test(x)))].slice(0, 12);
    const off = (Array.isArray(body.off) ? body.off : []).map(x => String(x).slice(0, 80)).slice(0, 20);
    if (!keywords.length && !off.length) fail(400, "Choose at least one keyword or switch off a topic.");
    if (!(await editionExists(env, edition))) fail(400, "That edition is not on the site.");

    const uk = usedKey(env, me.uid, edition);
    if (!me.unlimited) {
      const prev = await env.REGEN.get(uk);
      if (prev) return json({ error: "You have already used your rewrite" + (scope(env) === "ever" ? "." : " for this edition."), job: prev }, 409);
    }
    const dk = dayKey();
    const today = Number(await env.REGEN.get(dk)) || 0;
    if (today >= cap(env)) fail(429, "Today's limit on rewrites has been reached. Please try again tomorrow.");

    const id = crypto.randomUUID().replace(/-/g, "");
    const job = { id, uid: me.uid, edition, keywords, off, status: "queued", created: Date.now(), updated: Date.now() };
    await putJob(env, job);
    // Claim the allowance before starting, so two quick clicks cannot both run.
    if (!me.unlimited) await env.REGEN.put(uk, id, scope(env) === "ever" ? {} : { expirationTtl: 40 * 86400 });
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
    return json({ job: id });
  }

  const jm = p.match(/^\/api\/job\/([A-Za-z0-9_-]{8,64})$/);
  if (jm && req.method === "GET") {
    const job = await ownJob(env, me, jm[1]);
    if ((job.status === "queued" || job.status === "running") && Date.now() - job.created > STUCK_MS) {
      Object.assign(job, { status: "failed", error: "The rewrite took too long and was stopped.", updated: Date.now() });
      await putJob(env, job);
      await refund(env, job);
    }
    const { uid, ...pub } = job;
    return json(pub);
  }

  const rm = p.match(/^\/r\/([A-Za-z0-9_-]{8,64})$/);
  if (rm && req.method === "GET") {
    await ownJob(env, me, rm[1]);
    const html = await env.REGEN.get(`res:${rm[1]}`);
    if (!html) return new Response("This rewrite is not available (it may have expired).", { status: 404 });
    return new Response(html, {
      headers: {
        "content-type": "text/html; charset=utf-8", "cache-control": "private, no-store",
        // the page is shown as a document only: no scripts, no forms
        "content-security-policy": "sandbox allow-popups allow-popups-to-escape-sandbox; default-src 'none'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src data:",
        "x-robots-tag": "noindex",
      },
    });
  }

  return new Response("Not found", { status: 404 });
}

// ---------------------------------------------------------------------------------------------
// Identity: Cloudflare Access signs every request it lets through. Check that signature here too,
// so the Worker is never usable without Access in front of it.

let certCache = null;
async function accessClaims(req, env) {
  const token = req.headers.get("cf-access-jwt-assertion");
  if (!token || !env.ACCESS_TEAM_DOMAIN || !env.ACCESS_AUD) fail(401, "Sign-in is required.");
  const [h, pl, sig] = token.split(".");
  if (!sig) fail(401, "Sign-in is required.");
  const header = JSON.parse(b64text(h));
  const claims = JSON.parse(b64text(pl));
  const team = env.ACCESS_TEAM_DOMAIN.replace(/^https?:\/\//, "").replace(/\/$/, "");
  if (!certCache || certCache.exp < Date.now()) {
    const r = await fetch(`https://${team}/cdn-cgi/access/certs`);
    certCache = { keys: (await r.json()).keys || [], exp: Date.now() + 3600_000 };
  }
  const jwk = certCache.keys.find(k => k.kid === header.kid);
  if (!jwk || header.alg !== "RS256") fail(401, "Sign-in is required.");
  const key = await crypto.subtle.importKey("jwk", jwk, { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" }, false, ["verify"]);
  const ok = await crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, b64bytes(sig), enc.encode(`${h}.${pl}`));
  const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (!ok || !aud.includes(env.ACCESS_AUD) || claims.exp * 1000 < Date.now() || claims.iss !== `https://${team}`) fail(401, "Sign-in is required.");
  return claims;
}

async function identify(req, env) {
  const claims = await accessClaims(req, env);
  if (!claims.email) fail(403, "This page is for people, not services.");
  const uid = await hmac(env.USER_SALT, String(claims.email).trim().toLowerCase());
  const unlimited = String(env.UNLIMITED || "").split(",").map(s => s.trim()).filter(Boolean).includes(uid);
  return { uid, unlimited };
}

async function hookAuth(req, env) {
  const got = (req.headers.get("authorization") || "").replace(/^Bearer\s+/i, "");
  if (!env.HOOK_SECRET || !(await same(got, env.HOOK_SECRET))) fail(401, "unauthorised");
}

// ---------------------------------------------------------------------------------------------

const scope = env => (env.LIMIT_SCOPE === "ever" ? "ever" : "edition");
const cap = env => Math.max(0, Number(env.DAILY_CAP) || 10);
const days = env => Math.min(60, Math.max(1, Number(env.RESULT_DAYS) || 14));
const usedKey = (env, uid, edition) => (scope(env) === "ever" ? `used:${uid}` : `used:${uid}:${edition}`);
const dayKey = () => `day:${new Date().toISOString().slice(0, 10)}`;
const str = (s, n) => (typeof s === "string" ? s.slice(0, n) : "");

async function getJob(env, id) {
  if (!JOB_ID.test(id)) return null;
  return JSON.parse((await env.REGEN.get(`job:${id}`)) || "null");
}
async function putJob(env, job) {
  await env.REGEN.put(`job:${job.id}`, JSON.stringify(job), { expirationTtl: days(env) * 86400 });
}
async function ownJob(env, me, id) {
  const job = await getJob(env, id);
  if (!job || job.uid !== me.uid) fail(404, "No such rewrite.");
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
  if (!secret) fail(500, "The service is not set up yet (USER_SALT).");
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(text)));
  return [...sig.slice(0, 16)].map(b => b.toString(16).padStart(2, "0")).join("");
}
async function same(a, b) {
  const [x, y] = await Promise.all([a, b].map(s => crypto.subtle.digest("SHA-256", enc.encode(s))));
  const u = new Uint8Array(x), v = new Uint8Array(y);
  let d = 0;
  for (let i = 0; i < u.length; i++) d |= u[i] ^ v[i];
  return d === 0;
}
function b64bytes(s) {
  s = s.replace(/-/g, "+").replace(/_/g, "/");
  const bin = atob(s + "===".slice((s.length + 3) % 4));
  return Uint8Array.from(bin, c => c.charCodeAt(0));
}
const b64text = s => new TextDecoder().decode(b64bytes(s));

// ---------------------------------------------------------------------------------------------
// The visitor's page

function page(env) {
  return new Response(APP.replace("__SITE__", JSON.stringify(env.SITE_URL || "")), {
    headers: {
      "content-type": "text/html; charset=utf-8", "cache-control": "no-store", "x-robots-tag": "noindex",
      "content-security-policy": "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; frame-src 'self'; img-src data:",
    },
  });
}

const APP = `<!DOCTYPE html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>Rewrite a briefing</title>
<link href="https://fonts.googleapis.com/css2?family=Source+Sans+3:wght@400;600;700&family=Source+Serif+4:opsz,wght@8..60,700&display=swap" rel="stylesheet">
<style>
:root{color-scheme:light dark;--bg:light-dark(#fff,#0b1411);--ink:light-dark(#121417,#e8efeb);--mut:light-dark(#4d5752,#a9b8b0);--rule:light-dark(#d5ddd8,#24332c);
--g:light-dark(#0b6b4b,#3fb487);--tint:light-dark(#eaf4ef,#12231c);--r:light-dark(#a2192f,#e0566c)}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 "Source Sans 3",system-ui,sans-serif}
header{background:#0b6b4b;color:#fff;padding:10px max(5vw,16px);font:700 18px "Source Serif 4",Georgia,serif}header a{color:#fff;text-decoration:none}
main{max-width:860px;margin:0 auto;padding:28px 16px}h1{font:700 32px/1.15 "Source Serif 4",Georgia,serif;margin:0 0 8px}
.mut{color:var(--mut)}.box{border:1px solid var(--rule);border-radius:4px;padding:14px;margin:16px 0}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0}.chip{border:1px solid var(--g);border-radius:99px;padding:3px 10px;font:inherit;font-size:14px;background:transparent;color:inherit;cursor:pointer}
.chip.off{border-color:var(--rule);text-decoration:line-through}
form{display:flex;gap:6px;flex-wrap:wrap}input{font:inherit;flex:1 1 220px;padding:5px 8px;border:1px solid var(--rule);border-radius:3px;background:transparent;color:inherit}
button.main,button.add{font:inherit;font-weight:700;border:1px solid var(--g);border-radius:3px;padding:7px 16px;cursor:pointer}
button.main{background:var(--g);color:light-dark(#fff,#06120d)}button.add{background:transparent;color:var(--g);padding:5px 12px}button[disabled]{opacity:.5;cursor:not-allowed}
.status{background:var(--tint);border-radius:4px;padding:10px 14px}.err{color:var(--r)}
iframe{width:100%;height:80vh;border:1px solid var(--rule);border-radius:4px;background:#fff}a{color:var(--g)}
</style></head><body><header><a id="home" href="#">Parliamentary briefing</a></header><main>
<h1>Rewrite a briefing with your keywords</h1>
<p class="mut" id="intro">Loading…</p>
<div class="box" id="pick" hidden>
<p><b>Edition:</b> <span id="ed"></span></p>
<p><b>Your keywords</b> <span class="mut">(click one to remove it)</span></p><div class="chips" id="kws"></div>
<form id="add"><input id="kin" maxlength="40" aria-label="Add a keyword" placeholder="Add a keyword"><button class="add" type="submit">Add</button></form>
<p id="offp" hidden><b>Topics switched off</b> <span class="mut">(click one to switch it back on)</span></p><div class="chips" id="offs"></div>
<p class="mut" id="allow"></p>
<button class="main" id="go" type="button">Start my rewrite</button>
</div>
<div id="out" aria-live="polite"></div>
</main><script>
(function(){
var SITE=__SITE__,q=new URLSearchParams(location.search),E=q.get('e')||'',st={k:[],off:[]};
try{var h=JSON.parse(decodeURIComponent(location.hash.slice(1)));if(h&&h.e===E){st.k=(h.k||[]).slice(0,12);st.off=(h.off||[]).slice(0,20)}}catch(x){}
var $=function(i){return document.getElementById(i)},out=$('out');
if(SITE)$('home').href=SITE+(E?E+'.html':'');
function el(t,c,txt){var n=document.createElement(t);if(c)n.className=c;if(txt!=null)n.textContent=txt;return n}
function api(path,opt){return fetch(path,Object.assign({credentials:'same-origin',headers:{'content-type':'application/json'}},opt||{})).then(function(r){
  if(r.redirected||r.type==='opaqueredirect')throw new Error('signin');return r.json().then(function(j){j._status=r.status;return j})})}
function draw(){var a=$('kws');a.textContent='';st.k.forEach(function(k){var b=el('button','chip',k+' ✕');b.type='button';b.onclick=function(){st.k=st.k.filter(function(x){return x!==k});draw()};a.appendChild(b)});
  if(!st.k.length)a.appendChild(el('span','mut','None yet.'));
  var o=$('offs');o.textContent='';$('offp').hidden=!st.off.length;st.off.forEach(function(t){var b=el('button','chip off',t);b.type='button';b.onclick=function(){st.off=st.off.filter(function(x){return x!==t});draw()};o.appendChild(b)});
  $('go').disabled=!st.k.length&&!st.off.length}
$('add').onsubmit=function(e){e.preventDefault();var v=$('kin').value.trim().replace(/\\s+/g,' ');if(v.length>1&&st.k.length<12&&st.k.indexOf(v)<0)st.k.push(v);$('kin').value='';draw()};
function status(t,cls){out.textContent='';var p=el('p','status'+(cls?' '+cls:''),t);out.appendChild(p);return p}
function show(id,job){out.textContent='';var p=el('p','status');p.appendChild(document.createTextNode('Your rewrite is ready'+(job&&job.title?': '+job.title:'')+'. '));
  var a=el('a',null,'Open it in a new tab');a.href='/r/'+id;a.target='_blank';a.rel='noopener';p.appendChild(a);out.appendChild(p);
  var f=document.createElement('iframe');f.src='/r/'+id;f.title='Your rewritten briefing';f.setAttribute('sandbox','allow-popups allow-popups-to-escape-sandbox');out.appendChild(f)}
function poll(id){api('/api/job/'+id).then(function(j){
  if(j.status==='done')return show(id,j);
  if(j.status==='failed'){status((j.error||'The rewrite failed.')+' Your allowance has been given back, so you can try again.','err');$('pick').hidden=false;$('go').disabled=false;return}
  status(j.status==='running'?'Writing your briefing. This usually takes three to eight minutes; you can leave this page open.':'Waiting for a writer to start…');
  setTimeout(function(){poll(id)},10000)}).catch(function(e){status('Lost contact with the service. Reload the page to check again (you may need to sign in again).','err')})}
$('go').onclick=function(){if(!confirm('Use your one rewrite for this edition now?'))return;$('go').disabled=true;status('Starting…');
  api('/api/request',{method:'POST',body:JSON.stringify({e:E,k:st.k,off:st.off})}).then(function(j){
    if(j.job&&j._status===200){$('pick').hidden=true;poll(j.job)}
    else if(j.job){$('pick').hidden=true;status(j.error||'Already used.');poll(j.job)}
    else{status(j.error||'The rewrite could not be started.','err');$('go').disabled=false}})
  .catch(function(e){status('The rewrite could not be started. Reload the page and try again (you may need to sign in again).','err');$('go').disabled=false})};
if(!/^\\d{4}-\\d{2}-\\d{2}$/.test(E)){$('intro').textContent='Open this page from the "Tune keywords" panel on a briefing.';return}
$('ed').textContent=E;
api('/api/me?e='+encodeURIComponent(E)).then(function(me){
  if(me._status!==200){$('intro').textContent=me.error||'You are not able to use this service.';return}
  $('intro').textContent='Check your keywords, then start the rewrite. An AI writer redrafts the '+E+' edition around them. The result is shown only to you.';
  if(me.usedJob){$('intro').textContent='You have already used your rewrite for this edition. Here it is.';poll(me.usedJob);return}
  $('allow').textContent=me.unlimited?'Your account has no rewrite limit.':(me.scope==='ever'?'You have one rewrite in total.':'You have one rewrite for this edition.')+' '+(me.dailyLeft>0?me.dailyLeft+' rewrites left across all readers today.':'Today\\'s limit has been reached; please try tomorrow.');
  if(!me.dailyLeft&&!me.unlimited)$('go').disabled=true;
  $('pick').hidden=false;draw();if(!me.dailyLeft&&!me.unlimited)$('go').disabled=true})
.catch(function(){$('intro').textContent='The service could not be reached. Reload the page (you may need to sign in again).'});
})();
</script></body></html>`;
