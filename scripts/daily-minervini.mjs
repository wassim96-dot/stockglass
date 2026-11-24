// Daily Minervini check (light, context only, never a score): for every stock in watchlist.txt, fetches about two years
// of daily prices (one Yahoo request per ticker, Stooq as a fallback) and runs the SAME trend-template code as the
// StockGlass page (the block between @tt-begin and @tt-end in index.html), with the market-stress check from
// data/market.json. Writes data/daily/<market date>.json, keeps the 5 newest files, updates data/daily/index.json and
// writes alerts/*.title|md when a stock newly meets or loses the template (the workflow turns them into a GitHub issue,
// which the GitHub app pushes to the phone). ETFs, indices and crypto are skipped (the template is for stocks).
// Usage: node scripts/daily-minervini.mjs   (env FORCE=1 re-runs a market date that already has a file)
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const P = f => path.join(ROOT, f);
const read = f => { try { return JSON.parse(fs.readFileSync(P(f), "utf8")); } catch { return null; } };
const KEEP = 5, SITE = "https://wassim96-dot.github.io/stockglass/";
const sleep = ms => new Promise(r => setTimeout(r, ms));
const UA = { "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36" };

fs.rmSync(P("alerts"), { recursive: true, force: true });   // never re-send an old alert

// ---- the page's own template code ----
const html = fs.readFileSync(P("index.html"), "utf8");
const a = html.indexOf("/* @tt-begin"), b = html.indexOf("/* @tt-end */");
if (a < 0 || b < 0) throw new Error("trend-template markers not found in index.html");
const ctx = vm.createContext({ Math, Date, Map, JSON, Number, String, Array, Object, isFinite,
  sum: x => x.reduce((p, q) => p + q, 0), last: x => x[x.length - 1], isN: v => typeof v === "number" && isFinite(v), S: null, MF: null });
vm.runInContext(html.slice(a, b), ctx);

// ---- prices ----
// Yahoo often refuses direct requests from GitHub's servers, so after one direct try per host the request goes
// through the same public relays the StockGlass page uses (allorigins, codetabs, corsproxy, jina).
const RELAYS = [["direct", u => u], ["direct2", u => u.replace("query1", "query2")],
  ["allorigins", u => "https://api.allorigins.win/raw?url=" + encodeURIComponent(u)], ["codetabs", u => "https://api.codetabs.com/v1/proxy?quest=" + encodeURIComponent(u)],
  ["corsproxy", u => "https://corsproxy.io/?url=" + encodeURIComponent(u)], ["jina", u => "https://r.jina.ai/" + u]];
const parseJ = t => { try { return JSON.parse(t); } catch { const i = t.indexOf("{"), k = t.lastIndexOf("}"); return i >= 0 && k > i ? JSON.parse(t.slice(i, k + 1)) : null; } };
const STAT = {};   // which route worked / failed, printed at the end
let order = RELAYS.map(r => r[0]);   // routes that work move to the front
async function yahoo(sym) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=2y&interval=1d`;
  for (const name of [...order]) for (let k = 0; k < (name === order[0] ? 3 : 1); k++) {   // the working route gets 2 retries after throttling
    const w = RELAYS.find(r => r[0] === name)[1];
    try {
      const ac = new AbortController(), to = setTimeout(() => ac.abort(), 15000);
      const r = await fetch(w(url), { headers: UA, signal: ac.signal }); clearTimeout(to);
      const t = r.ok ? await r.text() : "";
      const j = t ? parseJ(t) : null, res = j?.chart?.result?.[0];
      if (res?.timestamp?.length) { STAT[name] = (STAT[name] || 0) + 1; order = [name, ...order.filter(x => x !== name)]; return { res, via: "Yahoo" + (name.startsWith("direct") ? "" : " via " + name) }; }
      if (j?.chart?.error?.code === "Not Found") return null;
      STAT[name + "_fail"] = (STAT[name + "_fail"] || 0) + 1; STAT[name + "_last"] = r.status;
      if (r.status === 429 && k < 2 && name === order[0]) { await sleep(5000 * (k + 1)); continue; }
    } catch (e) { STAT[name + "_fail"] = (STAT[name + "_fail"] || 0) + 1; STAT[name + "_last"] = e.name; }
    await sleep(300); break;
  }
  return null;
}
// Stooq fallback (daily CSV, no key) for the markets it covers; symbols translated from Yahoo's
const STQ = [[/^[A-Z.\-]+$/, s => s.replace("-", ".").toLowerCase() + ".us"], [/\.DE$/, s => s.replace(/\.DE$/, ".de").toLowerCase()],
  [/\.L$/, s => s.replace(/\.L$/, ".uk").toLowerCase()], [/\.WA$/, s => s.replace(/\.WA$/, "").toLowerCase()],
  [/\.HK$/, s => s.replace(/\.HK$/, ".hk").toLowerCase()], [/\.T$/, s => s.replace(/\.T$/, ".jp").toLowerCase()]];
async function stooq(sym) {
  const m = STQ.find(([rx]) => rx.test(sym)); if (!m || sym.includes("^")) return null;
  try {
    const r = await fetch(`https://stooq.com/q/d/l/?s=${encodeURIComponent(m[1](sym))}&i=d`, { headers: UA });
    const t = r.ok ? await r.text() : "";
    if (!/^Date,Open,High,Low,Close/i.test(t)) return null;
    const rows = t.trim().split("\n").slice(1).map(l => l.split(",")).filter(x => x.length >= 5 && +x[4] > 0).slice(-520);
    if (rows.length < 200) return null;
    return { res: { meta: { currency: null, instrumentType: "EQUITY" }, timestamp: rows.map(x => Date.parse(x[0] + "T21:00:00Z") / 1e3),
      indicators: { quote: [{ open: rows.map(x => +x[1]), high: rows.map(x => +x[2]), low: rows.map(x => +x[3]), close: rows.map(x => +x[4]), volume: rows.map(x => x[5] ? +x[5] : null) }] } }, via: "Stooq" };
  } catch { return null; }
}
const bars = res => { const q = (res.indicators.quote || [{}])[0], out = [];
  (res.timestamp || []).forEach((t, i) => { if (q.close && q.close[i] != null) out.push({ t: t * 1e3, c: q.close[i], h: q.high?.[i] ?? q.close[i], l: q.low?.[i] ?? q.close[i], v: q.volume ? q.volume[i] : null }); });
  return out; };
const kindOf = (sym, m) => { const it = String(m?.instrumentType || "").toUpperCase();
  return it === "ETF" || it === "MUTUALFUND" ? "fund" : it === "INDEX" || sym.startsWith("^") ? "index" : it === "CRYPTOCURRENCY" || /-USD$/.test(sym) ? "crypto" : "equity"; };

// ---- watchlist ----
const tickers = [...new Set(fs.readFileSync(P("watchlist.txt"), "utf8").split("\n").map(l => l.replace(/#.*/, "").trim().split(/\s+/)[0]).filter(Boolean))];

// ---- market indexes (same choice as the page: S&P 500 via SPY, S&P/TSX, STOXX Europe 600) ----
const CA_RX = /\.(TO|V)$/i;
const IDX = { us: ["SPY", "S&P 500 (SPY)"], ca: ["^GSPTSE", "S&P/TSX Composite"], eu: ["^STOXX", "STOXX Europe 600"] };
const MK = {};
for (const [k, [sym, name]] of Object.entries(IDX)) {
  const y = await yahoo(sym); await sleep(400);
  if (!y) { MK[k] = null; console.error(`index ${sym}: no data`); continue; }
  const c0 = y.res.indicators.quote[0].close || [], map = new Map();
  (y.res.timestamp || []).forEach((t, i) => { if (c0[i] != null) map.set(new Date(t * 1e3).toISOString().slice(0, 10), c0[i]); });
  const c = [...map.values()], sma = n => c.slice(-n).reduce((p, q) => p + q, 0) / n;
  let mkt = null;
  if (c.length >= 200) { const a2 = sma(200), a5 = sma(50), iv = (c[c.length - 1] / a2 - 1) * 100, up = a5 > a2; mkt = { n: name, iv, up, lab: iv > 0 && up ? "Supportive" : iv < 0 && !up ? "Hostile" : "Mixed" }; }
  MK[k] = { map, name, mkt, last: [...map.keys()].pop() };
}
const day = MK.us?.last || new Date().toISOString().slice(0, 10);   // market date of the run (last S&P 500 bar)
fs.mkdirSync(P("data/daily"), { recursive: true });
const outF = `data/daily/${day}.json`;
if (fs.existsSync(P(outF)) && process.env.FORCE !== "1" && (read(outF)?.counts?.stocks || 0) > 0) { console.log(`${outF} already exists: nothing to do`); process.exit(0); }

const m = read("data/market.json");
const MF = m && m.date && Math.abs(Date.parse(day) - Date.parse(m.date)) < 8 * 864e5 ? m : null;
ctx.MF = MF;

// ---- run ----
const items = [], skipped = [], failed = [];
for (const sym of tickers) {
  let y = await yahoo(sym); if (!y) y = await stooq(sym);
  await sleep(350);
  if (!y) { failed.push(sym); continue; }
  const meta = y.res.meta || {}, kind = kindOf(sym, meta);
  if (kind !== "equity") { skipped.push(sym); continue; }
  const d = bars(y.res), ca = CA_RX.test(sym), us = !ca && !sym.includes("."), mk = MK[ca ? "ca" : us ? "us" : "eu"];
  ctx.S = { kind: "equity", closes: d, price: meta.regularMarketPrice ?? d[d.length - 1]?.c, cur: meta.currency || (us ? "USD" : null),
    mktC: mk?.map || null, mktN: mk?.name || null, benchC: null, benchN: mk?.name || null, mkt: mk?.mkt || null, fear: MF };
  let T = null; try { T = vm.runInContext("trendTemplate()", ctx); } catch (e) { console.error(sym, e.message); }
  if (!T) { failed.push(sym); continue; }
  const p = ctx.S.price, prev = d.length > 1 ? d[d.length - 2].c : null, r1 = v => v == null || !isFinite(v) ? null : Math.round(v * 10) / 10;
  items.push({ t: sym, name: meta.longName || meta.shortName || null, cur: ctx.S.cur, price: p, chg_1d: prev ? r1((d[d.length - 1].c / prev - 1) * 100) : null,
    via: y.via, last_bar: new Date(d[d.length - 1].t).toISOString().slice(0, 10),
    icon: T.verdict[0].slice(0, 2).trim(), verdict: T.verdict[0].replace(/^\S+\s/, ""), passed: T.passed, total: T.total, met: T.met,
    falling_200: T.fall, missing: T.missing, rs_w: r1(T.rsW), stress: T.why,
    stop: T.stop ? { pct: r1(T.stop.pct), over_10: T.stop.over, max_position_pct: Math.round(T.stop.size) } : null,
    rules: T.rules.map(([txt, ok]) => [txt, ok]),
    ctx: { rs_line_high: T.X.rsHigh ?? null, rs_line_leads: T.X.rsLead ?? null, ext_atr: r1(T.X.ext), ext_pct: r1(T.X.extPct), max_1d: r1(T.X.max1d),
      up_vol: T.X.upVol != null ? Math.round(T.X.upVol * 100) / 100 : null, up_day: T.X.upDay ?? null, vol_dry: T.X.dry != null ? Math.round(T.X.dry * 100) / 100 : null,
      turnover_eur: T.X.turnEur != null ? Math.round(T.X.turnEur) : null } });
}

// ---- compare with the previous daily file ----
const idx0 = read("data/daily/index.json") || { files: [] };
const prevDay = (idx0.files || []).filter(f => f < day).sort().pop();
const prevF = prevDay ? read(`data/daily/${prevDay}.json`) : null, pmap = new Map((prevF?.items || []).map(x => [x.t, x]));
const ch = { new_green: [], lost_green: [], new_met: [], lost_met: [], new_falling_200: [] };
for (const x of items) {
  const o = pmap.get(x.t); if (!o) continue;
  if (x.icon === "🟢" && o.icon !== "🟢") ch.new_green.push(x.t);
  if (o.icon === "🟢" && x.icon !== "🟢") ch.lost_green.push(x.t);
  if (x.met && !o.met && x.icon !== "🟢") ch.new_met.push(x.t);
  if (o.met && !x.met && o.icon !== "🟢") ch.lost_met.push(x.t);
  if (x.falling_200 && !o.falling_200) ch.new_falling_200.push(x.t);
}
const cnt = k => items.filter(x => x.icon === k).length;
const out = { date: day, generated: new Date().toISOString(), previous: prevDay || null, version: 1,
  market_fear: MF ? { date: MF.date, phase: MF.phase, phase_label: MF.phase_label, score: MF.score, label: MF.label, vix: MF.vix } : null,
  markets: Object.fromEntries(Object.entries(MK).map(([k, v]) => [k, v?.mkt ? { name: v.name, label: v.mkt.lab, vs_200d: Math.round(v.mkt.iv * 10) / 10, last: v.last } : null])),
  counts: { green: cnt("🟢"), yellow: cnt("🟡"), red: cnt("🔴"), stocks: items.length, skipped: skipped.length, failed: failed.length },
  changes: ch, items, skipped, failed,
  note: "Minervini Trend Template (version 2), same code as the StockGlass card. Context only, not a score, not investment advice." };
console.log("routes:", JSON.stringify(STAT));
if (!items.length) { console.error(`No stock could be priced (${failed.length} failed): nothing saved, no alert.`); process.exit(1); }
fs.writeFileSync(P(outF), JSON.stringify(out));

// ---- keep the 5 newest files ----
const files = fs.readdirSync(P("data/daily")).filter(f => /^\d{4}-\d{2}-\d{2}\.json$/.test(f)).map(f => f.slice(0, 10)).sort().reverse();
for (const f of files.slice(KEEP)) fs.rmSync(P(`data/daily/${f}.json`));
fs.writeFileSync(P("data/daily/index.json"), JSON.stringify({ latest: files[0], files: files.slice(0, KEEP), keep: KEEP }));

// ---- alert when a stock newly meets or loses the template ----
const any = ch.new_green.length || ch.lost_green.length || ch.new_met.length || ch.lost_met.length;
const nm = t => { const x = items.find(i => i.t === t) || pmap.get(t); return x?.name ? `${t} (${x.name})` : t; };
if (any || process.env.TEST_ALERT === "true") {
  const parts = [];
  if (ch.new_green.length) parts.push(`${ch.new_green.length} now meet${ch.new_green.length > 1 ? "" : "s"} it`);
  if (ch.lost_green.length) parts.push(`${ch.lost_green.length} lost it`);
  if (ch.new_met.length) parts.push(`${ch.new_met.length} met under market stress`);
  if (ch.lost_met.length) parts.push(`${ch.lost_met.length} no longer met`);
  const title = any ? `Minervini: ${parts.join(", ")} (${day})` : `Test alert: daily Minervini check is working (${day})`;
  const L = (lab, arr, why) => arr.length ? [`**${lab}**`, ...arr.map(t => { const x = items.find(i => i.t === t); return `- ${nm(t)}${x ? ` · ${x.passed}/${x.total}${x.missing?.length ? ` · missing: ${x.missing.join(", ")}` : ""}${x.stop ? ` · stop guide −${x.stop.pct}%${x.stop.over_10 ? " (too volatile for his 10% max)" : ""}` : ""}` : ""}${why ? ` · ${why}` : ""}`; }), ""] : [];
  const body = [`**Daily Minervini check, market date ${day}**${prevDay ? ` (vs ${prevDay})` : ""}`, "",
    ...L("🟢 Newly meet his Trend Template (a setup filter, not a buy signal)", ch.new_green),
    ...L("🔴 / 🟡 No longer meet it", ch.lost_green),
    ...L("🟡 Template met, but the market is under stress", ch.new_met),
    ...L("No longer met (was under market stress)", ch.lost_met),
    !any ? "This is a test. You will get an issue like this when a stock newly meets or loses the template." : null,
    `Now: 🟢 ${out.counts.green} · 🟡 ${out.counts.yellow} · 🔴 ${out.counts.red} of ${items.length} stocks${MF ? ` · market fear: ${MF.phase_label}` : ""}`, "",
    `Today page: ${SITE}today.html · Rule-based screen on public data, not investment advice.`, "", "@wassim96-dot"].filter(x => x != null).join("\n");
  fs.mkdirSync(P("alerts")); fs.writeFileSync(P("alerts/0.title"), title); fs.writeFileSync(P("alerts/0.md"), body);
}
console.log(`${day}: ${items.length} stocks (🟢 ${out.counts.green} · 🟡 ${out.counts.yellow} · 🔴 ${out.counts.red}), ${skipped.length} skipped, ${failed.length} failed${failed.length ? ": " + failed.join(" ") : ""}; changes ${JSON.stringify(ch)}`);
