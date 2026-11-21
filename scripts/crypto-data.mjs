// Crypto data for StockGlass and the stock-verdict skill: on-chain history (Coin Metrics Community, CC BY-NC 4.0),
// perpetual funding (OKX) and the Crypto Fear & Greed Index (alternative.me). Writes data/crypto-history.json.
import fs from "node:fs";
import path from "node:path";
const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36";
const get = async (u, t = 30000) => { const r = await fetch(u, { headers: { "user-agent": UA, accept: "application/json" }, signal: AbortSignal.timeout(t) }); if (!r.ok) throw Error("HTTP " + r.status + " " + (await r.text()).slice(0, 200)); return r.json(); };
const METRICS = ["PriceUSD", "CapMrktCurUSD", "CapMVRVCur", "AdrActCnt", "TxCnt", "HashRate", "SplyCur"];
const watch = fs.readFileSync(path.join(ROOT, "watchlist.txt"), "utf8").split("\n").map(l => l.split("#")[0].trim()).filter(s => /-USD$/.test(s));
const assets = [...new Set(["btc", "eth", ...watch.map(s => s.replace(/-USD$/, "").toLowerCase())])];
const out = { updated: new Date().toISOString(), source: { onchain: "Coin Metrics Community API (CC BY-NC 4.0)", funding: "OKX public API", fng: "alternative.me Crypto Fear & Greed Index" }, assets: {}, funding: {}, fng: null };
for (const a of assets) {
  const rows = []; let url = `https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=${a}&metrics=${METRICS.join(",")}&frequency=1d&start_time=2010-01-01&page_size=10000&ignore_unsupported_errors=true&ignore_forbidden_errors=true`;
  try {
    while (url) { const j = await get(url); for (const d of j.data || []) rows.push([d.time.slice(0, 10), ...METRICS.map(m => d[m] != null ? +(+d[m]).toPrecision(8) : null)]); url = j.next_page_url || null; await new Promise(r => setTimeout(r, 700)); }
    const have = METRICS.filter((m, k) => rows.some(r => r[k + 1] != null));
    out.assets[a] = { columns: ["date", ...METRICS], have, rows };
    console.log(`${a}: ${rows.length} days (${rows[0]?.[0]} → ${rows.at(-1)?.[0]}), metrics: ${have.join(", ")}`);
  } catch (e) { console.log(`${a}: no on-chain data (${e.message.slice(0, 120)})`); }
}
for (const a of assets) {
  try { const j = await get(`https://www.okx.com/api/v5/public/funding-rate-history?instId=${a.toUpperCase()}-USDT-SWAP&limit=100`);
    const v = (j.data || []).map(x => [+x.fundingTime, +x.realizedRate]).sort((p, q) => p[0] - q[0]);
    if (v.length) { out.funding[a] = v; console.log(`${a} funding: ${v.length} periods`); }
  } catch (e) { console.log(`${a} funding: none (${e.message.slice(0, 80)})`); }
}
try { const j = await get("https://api.alternative.me/fng/?limit=0"); out.fng = (j.data || []).map(x => [new Date(+x.timestamp * 1000).toISOString().slice(0, 10), +x.value]).sort(); console.log(`fng: ${out.fng.length} days`); } catch (e) { console.log("fng: none", e.message); }
fs.mkdirSync(path.join(ROOT, "data"), { recursive: true });
fs.writeFileSync(path.join(ROOT, "data", "crypto-history.json"), JSON.stringify(out));

// ---- readings (data/crypto.json): crypto cycle phase per asset; same rule in the skill's scripts/crypto_reading.py ----
// Phase from MVRV (market value / realised value = price / average cost of all coins) and the 200-day average:
//   accumulation: MVRV <= 1 (price below holders' average cost) · distribution: MVRV in the top 10% of its last 4 years
//   bull: price above its 200-day average · bear: price below it. Coins without on-chain data use Bitcoin's phase.
// Scores (backtest 2012–2026 BTC, 2017–2026 ETH, see the skill's references/crypto.md; shrunk towards 5 for few cycles):
export const CPH = {
  accumulation: { lt: 8.5, tm: 6.5, label: "Accumulation", note: "Price is below the average cost of all coins (MVRV ≤ 1): holders are at a loss on average. In 2012–2026 Bitcoin was higher one year later in 98–100% of such days (median +93%); Ethereum in 70–96%. Bottoms form here, but it can last months." },
  bull: { lt: 6, tm: 6, label: "Bull market", note: "Price above its 200-day average with holders in profit but not euphoric: the trend phase of the cycle." },
  bear: { lt: 3.5, tm: 4, label: "Bear market", note: "Price below its 200-day average while holders are still in profit on average (MVRV > 1): historically weak — Bitcoin's median one-year return from such days was −9%, Ethereum's −26%. The cycle usually ends with a drop into accumulation (price under the average cost)." },
  distribution: { lt: 3.5, tm: 5, label: "Distribution", note: "MVRV in the top 10% of its last 4 years: holders sit on large profits and long-term holders sell into strength. Momentum can carry prices higher for weeks, but one-year returns from here have been poor since 2019." }
};
const pctOf = (arr, x) => arr.filter(a => a < x).length / arr.length;
export function cycleReading(rows, cols) {   // rows: [date, ...METRICS]
  const c = Object.fromEntries(cols.map((k, i) => [k, i])), R = rows.filter(r => r[c.PriceUSD] != null);
  if (R.length < 250) return null;
  const i = R.length - 1, x = R[i], px = x[c.PriceUSD], w200 = R.slice(-200), ma200 = w200.reduce((a, r) => a + r[c.PriceUSD], 0) / 200;
  const out = { date: x[0], price: px, ma200: +ma200.toPrecision(6), above_200d: px > ma200, ret_1y: R[i - 365] ? +((px / R[i - 365][c.PriceUSD] - 1) * 100).toFixed(1) : null };
  const M = R.map(r => r[c.CapMVRVCur]);
  if (M[i] != null && R.length >= 730) {
    const hist = M.slice(Math.max(0, i - 1460), i + 1).filter(v => v != null), mp = pctOf(hist, M[i]);
    const ph = M[i] <= 1 ? "accumulation" : mp >= .9 ? "distribution" : px > ma200 ? "bull" : "bear";
    const adr = R.map(r => r[c.AdrActCnt]), a30 = adr.slice(-30), a30y = adr.slice(i - 394, i - 364);
    const adg = a30.every(v => v) && a30y.length === 30 && a30y.every(v => v) ? (a30.reduce((p, q) => p + q, 0) / a30y.reduce((p, q) => p + q, 0) - 1) * 100 : null;
    Object.assign(out, { mvrv: +M[i].toFixed(3), mvrv_pct_4y: Math.round(mp * 100), realized_price: +(px / M[i]).toPrecision(6), phase: ph, phase_source: "own on-chain data", adr_growth_1y: adg != null ? +adg.toFixed(1) : null });
  }
  return out;
}
const RD = { updated: out.updated, method: "Crypto cycle phase: accumulation (MVRV ≤ 1), distribution (MVRV in the top 10% of its last 4 years), else bull (price above its 200-day average) or bear. Coins without on-chain data use Bitcoin's phase. Long-term phase scores: accumulation 8.5, bull 6, bear 3.5, distribution 3.5; timing: 6.5, 6, 4, 5.", phases: CPH, assets: {} };
for (const [a, A] of Object.entries(out.assets)) RD.assets[a] = cycleReading(A.rows, A.columns);
const btc = RD.assets.btc;
for (const a of Object.keys(RD.assets)) { const r = RD.assets[a]; if (r && !r.phase && btc?.phase) Object.assign(r, { phase: btc.phase, phase_source: "Bitcoin's cycle (no on-chain data for this coin)" }); }
for (const [a, v] of Object.entries(out.funding)) { const last = v.slice(-21); if (RD.assets[a] && last.length) RD.assets[a].funding_annual = +(last.reduce((p, q) => p + q[1], 0) / last.length * 3 * 365 * 100).toFixed(1); }
if (out.fng?.length) { const f = out.fng.at(-1); RD.fng = { date: f[0], value: f[1] }; }
fs.writeFileSync(path.join(ROOT, "data", "crypto.json"), JSON.stringify(RD, null, 1));
console.log("readings:", Object.entries(RD.assets).map(([a, r]) => `${a} ${r?.phase} (MVRV ${r?.mvrv ?? "–"}, ${r?.phase_source || ""})`).join("; "));
