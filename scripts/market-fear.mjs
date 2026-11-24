// Market fear for StockGlass and the stock-verdict skill (version 3, 21 Nov 2026).
// Writes data/market.json (today's reading) and data/market-history.json (daily series, up to 20 years).
//
// Fear score (0–10; 10% of entry timing for stocks, ETFs and indices, scaled by beta per stock; not crypto)
//   = 0.3 × premium score + 0.7 × fear-phase score.
//  Premium: variance risk premium VRP = VIX² − expected realised variance of the S&P 500 over the next 22 trading days,
//    forecast with a HAR model (Corsi 2009) fitted on past data only (expanding window), as in Bekaert & Hoerova (2014).
//    Ranked over the last 10 years and mapped to 3–7 (3 + 4 × percentile): the premium predicted returns in 1990–2005
//    (Bollerslev, Tauchen & Zhou 2009) but out of sample the evidence is mixed (Pyun 2019), so it moves the score little.
//  Phase: stress day = VIX above VIX3M or the VIX in the top 10% of its last 252 days. Early fear (first 5 stress days,
//    VIX ≥ 95% of the episode high) = 5 with a risk flag (normal average return but the deepest follow-on drops);
//    peak stress = 5.5; fading fear (VIX ≤ 85% of the high) = 7.5 only when confirmed — credit has stopped widening (HYG/IEF
//    above its 20-day low), no new 20-day S&P 500 low in the last 5 days, and no bear state (S&P 500 > 15% below its
//    52-week high with a negative 12-month return) — otherwise 5.5; after fear (stress in the last 20 days) = 4.5; calm = 5.
//    Scores set from a holdout test: 2007–2016 (not used to design v2) and 2016–2026; ungated fading fear returned +0.1%
//    over 63 days in 2007–2016 (2008), confirmed fading +2.6% (80% up, worst 21-day −9%) vs +1.6% on all days.
//    Sources: Whaley (2000, 2009); Fassas & Siriopoulos (2019); Daniel & Moskowitz (2016); Bekaert, Hoerova & Lo Duca (2013).
//  Context only: VIX percentile, VIX/VIX3M, HY option-adjusted spread (FRED, when reachable), CNN Fear & Greed.
// Usage: node scripts/market-fear.mjs   (Node 18+, no dependencies)
import fs from "node:fs";
import path from "node:path";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36";
const WIN10 = 2520, WIN5 = 1260, RVN = 22, HAR_MIN = 500;
export const PHASE = {
  calm: [5, "Calm", "No market stress: no signal from the fear cycle."],
  early: [5, "Early fear", "Fear has just begun and the VIX is near its high. Average returns after such days have been normal, but they were followed by the deepest drops: not the bottom, a high-risk entry."],
  peak: [5.5, "Peak stress", "Fear has lasted several days with the VIX near its high: forward returns slightly above average overall, but below average in 2007–2016, with large swings."],
  fading: [7.5, "Fading fear (confirmed)", "The VIX is 15%+ below its high, credit has stopped widening and the market made no new low: historically the best entry phase, with the smallest follow-on drops (2007–2016 and 2016–2026)."],
  fading_unconfirmed: [5.5, "Fading fear (unconfirmed)", "The VIX is 15%+ below its high, but credit is still widening, the market made a new low or it is in a bear market: in 2008 and 2022 such pauses came before further falls."],
  after: [4.5, "After fear", "Stress ended within the last month: returns have been below average in both 2007–2016 and 2016–2026."]
};

async function chart(sym, range = "20y") {
  for (const host of ["query1", "query2"]) {
    try {
      const r = await fetch(`https://${host}.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=${range}&interval=1d`, { headers: { "user-agent": UA } });
      if (!r.ok) throw Error("HTTP " + r.status);
      const res = (await r.json()).chart.result[0], q = res.indicators.quote[0], adj = res.indicators.adjclose?.[0]?.adjclose, m = new Map();
      res.timestamp.forEach((t, i) => { const v = adj?.[i] ?? q.close[i]; if (v != null) m.set(new Date((t + (res.meta.gmtoffset || 0)) * 1000).toISOString().slice(0, 10), v); });
      if (m.size > 500) return m;
    } catch (e) { console.log(sym, host, e.message); }
  }
  throw Error("no data for " + sym);
}
async function fredSeries(id, cosd = "2006-01-01") {
  // FRED often answers slowly to GitHub's servers: a long direct try, then the public relays the StockGlass page uses
  const base = `https://fred.stlouisfed.org/graph/fredgraph.csv?id=${id}&cosd=${cosd}`;
  for (const [u, to] of [[base, 45000], ["https://r.jina.ai/" + base, 45000], ["https://api.allorigins.win/raw?url=" + encodeURIComponent(base), 30000], ["https://api.codetabs.com/v1/proxy?quest=" + encodeURIComponent(base), 30000]]) {
    try {
      const r = await fetch(u, { headers: { "user-agent": UA, accept: "text/csv" }, signal: AbortSignal.timeout(to) });
      if (!r.ok) throw Error("HTTP " + r.status);
      const m = new Map((await r.text()).trim().split("\n").map(l => l.trim().split(",")).filter(x => /^\d{4}-\d{2}-\d{2}$/.test(x[0]) && x[1] && !isNaN(+x[1])).map(x => [x[0], +x[1]]));
      if (m.size > 100) return m;
    } catch (e) { console.log("FRED", id, e.cause?.code || e.message); }
  }
  return null;
}
async function cnnFearGreed() {
  try {
    const r = await fetch("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", { headers: { "user-agent": UA, accept: "application/json", referer: "https://edition.cnn.com/" } });
    if (!r.ok) throw Error("HTTP " + r.status);
    const fg = (await r.json()).fear_and_greed;
    return { score: Math.round(fg.score), rating: fg.rating, date: String(fg.timestamp).slice(0, 10) };
  } catch (e) { console.log("CNN Fear & Greed", e.message); return null; }
}

// ---- pure computation (exported for tests) ----
function solve4(A, b) {           // Gaussian elimination, 4×4
  const M = A.map((r, i) => [...r, b[i]]), n = 4;
  for (let c = 0; c < n; c++) {
    let p = c; for (let r = c + 1; r < n; r++) if (Math.abs(M[r][c]) > Math.abs(M[p][c])) p = r;
    [M[c], M[p]] = [M[p], M[c]]; if (Math.abs(M[c][c]) < 1e-12) return null;
    for (let r = 0; r < n; r++) if (r !== c) { const f = M[r][c] / M[c][c]; for (let k = c; k <= n; k++) M[r][k] -= f * M[c][k]; }
  }
  return M.map((r, i) => r[n] / r[i]);
}
export function build(days, vix, vix3m, spx, credit) {
  const S = [], r2 = [];
  for (let i = 1; i < days.length; i++) r2.push(252 * Math.log(spx.get(days[i]) / spx.get(days[i - 1])) ** 2 * 1e4);
  const d = days.slice(1), n = d.length, X = [], Y = [];
  const XtX = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]], Xty = [0, 0, 0, 0]; let pairs = 0, beta = null;
  const mean = (a, b) => { let s = 0; for (let k = a; k <= b; k++) s += r2[k]; return s / (b - a + 1); };
  for (let i = 0; i < n; i++) {
    if (i >= RVN - 1) X[i] = [1, r2[i], mean(i - 4, i), mean(i - RVN + 1, i)];
    if (i + RVN < n) Y[i] = mean(i + 1, i + RVN);
    const j = i - RVN;                      // the target of day j is fully known at day i
    if (j >= 0 && X[j] && Y[j] != null) { const x = X[j]; for (let a = 0; a < 4; a++) { Xty[a] += x[a] * Y[j]; for (let b = 0; b < 4; b++) XtX[a][b] += x[a] * x[b]; } pairs++; if (pairs >= HAR_MIN && (pairs % 5 === 0 || !beta)) beta = solve4(XtX, Xty) || beta; }
    if (!X[i]) continue;
    const v = vix.get(d[i]), rv = X[i][3];
    const har = beta && pairs >= HAR_MIN ? Math.max(1, beta.reduce((s, b, k) => s + b * X[i][k], 0)) : rv;
    S.push({ date: d[i], vix: v, vix3m: vix3m.get(d[i]) ?? null, spx: spx.get(d[i]), rv22: rv, rvhar: har, vrp: v * v - har, vrp_trail: v * v - rv, credit: credit?.get(d[i]) ?? null });
  }
  // phases
  const pct = (arr, x) => arr.filter(a => a < x).length / arr.length;
  let age = 0, peak = 0, last = -999;
  S.forEach((s, i) => {
    const yr = S.slice(Math.max(0, i - 251), i + 1);
    const stress = (s.vix3m && s.vix / s.vix3m > 1) || (i >= 60 && pct(yr.map(x => x.vix), s.vix) >= 0.9);
    const hi52 = Math.max(...yr.map(x => x.spx)), ago = S[i - 251]?.spx;
    s.bear = s.spx < 0.85 * hi52 && ago != null && s.spx < ago;
    const lows = S.slice(Math.max(0, i - 4), i + 1).some((x, k) => { const at = Math.max(0, i - 4) + k; return x.spx <= Math.min(...S.slice(Math.max(0, at - 19), at + 1).map(y => y.spx)); });
    const cw = S.slice(Math.max(0, i - 19), i + 1).map(x => x.credit).filter(x => x != null);
    s.credit_easing = s.credit == null || cw.length < 10 ? null : s.credit > Math.min(...cw);
    s.new_low5 = lows;
    if (stress) { age = age ? age + 1 : 1; peak = age === 1 ? s.vix : Math.max(peak, s.vix); last = i; } else age = 0;
    s.age = age; s.peak = stress ? peak : null;
    if (!stress) s.phase = i - last <= 20 ? "after" : "calm";
    else if (age <= 5 && s.vix >= 0.95 * peak) s.phase = "early";
    else if (s.vix <= 0.85 * peak) s.phase = (s.credit_easing !== false && !s.new_low5 && !s.bear) ? "fading" : "fading_unconfirmed";
    else s.phase = "peak";
  });
  return S;
}
export function reading(S) {
  const last = S[S.length - 1], win = S.slice(-(S.length >= WIN10 ? WIN10 : WIN5));
  const pv = win.filter(s => s.vrp < last.vrp).length / win.length, pk = win.filter(s => s.vix < last.vix).length / win.length;
  const prem = 3 + 4 * pv, ph = PHASE[last.phase][0], score = +(0.3 * prem + 0.7 * ph).toFixed(1);
  const label = score >= 6.5 ? "Supportive" : score <= 4.5 ? "Unsupportive" : "Neutral";
  const ratio = last.vix3m ? +(last.vix / last.vix3m).toFixed(3) : null;
  const ago24 = S[S.length - 1 - 504]?.spx, w200 = S.slice(-200), ma200 = w200.reduce((a, s) => a + s.spx, 0) / w200.length;
  const note = `${PHASE[last.phase][1]}${last.age ? ` (day ${last.age} of stress, VIX high ${last.peak.toFixed(1)})` : ""}: ${PHASE[last.phase][2]}`
    + ` Variance risk premium (HAR) higher than ${Math.round(pv * 100)}% of the last ${(win.length / 252).toFixed(0)} years.`
    + (ratio != null && ratio > 1 ? " VIX above VIX3M: the term structure is inverted, a sign of near-term stress." : "")
    + (last.bear ? " Bear state: the S&P 500 is more than 15% below its 52-week high with a negative 12-month return." : "");
  return {
    date: last.date, vix: +last.vix.toFixed(2), vix3m: last.vix3m != null ? +last.vix3m.toFixed(2) : null, vix_vix3m: ratio,
    rv22: +last.rv22.toFixed(1), rv_expected: +last.rvhar.toFixed(1), vrp: +last.vrp.toFixed(1), vrp_pct: Math.round(pv * 100), vix_pct: Math.round(pk * 100),
    window_years: +(win.length / 252).toFixed(1), phase: last.phase, phase_label: PHASE[last.phase][1], stress_days: last.age, vix_peak: last.peak,
    risk_flag: last.phase === "early", fading_checks: last.phase.startsWith("fading") ? { credit_easing: last.credit_easing, new_low_5d: last.new_low5, bear_state: last.bear } : null,
    premium_score: +prem.toFixed(1), phase_score: ph, score, label, note,
    market: { index: "S&P 500", above_200d: last.spx > ma200, ret_24m: ago24 ? +((last.spx / ago24 - 1) * 100).toFixed(1) : null, bear_state: last.bear },
    weights: { premium: 0.3, phase: 0.7, timing_share: 0.10, beta_scaled: "5 + (score − 5) × clip(beta, 0.5, 1.5)" }
  };
}

if (process.argv[1] && process.argv[1].endsWith("market-fear.mjs")) {
  const [vix, spx] = await Promise.all([chart("^VIX"), chart("^GSPC")]);
  let vix3m = new Map(); try { vix3m = await chart("^VIX3M"); } catch (e) { console.log("VIX3M unavailable"); }
  let credit = null;
  try { const [hyg, ief] = await Promise.all([chart("HYG"), chart("IEF")]); credit = new Map([...hyg].filter(([d]) => ief.has(d)).map(([d, v]) => [d, v / ief.get(d)])); } catch (e) { console.log("HYG/IEF unavailable", e.message); }
  const days = [...spx.keys()].filter(d => vix.has(d)).sort();
  const S = build(days, vix, vix3m, spx, credit), out = reading(S);
  const [oas, fg] = await Promise.all([fredSeries("BAMLH0A0HYM2"), cnnFearGreed()]);
  if (oas) { const k = [...oas.keys()].sort(), v = k.map(x => oas.get(x)), w = v.slice(-WIN10), lv = v[v.length - 1]; out.credit_spread = { date: k[k.length - 1], value: lv, pct: Math.round(100 * w.filter(x => x < lv).length / w.length), high_20d: Math.max(...v.slice(-20)) }; } else out.credit_spread = null;
  out.credit_proxy = credit ? { series: "HYG/IEF total-return ratio", easing: S[S.length - 1].credit_easing } : null;
  // credit check (context only, never scored). Main measure: ICE BofA option-adjusted spreads from FRED (high yield BAMLH0A0HYM2,
  // investment grade BAMLC0A0CM), change over 1 and 4 weeks and rank over the available years. Plain fund ratios also move with
  // interest rates (HYG duration ~3.2 y, LQD ~8.3 y, IEF ~7.3 y), so the backup measure is a rate-adjusted return:
  // fund return minus (fund duration / IEF duration) x IEF return. Plus the 10-year Treasury yield (^TNX) and the S&P 500.
  try {
    const D = { HYG: 3.2, LQD: 8.3, IEF: 7.3 };
    const [hyg, lqd, ief2, tnx] = await Promise.all([chart("HYG"), chart("LQD"), chart("IEF"), chart("^TNX").catch(() => null)]);
    const keys = m => [...m.keys()].sort();
    const chg = (m, n) => { const k = keys(m); if (k.length <= n) return null; const a = m.get(k[k.length - 1 - n]), b = m.get(k[k.length - 1]); return +((b / a - 1) * 100).toFixed(2); };
    const dif = (m, n, dp = 2) => { const k = keys(m); if (k.length <= n) return null; return +(m.get(k[k.length - 1]) - m.get(k[k.length - 1 - n])).toFixed(dp); };
    const adj = (f, n) => { const a = chg(f === "HYG" ? hyg : lqd, n), b = chg(ief2, n); return a == null || b == null ? null : +(a - D[f] / D.IEF * b).toFixed(2); };
    const sp = async id => { const m = await fredSeries(id, "2019-01-01"); if (!m || m.size < 30) return null;
      const k = keys(m), v = k.map(x => m.get(x)), lv = v[v.length - 1], w = v.slice(-756);
      return { value: lv, date: k[k.length - 1], chg_1w: dif(m, 5), chg_4w: dif(m, 20), pct_3y: Math.round(100 * w.filter(x => x < lv).length / w.length) }; };
    // one FRED call at a time (parallel calls get refused by the relays), a second round for what failed, else the last good value (≤ 5 days)
    let hyS = await sp("BAMLH0A0HYM2"), igS = await sp("BAMLC0A0CM");
    if (!hyS || !igS) { await new Promise(r => setTimeout(r, 20000)); if (!hyS) hyS = await sp("BAMLH0A0HYM2"); if (!igS) igS = await sp("BAMLC0A0CM"); }
    let prev = null; try { prev = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "market.json"), "utf8")).credit_check?.spreads; } catch {}
    const keep = (n, o) => n || (o && o.date && Date.now() - Date.parse(o.date) < 5 * 864e5 ? { ...o, stale: true } : null);
    hyS = keep(hyS, prev?.hy); igS = keep(igS, prev?.ig);
    out.credit_check = { version: 2, date: keys(hyg).pop(),
      spreads: hyS || igS ? { source: "ICE BofA option-adjusted spreads (FRED), percentage points", hy: hyS, ig: igS } : null,
      hy_adj: { series: "HYG vs IEF, rate-adjusted", chg_1w: adj("HYG", 5), chg_4w: adj("HYG", 20) },
      ig_adj: { series: "LQD vs IEF, rate-adjusted", chg_1w: adj("LQD", 5), chg_4w: adj("LQD", 20) },
      hy: credit ? { series: "HYG/IEF", chg_1w: chg(credit, 5), chg_4w: chg(credit, 20) } : null,
      ust10: tnx ? { value: +tnx.get(keys(tnx).pop()).toFixed(2), chg_1w: dif(tnx, 5), chg_4w: dif(tnx, 20) } : null,
      spx: { chg_1w: chg(spx, 5), chg_4w: chg(spx, 20) }, durations: D };
  } catch (e) { out.credit_check = null; console.log("credit check unavailable", e.message); }
  out.cnn_fear_greed = fg;
  out.updated = new Date().toISOString();
  out.method = "Fear score = 0.3 × (3 + 4 × HAR variance-risk-premium percentile over 10 years) + 0.7 × fear-phase score (calm 5, early fear 5 + risk flag, peak stress 5.5, fading fear 7.5 if confirmed by credit, no new low and no bear state, else 5.5, after fear 4.5). Per stock: 5 + (score − 5) × clip(beta, 0.5, 1.5), 10% of entry timing. Holdout-tested on 2007–2016.";
  out.history = "data/market-history.json";
  fs.mkdirSync(path.join(ROOT, "data"), { recursive: true });
  fs.writeFileSync(path.join(ROOT, "data", "market.json"), JSON.stringify(out, null, 1));
  const cols = ["date", "vix", "vix3m", "spx", "rv22", "vrp_trail", "phase", "rvhar", "vrp", "credit", "bear"];
  fs.writeFileSync(path.join(ROOT, "data", "market-history.json"), JSON.stringify({ columns: cols, rows: S.map(s => [s.date, +s.vix.toFixed(2), s.vix3m != null ? +s.vix3m.toFixed(2) : null, +s.spx.toFixed(2), +s.rv22.toFixed(1), +s.vrp_trail.toFixed(1), s.phase, +s.rvhar.toFixed(1), +s.vrp.toFixed(1), s.credit != null ? +s.credit.toFixed(5) : null, s.bear ? 1 : 0]) }));
  console.log(`${out.date}: VIX ${out.vix}, VRP(HAR) pct ${out.vrp_pct}, phase ${out.phase_label} (day ${out.stress_days}) → ${out.score}/10 ${out.label}; credit easing ${out.credit_proxy?.easing}; HY OAS ${out.credit_spread?.value ?? "∅"}; CNN ${fg?.score ?? "∅"}`);
}
