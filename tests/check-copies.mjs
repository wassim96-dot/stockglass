// Copy check (27 Nov 2026): the rules that live in several files must give the same answers. No network.
// Runs each copy on the same inputs (the saved data files plus synthetic variants that reach every branch) and lists
// every input where two copies disagree. In the repo (CI):
//   regime.js  ↔ scripts/regime.py        fearZone, creditZone, ratesRead, inflationRead, btcCycle, liveFear, fearAt
//   creditRead in index.html ↔ today.html ↔ scripts/weekly_review.py credit_read
// With --skill <stock-verdict folder> (local check before a release; the skill is not in this repo), also:
//   scripts/regime.py = skill scripts/regime.py (same file, and same answers), data/glossary.json = skill assets/glossary.json,
//   glossInit in regime.js = skill assets/gloss.js, creditRead = skill render.py credit_read,
//   WI_S / LW_S / LW_F / LW_C in index.html = skill score.py WI / LENS.balanced / LENS_ETF.etf / LENS_CRYPTO.crypto.
// Usage: node tests/check-copies.mjs [--skill ../stock-verdict]      exit code 1 when a copy differs
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { execFileSync } from "node:child_process";
import { createRequire } from "node:module";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const P = f => path.join(ROOT, f), J = f => JSON.parse(fs.readFileSync(P(f), "utf8"));
const norm = v => JSON.parse(JSON.stringify(v ?? null));
// compare what the pages show; fields that exist in one copy only, for its own page, are left out
// liveFear: which live quotes were used is `used` in JS and `live_inputs` in Python; rv_expected is shown on the skill page only
const VIEW = { liveFear: o => o && (({ used, live_inputs, rv_expected, ...r }) => ({ ...r, used: used ?? live_inputs ?? null }))(o),
  creditRead: o => o && { status: o.status, col: o.col, lines: o.lines } };

export function same(a, b, at = "") {          // first difference, or null; numbers equal to 1e-9 (relative); a missing field = null
  if (a === undefined) a = null; if (b === undefined) b = null;
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) <= 1e-9 * Math.max(1, Math.abs(a)) ? null : `${at}: ${a} ≠ ${b}`;
  if (a === null || b === null || typeof a !== "object" || typeof b !== "object") return a === b ? null : `${at}: ${JSON.stringify(a)?.slice(0, 160)} ≠ ${JSON.stringify(b)?.slice(0, 160)}`;
  if (Array.isArray(a) !== Array.isArray(b)) return `${at}: array vs object`;
  const ks = new Set([...Object.keys(a), ...Object.keys(b)]);
  for (const k of ks) { const d = same(a[k], b[k], `${at}.${k}`); if (d) return d; }
  return null;
}

// a top-level `function name(...) {...}` or `const name={...}` taken out of a page or script (brace matching, strings skipped)
export function extract(src, start) {
  const i = src.indexOf(start); if (i < 0) return null;
  let k = src.indexOf("{", i), depth = 0, q = null;
  for (let j = k; j < src.length; j++) {
    const ch = src[j];
    if (q) { if (ch === "\\") { j++; continue; } if (ch === q) q = null; else if (q === "`" && ch === "$" && src[j + 1] === "{") { /* template expression: braces balance */ } continue; }
    if (ch === '"' || ch === "'" || ch === "`") { q = ch; continue; }
    if (ch === "{") depth++; else if (ch === "}" && --depth === 0) return src.slice(i, j + 1);
  }
  return null;
}
const fnFrom = (file, name) => { const s = extract(fs.readFileSync(P(file), "utf8"), `function ${name}(`); if (!s) throw Error(`${name} not found in ${file}`);
  return vm.runInNewContext(`(${s})`, PAGE_GLOBALS); };
const PAGE_GLOBALS = { isN: v => typeof v === "number" && isFinite(v), sum: x => x.reduce((p, q) => p + q, 0), last: x => x[x.length - 1] };   // helpers the page functions use
const objFrom = (file, name) => { const src = fs.readFileSync(P(file), "utf8"), m = new RegExp(`(?:const |,)\\s*${name}\\s*=\\s*\\{`).exec(src); if (!m) return null;
  const s = extract(src.slice(m.index + m[0].length - 1), "{"); if (!s) return null;
  return vm.runInNewContext(`(${s})`, {}); };

function python(calls, extra = []) {
  const out = execFileSync("python3", [P("tests/py_bridge.py"), ...extra], { input: JSON.stringify(calls), maxBuffer: 256 << 20 });
  return JSON.parse(out.toString());
}

// ---------- inputs: saved data + variants that reach every branch ----------
export function fixtures() {
  const MK = J("data/market.json"), RG = J("data/regime.json"), MH = J("data/market-history.json"), CH = J("data/crypto-history.json");
  const F = [], CC = [], RGs = [], BTC = [], LIVE = [], CL = [];
  const cyc = (arr, k) => arr[k % arr.length];      // walk a list of values alongside a larger grid
  // values on both sides of every threshold used by the rules (VIX 40, VIX rank 10%, spreads 3 / 4.5 / 5 / 6 / 12 %, ranks 20 / 80 %,
  // 1- and 4-week change thresholds, real yield 2%, rate moves ±0.25 pt, inflation 2.5 / 3.5 % and ±0.3 pt)
  for (const phase of ["calm", "early", "peak", "fading", "fading_unconfirmed", "after"]) for (const vix of [14, 39.9, 40, 40.1]) for (const up of [true, false]) for (const bear of [true, false]) for (const p of [5, 9.9, 10, 11, 60])
    F.push({ ...MK, phase, vix, vix_pct: p, market: { ...(MK.market || {}), above_200d: up, bear_state: bear } });
  F.push(MK, null);
  const base = MK.credit_check || {};
  CC.push(base, null, { ...base, spreads: null }, { hy: { series: "HYG/IEF", chg_1w: -0.4, chg_4w: 1.1 }, spx: { chg_1w: 1, chg_4w: -2 } });
  const HYV = [2.6, 2.99, 3, 3.01, 3.7, 4.49, 4.5, 4.51, 4.99, 5, 5.01, 5.99, 6, 6.01, 7.1], C4 = [-0.9, -0.41, -0.4, -0.39, -0.1, 0, 0.39, 0.4, 0.41, 0.6], C1 = [-0.3, -0.21, -0.2, -0.19, 0, 0.19, 0.2, 0.21, 0.29];
  const PCT = [10, 19, 20, 21, 50, 79, 80, 81, 97], ADJ = [-1.1, -0.99, -0.6, -0.49, 0, 0.26, 0.49, 0.51, 0.99, 1.01];
  const CCC = [null, { value: 12, chg_4w: 1, chg_1w: 0.5 }, { value: 13.9, chg_4w: 1.4, chg_1w: 0.6 }, { value: 9.1, chg_4w: 0.1, chg_1w: 0 }, { value: 11.99, chg_4w: 1.01, chg_1w: -0.49 }, { value: 12.01, chg_4w: 0.99, chg_1w: 0.51 }, { value: 10, chg_4w: -1.2, chg_1w: -0.6 }];
  let k = 0;
  for (const v of HYV) for (const c4 of C4) for (const c1 of C1) { k++;
    const q = cyc(CCC, k), ig = { value: 0.98, chg_1w: cyc([-0.06, -0.04, 0, 0.04, 0.06], k), chg_4w: cyc([-0.11, -0.09, 0, 0.09, 0.11], k + 2), pct_3y: cyc(PCT, k + 3), date: "2026-11-24", stale: k % 5 === 0 };
    CC.push({ ...base, version: k % 17 === 0 ? undefined : base.version,
      spreads: { ...(base.spreads || {}), hy: { value: v, chg_1w: c1, chg_4w: c4, pct_3y: cyc(PCT, k), date: "2026-11-24", stale: k % 3 === 0 }, ig: k % 11 === 0 ? null : ig,
        ccc: q && { ...q, pct_3y: cyc(PCT, k + 5), date: "2026-11-24", stale: k % 4 === 0 } },
      hy_adj: k % 13 === 0 ? null : { chg_1w: cyc(ADJ, k), chg_4w: cyc(ADJ, k + 3) }, ig_adj: { chg_1w: cyc(ADJ, k + 1) / 2, chg_4w: cyc(ADJ, k + 4) / 2 },
      ust10: { value: 4.4, chg_1w: c1, chg_4w: -c4 }, spx: { chg_1w: -c1 * 5, chg_4w: cyc([-6, -2, 0, 2, 6], k) } });
  }
  RGs.push(RG, null, {});
  const INF = [2, 2.49, 2.5, 2.51, 3, 3.49, 3.5, 3.51, 4.2];
  for (const c of [-0.4, -0.26, -0.25, -0.24, 0, 0.24, 0.25, 0.26, 0.4]) for (const inv of [true, false]) for (const r10 of [1.6, 1.99, 2, 2.01, 2.4]) { k++;
    const hot = cyc(INF, k), yo = cyc([hot - 0.31, hot - 0.29, hot + 0.29, hot + 0.31, null], k);
    RGs.push({ ...RG, rates: { ...RG.rates, y2: { ...(RG.rates?.y2 || {}), value: 4.5, chg_1w: +(c * 0.6).toFixed(3), chg_4w: c }   /* not c / 2: an exact half (-0.125) rounds differently in JS (away from zero) and Python (to even) */, y10: { ...(RG.rates?.y10 || {}), value: inv ? 4.2 : 4.8 },
      real10: { ...(RG.rates?.real10 || {}), value: r10, chg_1w: c, chg_4w: k % 9 === 0 ? null : c } },
      inflation: Object.fromEntries(Object.entries(RG.inflation || {}).map(([key, x]) => [key, x && { ...x, ann3m: hot, yoy: yo }])) });
  }
  const btc = CH.assets.btc, fund = CH.funding && CH.funding.btc;
  const fngAt = cut => { const f = (CH.fng || []).filter(r => !cut || r[0] <= cut); return f.length ? f[f.length - 1][1] : null; };   // as index.html passes it
  // cycle tops, bottoms, recoveries and stress periods
  for (const cut of ["2015-01-14", "2017-12-17", "2018-12-15", "2019-06-26", "2020-03-13", "2020-10-21", "2021-04-14", "2021-07-20", "2021-11-10", "2022-06-18",
                     "2022-11-21", "2023-03-10", "2023-10-24", "2024-03-14", "2024-08-05", "2025-04-08", "2025-10-06", null]) {
    const rows = cut ? btc.rows.filter(r => r[0] <= cut) : btc.rows;
    BTC.push([{ ...btc, rows }, cut ? null : fund, fngAt(cut)]);
  }
  BTC.push([CH.assets.eth, null, null], [null, null, null]);
  const R = MH.rows, c = Object.fromEntries(MH.columns.map((k, i) => [k, i]));
  for (let i = R.length - 60; i < R.length; i++) LIVE.push([{ columns: MH.columns, rows: R.slice(0, i) },
    { date: R[i][c.date], vix: R[i][c.vix], vix3m: R[i][c.vix3m], spx: R[i][c.spx], credit: R[i][c.credit] }, R[i][c.phase]]);
  // live credit estimate: saved fund closes (synthetic) and live prices up, down, missing; spread dates inside, before and
  // after the saved window
  const dates = Array.from({ length: 15 }, (_, i) => new Date(Date.UTC(2026, 10, 6 + i)).toISOString().slice(0, 10));
  const fc = { dates, HYG: dates.map((_, i) => 79 + i * 0.03), LQD: dates.map((_, i) => 108 - i * 0.02), IEF: dates.map((_, i) => 95 + i * 0.01), raw_last: { HYG: 78.6, LQD: 107.4, IEF: 94.9 } };
  for (const sd of ["2026-11-18", "2026-11-20", "2026-11-01", "2026-12-01"]) for (const [h, l, i] of [[78.9, 107.9, 95.3], [77.8, 106.2, 94.1], [null, 107.5, 95], [78.6, 107.4, null]])
    CL.push([{ ...base, durations: { HYG: 3.2, LQD: 8.3, IEF: 7.3 }, fund_closes: fc, spreads: { ...(base.spreads || {}),
      hy: { value: 3.72, date: sd, chg_1w: 0.29, chg_4w: 0.54, pct_3y: 97 }, ig: { value: 0.98, date: sd, chg_1w: 0.06, chg_4w: null, pct_3y: 88 }, ccc: { value: 14.05, date: sd, chg_4w: 0.84 } } },
      { HYG: h, LQD: l, IEF: i, t: 1795793000000 }]);
  CL.push([base, { HYG: 78, LQD: 107, IEF: 95 }], [null, null]);
  return { F, CC, RGs, BTC, LIVE, CL, MH };
}

export function checkCopies({ skill = null, log = console.log } = {}) {
  const require = createRequire(import.meta.url), G = require(P("regime.js"));
  const X = fixtures(), problems = [];
  const cases = [];          // [label, js result, python call]
  X.F.forEach((f, i) => cases.push([`fearZone #${i}`, G.fearZone(f), { fn: "regime.fear_zone", args: [f] }]));
  X.CC.forEach((cc, i) => cases.push([`creditZone #${i}`, G.creditZone(cc), { fn: "regime.credit_zone", args: [cc] }]));
  X.RGs.forEach((rg, i) => { cases.push([`ratesRead #${i}`, G.ratesRead(rg), { fn: "regime.rates_read", args: [rg] }]);
    cases.push([`inflationRead #${i}`, G.inflationRead(rg), { fn: "regime.inflation_read", args: [rg] }]); });
  X.BTC.forEach((a, i) => cases.push([`btcCycle #${i}`, G.btcCycle(...a), { fn: "regime.btc_cycle", args: a }]));
  X.LIVE.forEach(([h, live], i) => cases.push([`liveFear ${live.date}`, G.liveFear(h, live), { fn: "regime.live_fear", args: [h, live] }]));
  X.CL.forEach(([cc, live], i) => { const L = G.creditLive(cc, live);
    cases.push([`creditLive #${i}`, L, { fn: "regime.credit_live", args: [cc, live] }]);
    if (L) cases.push([`creditZone(live) #${i}`, G.creditZone(L), { fn: "regime.credit_zone", args: [L] }]); });
  for (const b of [0, 5]) cases.push([`fearAt back=${b}`, G.fearAt(X.MH, b), { fn: "regime.fear_at", args: [X.MH, b] }]);

  const compare = (label, cs, res) => {       // one line per function, with the first differing input
    const by = {};
    cs.forEach(([name, js], i) => { const r = res[i], fn = name.split(/[ #]/)[0] || "creditRead", b = by[fn] = by[fn] || { n: 0, bad: 0, first: null }, V = VIEW[fn] || (x => x);
      const d = r.err ? ` python error ${r.err}` : same(norm(V(norm(js))), norm(V(norm(r.ok))));
      b.n++; if (d) { b.bad++; b.first = b.first || `${name}${d}`; } });
    for (const [fn, b] of Object.entries(by)) {
      log(`${b.bad ? "FAIL" : "ok  "} ${label} ${fn}: ${b.n - b.bad}/${b.n} inputs agree`);
      if (b.bad) problems.push(`${label} ${fn}: ${b.bad} of ${b.n} inputs differ, first: ${b.first}`);
    }
  };
  compare("regime.js ↔ scripts/regime.py", cases, python(cases.map(c => c[2])));

  // creditRead copies
  const CRi = fnFrom("index.html", "creditRead"), CRt = fnFrom("today.html", "creditRead");
  const cr = X.CC.map((cc, i) => [`creditRead #${i}`, CRi(cc)]);
  // the two pages: the whole result must match
  let bad = 0; X.CC.forEach((cc, i) => { const d = same(norm(cr[i][1]), norm(CRt(cc))); if (d) { bad++; if (bad <= 5) problems.push(`creditRead index.html ↔ today.html · #${i}${d}`); } });
  log(`${bad ? "FAIL" : "ok  "} creditRead index.html ↔ today.html: ${X.CC.length - bad}/${X.CC.length} inputs agree`);
  compare("creditRead index.html ↔ weekly_review.py", cr, python(X.CC.map(cc => ({ fn: "weekly.credit_read", args: [cc] }))));

  if (skill) {
    const S = f => path.join(skill, f);
    const eqFile = (a, b, label) => { const ok = fs.existsSync(b) && fs.readFileSync(a, "utf8") === fs.readFileSync(b, "utf8");
      log(`${ok ? "ok  " : "FAIL"} ${label}`); if (!ok) problems.push(`${label}: files differ (or the skill copy is missing)`); };
    eqFile(P("scripts/regime.py"), S("scripts/regime.py"), "scripts/regime.py = skill scripts/regime.py");
    compare("regime.js ↔ skill regime.py", cases, python(cases.map(c => c[2]), ["--regime", S("scripts/regime.py")]));
    const gA = J("data/glossary.json"), gB = fs.existsSync(S("assets/glossary.json")) ? JSON.parse(fs.readFileSync(S("assets/glossary.json"), "utf8")) : null;
    const gd = gB ? same(gA, gB, "glossary") : "skill assets/glossary.json missing";
    log(`${gd ? "FAIL" : "ok  "} data/glossary.json = skill assets/glossary.json`); if (gd) problems.push(gd);
    // glossInit holds regular expressions, so it is cut by position: from its first line to the last "}" before the export line
    const body = (f, end) => { const t = fs.readFileSync(f, "utf8"), i = t.indexOf("function glossInit("), j = t.lastIndexOf("}", t.indexOf(end, i));
      return i < 0 || j < i ? "" : t.slice(i, j + 1).replace(/\s+/g, " ").trim(); };
    const gl = body(P("regime.js"), "W.SGRegime") === body(S("assets/gloss.js"), "W.glossInit") && body(P("regime.js"), "W.SGRegime");
    log(`${gl ? "ok  " : "FAIL"} glossInit in regime.js = skill assets/gloss.js`); if (!gl) problems.push("glossInit: regime.js and skill assets/gloss.js differ");
    const fb = (f, end) => { const t = fs.existsSync(f) ? fs.readFileSync(f, "utf8") : "", i = t.indexOf("function foldInit("), j = t.lastIndexOf("}", t.indexOf(end, i));
      return i < 0 || j < i ? "" : t.slice(i, j + 1).replace(/\s+/g, " ").trim(); };
    const fo = fb(P("regime.js"), "/* ---------- rates and inflation") === fb(S("assets/fold.js"), "W.foldInit") && fb(P("regime.js"), "/* ---------- rates and inflation");
    log(`${fo ? "ok  " : "FAIL"} foldInit in regime.js = skill assets/fold.js`); if (!fo) problems.push("foldInit: regime.js and skill assets/fold.js differ");
    compare("creditRead index.html ↔ skill render.py", cr, python(X.CC.map(cc => ({ fn: "skill_render.credit_read", args: [cc] })), ["--render", S("scripts/render.py")]));
    const K = python([{ fn: "skill_score.consts", args: [] }], ["--score", S("scripts/score.py")])[0];
    if (K.err) problems.push(`skill score.py constants: ${K.err}`);
    else for (const [js, py] of [["WI_S", K.ok.WI], ["LW_S", K.ok.LENS?.balanced], ["LW_F", K.ok.LENS_ETF?.etf], ["LW_C", K.ok.LENS_CRYPTO?.crypto]]) {
      const o = objFrom("index.html", js);
      if (o && "e200" in o) { o.s200 = o.e200; delete o.e200; }   // the page calls the 200-day indicator e200, the skill s200
      // by design: StockGlass has two scores, so the EPS surprise counts once in its entry timing; the skill counts it in its
      // third score (timing + guidance & news) and gives it 0 in timing. Every other weight must match.
      if (js === "WI_S" && o?.surprise && py?.surprise) { o.surprise = [o.surprise[0], 0]; log("     note: WI_S.surprise timing weight differs by design (no third score in StockGlass)"); }
      const z = x => x && Object.fromEntries(Object.entries(x).filter(([, v]) => !(Array.isArray(v) && v.every(w => w === 0))));   // a missing indicator = weight 0
      const d = same(norm(z(o)), norm(z(py)), js);
      log(`${d ? "FAIL" : "ok  "} index.html ${js} = skill score.py`); if (d) problems.push(`weights ${d}`);
    }
  } else log("     (skill copies not checked: run with --skill <stock-verdict folder>)");
  return problems;
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  const i = process.argv.indexOf("--skill"), skill = i > 0 ? path.resolve(process.argv[i + 1]) : null;
  const pr = checkCopies({ skill });
  if (pr.length) { console.log(`\n${pr.length} difference(s):`); pr.forEach(p => console.log("  - " + p)); process.exit(1); }
  console.log("\nAll copies agree.");
}
