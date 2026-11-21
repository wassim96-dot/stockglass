// Market fear (VIX) for StockGlass and the stock-verdict skill.
// Writes data/market.json (today's reading, small) and data/market-history.json (daily series, 10 years).
//
// Method (scientific basis):
//  - Variance risk premium (VRP) = implied variance (VIX², next 30 days, annualised) minus realised variance of the
//    S&P 500 over the last 22 trading days (annualised, daily log returns). A high premium has predicted higher
//    market returns over the next 2–4 months, in the US and in Europe; the US ("global") premium predicts European
//    returns better than local ones (Bollerslev, Tauchen & Zhou 2009, RFS; Bollerslev, Marrone, Xu & Zhou 2014, JFQA).
//  - The VIX level alone has little predictive power (same papers; Johnson 2017, JFQA), so it is shown as context,
//    with the VIX / VIX3M term structure (above 1 = inverted, near-term stress).
//  - Score 0–10 = the VRP's percentile within its own last 5 years of daily readings (1,260 trading days).
// Usage: node scripts/market-fear.mjs   (Node 18+, no dependencies; Yahoo chart API)
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36";
const WIN = 1260, RVN = 22;

async function chart(sym) {
  for (const host of ["query1", "query2"]) {
    try {
      const r = await fetch(`https://${host}.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=10y&interval=1d`, { headers: { "user-agent": UA } });
      if (!r.ok) throw Error("HTTP " + r.status);
      const res = (await r.json()).chart.result[0], q = res.indicators.quote[0], m = new Map();
      res.timestamp.forEach((t, i) => { if (q.close[i] != null) m.set(new Date((t + (res.meta.gmtoffset || 0)) * 1000).toISOString().slice(0, 10), q.close[i]); });
      if (m.size > 500) return m;
    } catch (e) { console.log(sym, host, e.message); }
  }
  throw Error("no data for " + sym);
}

const [vix, spx] = await Promise.all([chart("^VIX"), chart("^GSPC")]);
let vix3m = new Map();
try { vix3m = await chart("^VIX3M"); } catch (e) { console.log("VIX3M unavailable"); }

const days = [...spx.keys()].filter(d => vix.has(d)).sort();
const series = [];
for (let i = 1; i < days.length; i++) {
  const rets = [];
  for (let j = Math.max(1, i - RVN + 1); j <= i; j++) rets.push(Math.log(spx.get(days[j]) / spx.get(days[j - 1])));
  if (rets.length < RVN) continue;
  const rv = 252 * rets.reduce((a, r) => a + r * r, 0) / rets.length * 1e4;      // annualised, in %²
  const v = vix.get(days[i]), iv = v * v;                                            // VIX² in %²
  series.push([days[i], +v.toFixed(2), vix3m.has(days[i]) ? +vix3m.get(days[i]).toFixed(2) : null, +spx.get(days[i]).toFixed(2), +rv.toFixed(1), +(iv - rv).toFixed(1)]);
}
const pct = (arr, x) => arr.filter(a => a < x).length / arr.length;
const last = series[series.length - 1], win = series.slice(-WIN);
const vrpPct = pct(win.map(s => s[5]), last[5]), vixPct = pct(win.map(s => s[1]), last[1]);
const ratio = last[2] ? +(last[1] / last[2]).toFixed(3) : null;
const score = +(10 * vrpPct).toFixed(1);
const label = vrpPct >= 0.8 ? "High fear premium" : vrpPct <= 0.2 ? "Low fear premium" : "Normal fear premium";
const note = (vrpPct >= 0.8 ? "Option buyers pay far more than recent swings justify: historically followed by above-average market returns over 2–4 months, with larger swings."
  : vrpPct <= 0.2 ? "Little premium over realised volatility (complacency, or realised swings already exceed implied): historically followed by below-average market returns."
  : "Premium in its usual range: no signal from volatility pricing.")
  + (ratio != null && ratio > 1 ? " VIX above VIX3M: the term structure is inverted, a sign of near-term stress." : "");
const out = {
  updated: new Date().toISOString(), date: last[0], vix: last[1], vix3m: last[2], vix_vix3m: ratio, rv22: last[4], vrp: last[5],
  vrp_pct: +(vrpPct * 100).toFixed(0), vix_pct: +(vixPct * 100).toFixed(0), score, label, note, window_days: win.length,
  method: "VRP = VIX² − 22-day realised variance of the S&P 500 (annualised %²); score = 10 × its percentile over the last 5 years. Bollerslev, Tauchen & Zhou (2009); Bollerslev, Marrone, Xu & Zhou (2014).",
  history: "data/market-history.json"
};
fs.mkdirSync(path.join(ROOT, "data"), { recursive: true });
fs.writeFileSync(path.join(ROOT, "data", "market.json"), JSON.stringify(out, null, 1));
fs.writeFileSync(path.join(ROOT, "data", "market-history.json"), JSON.stringify({ columns: ["date", "vix", "vix3m", "spx", "rv22", "vrp"], rows: series }));
console.log(`${out.date}: VIX ${out.vix} (5y pct ${out.vix_pct}%), VIX/VIX3M ${ratio}, RV22 ${out.rv22}, VRP ${out.vrp} (pct ${out.vrp_pct}%) → ${score}/10, ${label}`);
