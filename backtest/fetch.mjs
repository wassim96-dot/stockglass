// Download daily prices (split-adjusted close, high, low, volume, dividend-adjusted close) for the universe + SPY,
// through the shared routes of scripts/lib/net.mjs (direct, then relays; timeouts). One request per ticker, cached
// in backtest/cache/<T>.json. Usage: node backtest/fetch.mjs
import fs from "node:fs";
import path from "node:path";
import { yahooChart, yahooStats, sleep } from "../scripts/lib/net.mjs";
const HERE = path.dirname(new URL(import.meta.url).pathname), C = path.join(HERE, "cache");
fs.mkdirSync(C, { recursive: true });
const U = JSON.parse(fs.readFileSync(path.join(HERE, "universe.json"), "utf8"));
const syms = ["SPY", "XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU", "XLB", "XLRE", "XLC", ...U.stocks.map(s => s.ticker)];   // sector ETFs: Minervini "leading sector" point (test 3)
let ok = 0; const failed = [];
for (const s of syms) {
  const f = path.join(C, s + ".json");
  if (fs.existsSync(f)) { ok++; continue; }
  let res; for (let k = 0; k < 3 && !res; k++) { res = await yahooChart(s, "max", { timeout: 45000, period1: 1230768000 }); if (!res) await sleep(4000); }   // daily bars from 2009-01-01
  if (!res) { failed.push(s); console.log("FAILED", s); continue; }
  const q = res.indicators.quote[0], adj = res.indicators.adjclose?.[0]?.adjclose || q.close, d = [], c = [], a = [], h = [], l = [], v = [];
  res.timestamp.forEach((t, i) => { if (q.close[i] == null || adj[i] == null) return;
    d.push(new Date((t + (res.meta.gmtoffset || 0)) * 1000).toISOString().slice(0, 10)); c.push(+q.close[i].toFixed(4)); a.push(+adj[i].toFixed(4));
    h.push(+(q.high[i] ?? q.close[i]).toFixed(4)); l.push(+(q.low[i] ?? q.close[i]).toFixed(4)); v.push(q.volume[i] ?? 0); });
  const gap = d.slice(1).reduce((m, x, i) => Math.max(m, (Date.parse(x) - Date.parse(d[i])) / 864e5), 0);
  if (gap > 10) { console.log(`${s}: not daily (largest gap ${gap} days), rejected`); failed.push(s); continue; }   // monthly bars must never pass as daily
  fs.writeFileSync(f, JSON.stringify({ s, d, c, a, h, l, v })); ok++;
  console.log(`${s}: ${d.length} days from ${d[0]}`);
  await sleep(600);
}
console.log(`prices: ${ok}/${syms.length}; failed: ${failed.join(" ") || "none"}; routes ${JSON.stringify(yahooStats())}`);
if (ok < syms.length * 0.9) process.exit(1);
