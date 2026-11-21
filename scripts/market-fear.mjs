// Market fear for StockGlass and the stock-verdict skill (version 2, 21 Nov 2026).
// Writes data/market.json (today's reading) and data/market-history.json (daily series, up to 20 years).
//
// Fear score (0–10, 10% of every entry-timing score except crypto) = average of two parts:
//  1. Variance risk premium (VRP) = VIX² − realised variance of the S&P 500 over the last 22 trading days (annualised %²),
//     ranked against the last 10 years (2,520 trading days; 5 years if less history). A high premium has predicted higher
//     market returns over the next 2–4 months in the US and Europe (Bollerslev, Tauchen & Zhou 2009; Bollerslev, Marrone,
//     Xu & Zhou 2014). Out of sample it is weaker: in 2016–2026 high- and low-premium days were followed by similar returns.
//  2. Fear phase: where the market is inside a stress episode. A stress day = VIX above VIX3M (inverted term structure) or
//     the VIX in the top 10% of its last year. Phases: calm, early fear (first 5 stress days, VIX still near its high),
//     peak stress, fading fear (VIX 15%+ below the episode's high), after fear (stress ended in the last 20 days).
//     Volatility spikes mean-revert (Whaley 2009), and losers rebound hardest when fear recedes (Daniel & Moskowitz 2016).
//     Event study on 2016–2026 daily data (scripts/market-fear.mjs history, S&P 500, overlapping windows, ~20 episodes):
//     average 63-day return after fading-fear days +10.5% (86% positive) vs +3.4% on all days; early fear +3.8% with the
//     worst 21-day drawdowns (−24%). Phase scores are those results shrunk towards neutral 5: calm 5, early 4.5, peak 6,
//     fading 8, after 5.5. The early-fear rule keeps the score from rewarding the first days of a panic.
//  Context only (not scored): VIX level and percentile, VIX/VIX3M, high-yield credit spread (FRED BAMLH0A0HYM2), and the
//  CNN Fear & Greed Index when its public feed answers (no peer-reviewed evidence; most of its parts are price-based).
// Usage: node scripts/market-fear.mjs   (Node 18+, no dependencies)
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36";
const WIN10 = 2520, WIN5 = 1260, RVN = 22;
const PHASE = {
  calm: [5, "Calm", "No market stress: no signal from the fear cycle."],
  early: [4.5, "Early fear", "Fear has only just begun and the VIX is still near its high: historically the first days of a panic are not the bottom (deepest follow-on drops); bottoms tend to come after fear has lasted and starts to fade."],
  peak: [6, "Peak stress", "Fear has lasted several days with the VIX near its high: forward returns have been above average, but swings stay large."],
  fading: [8, "Fading fear", "Fear has lasted and the VIX is 15%+ below its high: historically the best entry phase for the market (average +10.5% over 3 months in 2016–2026)."],
  after: [5.5, "After fear", "Stress ended within the last month: returns close to normal, with a slightly better hit rate."]
};

async function chart(sym, range = "20y") {
  for (const host of ["query1", "query2"]) {
    try {
      const r = await fetch(`https://${host}.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=${range}&interval=1d`, { headers: { "user-agent": UA } });
      if (!r.ok) throw Error("HTTP " + r.status);
      const res = (await r.json()).chart.result[0], q = res.indicators.quote[0], m = new Map();
      res.timestamp.forEach((t, i) => { if (q.close[i] != null) m.set(new Date((t + (res.meta.gmtoffset || 0)) * 1000).toISOString().slice(0, 10), q.close[i]); });
      if (m.size > 500) return m;
    } catch (e) { console.log(sym, host, e.message); }
  }
  throw Error("no data for " + sym);
}
async function fredLast(id) {          // high-yield option-adjusted spread, percent
  try {
    const r = await fetch(`https://fred.stlouisfed.org/graph/fredgraph.csv?id=${id}`, { headers: { "user-agent": UA } });
    if (!r.ok) throw Error("HTTP " + r.status);
    const rows = (await r.text()).trim().split("\n").slice(1).map(l => l.split(",")).filter(x => x[1] && x[1] !== "." && !isNaN(+x[1])).map(x => [x[0], +x[1]]);
    const last = rows[rows.length - 1], w = rows.slice(-WIN10);
    return { date: last[0], value: last[1], pct: Math.round(100 * w.filter(x => x[1] < last[1]).length / w.length), years: +(w.length / 252).toFixed(1) };
  } catch (e) { console.log("FRED", id, e.message); return null; }
}
async function cnnFearGreed() {
  try {
    const r = await fetch("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", { headers: { "user-agent": UA, accept: "application/json", referer: "https://edition.cnn.com/" } });
    if (!r.ok) throw Error("HTTP " + r.status);
    const fg = (await r.json()).fear_and_greed;
    return { score: Math.round(fg.score), rating: fg.rating, date: String(fg.timestamp).slice(0, 10) };
  } catch (e) { console.log("CNN Fear & Greed", e.message); return null; }
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
  const rv = 252 * rets.reduce((a, r) => a + r * r, 0) / rets.length * 1e4, v = vix.get(days[i]);
  series.push([days[i], +v.toFixed(2), vix3m.has(days[i]) ? +vix3m.get(days[i]).toFixed(2) : null, +spx.get(days[i]).toFixed(2), +rv.toFixed(1), +(v * v - rv).toFixed(1)]);
}

// fear phase for every day (same rule in scripts/market_fear.py of the skill)
const pctOf = (arr, x) => arr.filter(a => a < x).length / arr.length;
let age = 0, peak = 0, lastStress = -999;
const phases = series.map((s, i) => {
  const yr = series.slice(Math.max(0, i - 251), i + 1).map(x => x[1]);
  const stress = (s[2] && s[1] / s[2] > 1) || (i >= 60 && pctOf(yr, s[1]) >= 0.9);
  if (stress) { age = age ? age + 1 : 1; peak = age === 1 ? s[1] : Math.max(peak, s[1]); lastStress = i; } else age = 0;
  if (!stress) return { phase: i - lastStress <= 20 ? "after" : "calm", age: 0, peak: null };
  if (age <= 5 && s[1] >= 0.95 * peak) return { phase: "early", age, peak };
  if (s[1] <= 0.85 * peak) return { phase: "fading", age, peak };
  return { phase: "peak", age, peak };
});

const last = series[series.length - 1], ph = phases[phases.length - 1];
const win = series.slice(-(series.length >= WIN10 ? WIN10 : WIN5));
const vrpPct = pctOf(win.map(s => s[5]), last[5]), vixPct = pctOf(win.map(s => s[1]), last[1]);
const ratio = last[2] ? +(last[1] / last[2]).toFixed(3) : null;
const vrpScore = 10 * vrpPct, phScore = PHASE[ph.phase][0];
const score = +((vrpScore + phScore) / 2).toFixed(1);
const label = score >= 7 ? "High fear premium" : score <= 3.5 ? "Low fear premium" : "Normal fear premium";
const [hy, fg] = await Promise.all([fredLast("BAMLH0A0HYM2"), cnnFearGreed()]);
const note = `${PHASE[ph.phase][1]}${ph.age ? ` (day ${ph.age} of stress, VIX high ${ph.peak.toFixed(1)})` : ""}: ${PHASE[ph.phase][2]}`
  + ` Variance risk premium higher than ${Math.round(vrpPct * 100)}% of the last ${(win.length / 252).toFixed(0)} years.`
  + (ratio != null && ratio > 1 ? " VIX above VIX3M: the term structure is inverted, a sign of near-term stress." : "");
const out = {
  updated: new Date().toISOString(), date: last[0], vix: last[1], vix3m: last[2], vix_vix3m: ratio, rv22: last[4], vrp: last[5],
  vrp_pct: Math.round(vrpPct * 100), vix_pct: Math.round(vixPct * 100), window_years: +(win.length / 252).toFixed(1),
  phase: ph.phase, phase_label: PHASE[ph.phase][1], stress_days: ph.age, vix_peak: ph.peak, vrp_score: +vrpScore.toFixed(1), phase_score: phScore,
  score, label, note, credit_spread: hy, cnn_fear_greed: fg,
  method: "Fear score = ½ × variance-risk-premium percentile over 10 years ÷ 10 + ½ × fear-phase score (calm 5, early fear 4.5, peak stress 6, fading fear 8, after fear 5.5). Bollerslev, Tauchen & Zhou (2009); Bollerslev, Marrone, Xu & Zhou (2014); Whaley (2009); Daniel & Moskowitz (2016); event study 2016–2026.",
  history: "data/market-history.json"
};
fs.mkdirSync(path.join(ROOT, "data"), { recursive: true });
fs.writeFileSync(path.join(ROOT, "data", "market.json"), JSON.stringify(out, null, 1));
fs.writeFileSync(path.join(ROOT, "data", "market-history.json"), JSON.stringify({ columns: ["date", "vix", "vix3m", "spx", "rv22", "vrp", "phase"], rows: series.map((s, i) => [...s, phases[i].phase]) }));
console.log(`${out.date}: VIX ${out.vix} (pct ${out.vix_pct}), VIX/VIX3M ${ratio}, VRP pct ${out.vrp_pct} over ${out.window_years}y, phase ${out.phase_label} (day ${ph.age}) → ${score}/10 ${label}; HY spread ${hy ? hy.value : "∅"}; CNN F&G ${fg ? fg.score : "∅"}`);
