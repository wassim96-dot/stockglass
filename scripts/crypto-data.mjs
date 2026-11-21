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
