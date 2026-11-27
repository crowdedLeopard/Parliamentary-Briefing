// Local stand-in for the Worker, for trying the page end to end: node test/serve-local.mjs <port> <site url>
// GitHub is faked: a "dispatch" just records the job, and POST /_finish/<id> plays the workflow's part.
import http from "node:http";
import worker from "../src/index.js";

const [port = "8787", site = "http://localhost:8765/"] = process.argv.slice(2);
const m = new Map();
const env = { REGEN: { get: async k => m.get(k) ?? null, put: async (k, v) => void m.set(k, v), delete: async k => void m.delete(k) },
              GITHUB_REPO: "o/r", GITHUB_TOKEN: "t", HOOK_SECRET: "local", USER_SALT: "local", SITE_URL: site,
              ALLOWED_EMAILS: process.env.ALLOWED || "reader@example.org", DAILY_CAP: "10",
              // fake mail: the last code sent is readable at /_code (codes on unless NOCODE=1)
              ...(process.env.NOCODE ? {} : { EMAIL_FROM: "briefing@localhost.test", EMAIL: { send: async msg => { lastCode = msg.subject.match(/\d{6}/)[0]; return { messageId: "x" }; } } }) };
let lastCode = "";
const realFetch = globalThis.fetch;
globalThis.fetch = async (url, opt) => (String(url).includes("api.github.com") ? new Response(null, { status: 204 }) : realFetch(url, opt));

http.createServer(async (req, res) => {
  const body = await new Promise(r => { let b = ""; req.on("data", d => (b += d)).on("end", () => r(b)); });
  if (req.url === "/_code") { res.end(lastCode); return; }
  const fin = req.url.match(/^\/_finish\/(\w+)/);
  if (fin) {
    await worker.fetch(new Request(`http://x/hook/job/${fin[1]}`, { headers: { authorization: "Bearer local" } }), env);
    await worker.fetch(new Request(`http://x/hook/job/${fin[1]}`, { method: "POST", headers: { authorization: "Bearer local", "content-type": "application/json" },
      body: JSON.stringify({ status: "done", title: "Test rewrite", html: "<!DOCTYPE html><h1>Rewritten</h1>" }) }), env);
    res.end("ok"); return;
  }
  const r = await worker.fetch(new Request(`http://localhost:${port}${req.url}`, { method: req.method, headers: req.headers,
    body: ["GET", "HEAD", "OPTIONS"].includes(req.method) ? undefined : body }), env);
  res.writeHead(r.status, Object.fromEntries(r.headers));
  res.end(Buffer.from(await r.arrayBuffer()));
}).listen(Number(port));
