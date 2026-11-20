// Weekly watchlist run: serves the site locally, opens index.html?batch=1 in headless Chromium,
// waits until every ticker is done, then writes data/runs/<date>.json, data/latest.json and data/runs/index.json.
// Usage: node scripts/run-watchlist.mjs   (needs: npm i playwright && npx playwright install chromium)
import { chromium } from "playwright";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const PORT = 8765;
const TYPES = { ".html": "text/html; charset=utf-8", ".txt": "text/plain; charset=utf-8", ".json": "application/json", ".js": "text/javascript" };

const server = http.createServer((req, res) => {
  const p = decodeURIComponent(new URL(req.url, "http://x").pathname);
  const f = path.join(ROOT, p === "/" ? "index.html" : p);
  if (!f.startsWith(ROOT) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": TYPES[path.extname(f)] || "application/octet-stream" });
  fs.createReadStream(f).pipe(res);
}).listen(PORT);

// Web security off so the page can also call Yahoo / SEC / Nasdaq directly (no CORS relay needed on GitHub's servers).
const browser = await chromium.launch({ args: ["--disable-web-security", "--disable-features=IsolateOrigins,site-per-process"] });
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on("pageerror", e => console.log("page error:", e.message));

const extra = process.env.WATCHLIST ? "&watchlist=" + encodeURIComponent(process.env.WATCHLIST) : "";
await page.goto(`http://localhost:${PORT}/index.html?batch=1&direct=1${extra}`, { waitUntil: "domcontentloaded" });

const deadline = Date.now() + 75 * 60 * 1000;
let last = -1;
while (Date.now() < deadline) {
  const st = await page.evaluate(() => window.SG_BATCH ? { done: window.SG_BATCH.done, n: window.SG_BATCH.results ? window.SG_BATCH.results.length : 0, total: window.SG_BATCH.total } : null);
  if (st && st.n !== last) { last = st.n; console.log(`progress ${st.n}/${st.total}`); }
  if (st && st.done) break;
  await new Promise(r => setTimeout(r, 5000));
}
const batch = await page.evaluate(() => window.SG_BATCH);
await browser.close(); server.close();
if (!batch || !batch.results) { console.error("No results produced"); process.exit(1); }

const day = new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Paris" }); // YYYY-MM-DD, Paris date
const out = { date: day, run_at: new Date().toISOString(), seconds: batch.seconds, total: batch.total, results: batch.results };
const dir = path.join(ROOT, "data", "runs");
fs.mkdirSync(dir, { recursive: true });
fs.writeFileSync(path.join(dir, `${day}.json`), JSON.stringify(out));
fs.writeFileSync(path.join(ROOT, "data", "latest.json"), JSON.stringify(out));
const runs = fs.readdirSync(dir).filter(f => /^\d{4}-\d{2}-\d{2}\.json$/.test(f)).map(f => f.slice(0, 10)).sort();
fs.writeFileSync(path.join(dir, "index.json"), JSON.stringify({ runs }));

const scored = batch.results.filter(r => r.status === "scored").length;
const priced = batch.results.filter(r => r.status !== "no data" && !String(r.status).startsWith("error")).length;
console.log(`Done: ${batch.results.length} tickers, ${scored} scored, ${priced} with data, in ${batch.seconds}s → data/runs/${day}.json`);
for (const r of batch.results) console.log(`${r.sym.padEnd(12)} LT ${r.long_term?.score ?? "∅"}  TM ${r.timing?.score ?? "∅"}  ${r.status}  via ${JSON.stringify(r.sources || {})}`);
