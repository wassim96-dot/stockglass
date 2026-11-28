// Download daily prices (split-adjusted close, high, low, volume, dividend-adjusted close) for the universe + SPY,
// through the shared routes of scripts/lib/net.mjs (direct, then relays; timeouts). One request per ticker, cached
// in backtest/cache/<T>.json. Usage: node backtest/fetch.mjs
import fs from "node:fs";
import path from "node:path";
import { yahooChart, yahooStats, sleep } from "../scripts/lib/net.mjs";
const HERE = path.dirname(new URL(import.meta.url).pathname), C = path.join(HERE, "cache");
fs.mkdirSync(C, { recursive: true });
const U = JSON.parse(fs.readFileSync(path.join(HERE, "universe.json"), "utf8"));
const syms = ["SPY", ...U.stocks.map(s => s.ticker)];
let ok = 0; const failed = [];
for (const s of syms) {
  const f = path.join(C, s + ".json");
  if (fs.existsSync(f)) { ok++; continue; }
  let res; for (let k = 0; k < 3 && !res; k++) { res = await yahooChart(s, "max", { timeout: 45000 }); if (!res) await sleep(4000); }
  if (!res) { failed.push(s); console.log("FAILED", s); continue; }
  const q = res.indicators.quote[0], adj = res.indicators.adjclose?.[0]?.adjclose || q.close, d = [], c = [], a = [], h = [], l = [], v = [];
  res.timestamp.forEach((t, i) => { if (q.close[i] == null || adj[i] == null) return;
    d.push(new Date((t + (res.meta.gmtoffset || 0)) * 1000).toISOString().slice(0, 10)); c.push(+q.close[i].toFixed(4)); a.push(+adj[i].toFixed(4));
    h.push(+(q.high[i] ?? q.close[i]).toFixed(4)); l.push(+(q.low[i] ?? q.close[i]).toFixed(4)); v.push(q.volume[i] ?? 0); });
  fs.writeFileSync(f, JSON.stringify({ s, d, c, a, h, l, v })); ok++;
  console.log(`${s}: ${d.length} days from ${d[0]}`);
  await sleep(600);
}
console.log(`prices: ${ok}/${syms.length}; failed: ${failed.join(" ") || "none"}; routes ${JSON.stringify(yahooStats())}`);
if (ok < syms.length * 0.9) process.exit(1);
