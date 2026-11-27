// Market Regime data for StockGlass and the stock-verdict skill (27 Nov 2026). Context only: nothing here is scored.
// Writes data/regime.json:
//   rates     2-year and 10-year Treasury yields and the 10-year real (TIPS) yield, with 1-week and 4-week changes and a 3-year rank.
//             Source: US Treasury daily par and real yield curves (home.treasury.gov CSV); fallback FRED DGS2, DGS10, DFII10.
//   inflation CPI, core CPI, PCE, core PCE and PPI final demand (FRED: CPIAUCSL, CPILFESL, PCEPI, PCEPILFE, PPIFIS):
//             latest month, change on the month, on the year (null when the year-ago month is missing, as for Oct 2025) and the
//             3-month annualised pace, with the previous month for comparison.
// A series that cannot be fetched keeps its last good value (with "stale": true), so the page always shows something dated.
// Usage: node scripts/market-regime.mjs   (Node 18+, no dependencies)
import fs from "node:fs";
import path from "node:path";
import { fredSeries } from "./market-fear.mjs";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36";
const OUT = path.join(ROOT, "data", "regime.json");
let prev = {}; try { prev = JSON.parse(fs.readFileSync(OUT, "utf8")); } catch {}

async function treasury(type, col) {   // returns Map(date -> value) over the last 3 calendar years
  const m = new Map(), y = new Date().getUTCFullYear();
  for (const yr of [y - 3, y - 2, y - 1, y]) {
    const u = `https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/${yr}/all?type=${type}&field_tdr_date_value=${yr}&page&_format=csv`;
    try {
      const r = await fetch(u, { headers: { "user-agent": UA, accept: "text/csv" }, signal: AbortSignal.timeout(30000) });
      if (!r.ok) throw Error("HTTP " + r.status);
      const lines = (await r.text()).trim().split(/\r?\n/), head = lines[0].split(",").map(s => s.replace(/"/g, "").trim().toLowerCase());
      const ci = head.indexOf(col.toLowerCase()); if (ci < 0) throw Error("no column " + col);
      for (const l of lines.slice(1)) { const x = l.split(",").map(s => s.replace(/"/g, "").trim()), d = x[0].match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
        if (d && x[ci] !== "" && !isNaN(+x[ci])) m.set(`${d[3]}-${d[1]}-${d[2]}`, +x[ci]); }
    } catch (e) { console.log("Treasury", type, yr, e.message); }
  }
  return m.size > 200 ? m : null;
}
function stats(m, src) {
  const k = [...m.keys()].sort(), v = k.map(x => m.get(x)), n = v.length - 1, lv = v[n], w = v.slice(-756);
  const d = j => n - j >= 0 ? +(lv - v[n - j]).toFixed(2) : null;
  return { value: lv, date: k[n], chg_1w: d(5), chg_4w: d(20), pct_3y: Math.round(100 * w.filter(x => x < lv).length / w.length), source: src };
}
const keep = (n, o) => n || (o ? { ...o, stale: true } : null);

const rates = { source: "US Treasury daily par and real yield curves (fallback FRED)" };
for (const [key, type, col, fred] of [["y2", "daily_treasury_yield_curve", "2 Yr", "DGS2"], ["y10", "daily_treasury_yield_curve", "10 Yr", "DGS10"], ["real10", "daily_treasury_real_yield_curve", "10 YR", "DFII10"]]) {
  let m = await treasury(type, col), src = "US Treasury";
  if (!m) { const cosd = new Date(Date.now() - 3.2 * 365 * 864e5).toISOString().slice(0, 10); m = await fredSeries(fred, cosd); src = "FRED " + fred; }
  rates[key] = keep(m ? stats(m, src) : null, prev.rates && prev.rates[key]);
}

// fallbacks when FRED refuses GitHub's servers: BLS public API v1 (no key; CPI, core CPI, PPI) and DBnomics (mirrors BLS and BEA)
async function blsSeries(id) {
  try {
    const r = await fetch(`https://api.bls.gov/publicAPI/v1/timeseries/data/${id}`, { headers: { "user-agent": UA }, signal: AbortSignal.timeout(30000) });
    if (!r.ok) throw Error("HTTP " + r.status);
    const j = await r.json(), d = j?.Results?.series?.[0]?.data || [], m = new Map();
    for (const x of d) if (/^M(0[1-9]|1[0-2])$/.test(x.period) && !isNaN(+x.value)) m.set(`${x.year}-${x.period.slice(1)}-01`, +x.value);
    if (m.size > 12) return m; throw Error("too few rows " + m.size);
  } catch (e) { console.log("BLS", id, e.message); return null; }
}
async function dbnomics(code) {
  try {
    const r = await fetch(`https://api.db.nomics.world/v22/series/${code}?observations=1&format=json`, { headers: { "user-agent": UA }, signal: AbortSignal.timeout(30000) });
    if (!r.ok) throw Error("HTTP " + r.status);
    const doc = (await r.json())?.series?.docs?.[0], m = new Map();
    (doc?.period || []).forEach((p, i) => { const v = doc.value[i]; if (/^\d{4}-\d{2}$/.test(p) && typeof v === "number") m.set(p + "-01", v); });
    if (m.size > 12) return m; throw Error("too few rows " + m.size);
  } catch (e) { console.log("DBnomics", code, e.message); return null; }
}
const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const inflation = { source: "FRED (BLS CPI and PPI, BEA PCE), seasonally adjusted monthly index" };
for (const [key, id, bls, dbn] of [["cpi", "CPIAUCSL", "CUSR0000SA0", "BLS/cu/CUSR0000SA0"], ["ccpi", "CPILFESL", "CUSR0000SA0L1E", "BLS/cu/CUSR0000SA0L1E"],
    ["pce", "PCEPI", null, "BEA/NIPA-T20804/DPCERG-M"], ["cpce", "PCEPILFE", null, "BEA/NIPA-T20804/DPCCRG-M"], ["ppi", "PPIFIS", "WPSFD4", "BLS/wp/WPSFD4"]]) {
  let x = null;
  // official BLS first (fast, no key), then DBnomics (BLS and BEA mirrors), FRED last (slow from GitHub's servers)
  let m = bls ? await blsSeries(bls) : null, via = "BLS " + bls;
  if (!m && dbn) { m = await dbnomics(dbn); via = "DBnomics " + dbn; }
  if (!m) { m = await fredSeries(id, "2023-01-01"); via = "FRED " + id; }
  if (m) {
    const k = [...m.keys()].sort(), last = k[k.length - 1], at = (d, mo) => { const t = new Date(d + "T00:00:00Z"); t.setUTCMonth(t.getUTCMonth() - mo); return m.get(t.toISOString().slice(0, 10)); };
    const v = m.get(last), p1 = at(last, 1), p2 = at(last, 2), p3 = at(last, 3), p12 = at(last, 12);
    const r = (a, b, pw = 1) => a != null && b != null ? +((Math.pow(a / b, pw) - 1) * 100).toFixed(2) : null;
    const t = new Date(last + "T00:00:00Z");
    x = { id, via, date: last, month: `${MON[t.getUTCMonth()]} ${t.getUTCFullYear()}`, mom: r(v, p1), prev_mom: r(p1, p2), yoy: r(v, p12), ann3m: r(v, p3, 4) };
  }
  inflation[key] = keep(x, prev.inflation && prev.inflation[key]);
  await new Promise(res => setTimeout(res, 1500));   // the relays refuse parallel calls
}

const out = { updated: new Date().toISOString(), rates, inflation, previous: prev.updated ? { updated: prev.updated, rates: prev.rates, inflation: prev.inflation } : null };
if (out.previous) { delete out.previous.rates?.source; }
fs.mkdirSync(path.dirname(OUT), { recursive: true });
fs.writeFileSync(OUT, JSON.stringify(out, null, 1));
console.log(`rates: 2y ${rates.y2?.value ?? "∅"}, 10y ${rates.y10?.value ?? "∅"}, real 10y ${rates.real10?.value ?? "∅"}; core PCE ${inflation.cpce?.month ?? "∅"} ${inflation.cpce?.yoy ?? "∅"}% y/y`);
