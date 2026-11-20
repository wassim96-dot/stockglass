// One-off probe: which ETF / index / crypto data do StockGlass's sources return from GitHub's servers?
import fs from "node:fs";
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36";
const SYMS = ["EUNL.DE", "VDE", "MEUD.PA", "EXV4.DE", "^GSPC", "BTC-USD", "AAPL"];
const out = {};
async function get(url, opt = {}) {
  const t0 = Date.now();
  try {
    const r = await fetch(url, { headers: { "user-agent": UA, accept: "*/*", ...(opt.h || {}) }, signal: AbortSignal.timeout(20000) });
    const tx = await r.text();
    return { status: r.status, ms: Date.now() - t0, len: tx.length, head: tx.slice(0, 400), tx, setCookie: r.headers.get("set-cookie") };
  } catch (e) { return { status: "ERR " + e.message, ms: Date.now() - t0 }; }
}
const keep = (r, extra = {}) => ({ status: r.status, ms: r.ms, len: r.len, head: r.head, ...extra });
// crumb flow
let crumb = null, cookie = null;
{ const a = await get("https://fc.yahoo.com/"); cookie = (a.setCookie || "").split(";")[0];
  const b = await get("https://query2.finance.yahoo.com/v1/test/getcrumb", { h: { cookie } });
  crumb = b.status === 200 ? b.tx.trim() : null; out._crumb = { cookie: !!cookie, status: b.status, crumb: crumb ? crumb.slice(0, 4) + "…" : null }; }
const MODS = "price,summaryDetail,defaultKeyStatistics,fundProfile,topHoldings,fundPerformance,assetProfile";
for (const s of SYMS) {
  const e = encodeURIComponent(s), o = out[s] = {};
  const ch = await get(`https://query1.finance.yahoo.com/v8/finance/chart/${e}?range=5y&interval=1wk&events=div`);
  try { const m = JSON.parse(ch.tx).chart.result[0].meta; o.chart = { status: ch.status, instrumentType: m.instrumentType, currency: m.currency, name: m.longName || m.shortName, exch: m.fullExchangeName, n: JSON.parse(ch.tx).chart.result[0].timestamp.length }; } catch { o.chart = keep(ch); }
  const q0 = await get(`https://query2.finance.yahoo.com/v10/finance/quoteSummary/${e}?modules=${MODS}`);
  o.qs_nocrumb = keep(q0);
  if (crumb) { const q1 = await get(`https://query2.finance.yahoo.com/v10/finance/quoteSummary/${e}?modules=${MODS}&crumb=${encodeURIComponent(crumb)}`, { h: { cookie } });
    o.qs_crumb = { status: q1.status, len: q1.len };
    try { const r = JSON.parse(q1.tx).quoteSummary.result[0]; o.qs_crumb.modules = Object.keys(r);
      o.qs_crumb.sample = { fundProfile: r.fundProfile, topHoldings: r.topHoldings && { n: (r.topHoldings.holdings || []).length, top: (r.topHoldings.holdings || []).slice(0, 3), equityHoldings: r.topHoldings.equityHoldings, sectorWeightings: (r.topHoldings.sectorWeightings || []).length },
        summaryDetail: r.summaryDetail && Object.fromEntries(Object.entries(r.summaryDetail).filter(([k]) => /yield|totalAssets|navPrice|trailingPE|beta|expense|averageVolume|ytd/i.test(k))),
        defaultKeyStatistics: r.defaultKeyStatistics && Object.fromEntries(Object.entries(r.defaultKeyStatistics).filter(([k]) => /yield|totalAssets|beta|fundInception|ytd|threeYear|fiveYear|annualReportExpenseRatio|category|fundFamily|legalType/i.test(k))),
        fundPerformance: r.fundPerformance && { trailing: r.fundPerformance.trailingReturns, risk: (r.fundPerformance.riskOverviewStatistics || {}).riskStatistics } };
    } catch { o.qs_crumb.head = q1.head; } }
  for (const [n, w] of [["allorigins", u => "https://api.allorigins.win/raw?url=" + encodeURIComponent(u)], ["codetabs", u => "https://api.codetabs.com/v1/proxy?quest=" + encodeURIComponent(u)], ["corsproxy", u => "https://corsproxy.io/?url=" + encodeURIComponent(u)]]) {
    const r = await get(w(`https://query2.finance.yahoo.com/v10/finance/quoteSummary/${e}?modules=fundProfile,topHoldings`)); o["qs_via_" + n] = { status: r.status, head: (r.head || "").slice(0, 160) };
  }
  const j1 = await get(`https://r.jina.ai/https://finance.yahoo.com/quote/${e}/`);
  o.jina_quote = { status: j1.status, len: j1.len, hits: j1.tx ? ["Expense Ratio", "Net Assets", "NAV", "PE Ratio", "Yield", "Beta", "YTD", "Inception", "Avg. Volume"].filter(k => j1.tx.includes(k)) : [],
    snippet: j1.tx ? (j1.tx.match(/(Previous Close[\s\S]{0,1400})/) || [""])[0] : null };
  const j2 = await get(`https://r.jina.ai/https://finance.yahoo.com/quote/${e}/holdings/`);
  o.jina_holdings = { status: j2.status, len: j2.len, hits: j2.tx ? ["Top 10 Holdings", "Sector Weightings", "Price/Earnings", "Price/Book", "Overall Portfolio Composition", "Bond Ratings"].filter(k => j2.tx.includes(k)) : [],
    snippet: j2.tx ? (j2.tx.match(/(Overall Portfolio Composition[\s\S]{0,2200})/) || j2.tx.match(/(Top 10 Holdings[\s\S]{0,1500})/) || [""])[0] : null };
  const j3 = await get(`https://r.jina.ai/https://finance.yahoo.com/quote/${e}/performance/`);
  o.jina_perf = { status: j3.status, len: j3.len, snippet: j3.tx ? (j3.tx.match(/(Trailing Returns[\s\S]{0,1500})/) || j3.tx.match(/(Risk Statistics[\s\S]{0,1200})/) || [""])[0] : null };
  if (!s.includes(".") && !s.startsWith("^") && !s.includes("-")) for (const p of ["info?assetclass=etf", "summary?assetclass=etf", "holdings?assetclass=etf"]) {
    const r = await get(`https://api.nasdaq.com/api/quote/${e}/${p}`, { h: { accept: "application/json", origin: "https://www.nasdaq.com", referer: "https://www.nasdaq.com/" } }); o["nasdaq_" + p.split("?")[0]] = { status: r.status, len: r.len, head: (r.head || "").slice(0, 400) };
  }
  await new Promise(r => setTimeout(r, 3000));
}
fs.writeFileSync("probe/result.json", JSON.stringify(out, null, 1));
console.log(JSON.stringify(out, null, 1).slice(0, 20000));
