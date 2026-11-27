// Shared network code for the StockGlass jobs (27 Nov 2026). One place for timeouts, public relays, Yahoo charts and FRED.
//  - fetchText(url, {timeout}): the timeout covers the whole response, body included (a relay that sends headers and then
//    stalls used to hang the daily Minervini job until GitHub killed it at 30 minutes).
//  - Routes: Yahoo and FRED often refuse GitHub's servers, so a request can go direct or through public relays. A route that
//    fails 4 times in a row with no success is dropped for the rest of the run (it stops wasting a minute per ticker), and a
//    route that works moves to the front.
//  - fred(id, cosd): FRED's API when the FRED_API_KEY secret is set (free key; api.stlouisfed.org), else the graph CSV direct
//    and through the relays. One `fredBudget` per run: once FRED has failed on every route for one series, the other series
//    are not tried in that run (the jobs keep the last good value, up to 5 days), so a FRED outage costs about a minute, not nine.
// Usage: import { fetchText, getJSON, Routes, yahooChart, fred } from "./lib/net.mjs";
export const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36";
export const sleep = ms => new Promise(r => setTimeout(r, ms));
// Last completed US session (YYYY-MM-DD): the last weekday whose 16:15 New York close (VIX settlement) has passed. A US
// holiday is not detected here; it simply has no bars. Jobs drop bars dated after it, so a run during trading hours (GitHub
// starts jobs hours late, or a manual run) never saves half a session as a close.
export function lastUsClose(now = new Date()) {
  const ny = new Date(now.toLocaleString("en-US", { timeZone: "America/New_York" }));
  if (ny.getHours() * 60 + ny.getMinutes() < 16 * 60 + 15) ny.setDate(ny.getDate() - 1);
  while (ny.getDay() === 0 || ny.getDay() === 6) ny.setDate(ny.getDate() - 1);
  return `${ny.getFullYear()}-${String(ny.getMonth() + 1).padStart(2, "0")}-${String(ny.getDate()).padStart(2, "0")}`;
}

export async function fetchText(url, { timeout = 20000, headers = {}, accept } = {}) {
  const ac = new AbortController(), to = setTimeout(() => ac.abort(new Error(`timeout after ${timeout / 1000} s`)), timeout);
  try {
    const r = await fetch(url, { headers: { "user-agent": UA, ...(accept ? { accept } : {}), ...headers }, signal: ac.signal, redirect: "follow" });
    const text = await r.text();                       // still under the same timer
    return { ok: r.ok, status: r.status, text };
  } finally { clearTimeout(to); }
}
export async function getJSON(url, opt = {}) {
  const r = await fetchText(url, { accept: "application/json", ...opt });
  if (!r.ok) throw Error(`HTTP ${r.status} ${r.text.slice(0, 160)}`);
  return JSON.parse(r.text);
}
// JSON inside a relay answer (some relays wrap the body in text)
export const parseLoose = t => { try { return JSON.parse(t); } catch { const i = t.indexOf("{"), k = t.lastIndexOf("}"); try { return i >= 0 && k > i ? JSON.parse(t.slice(i, k + 1)) : null; } catch { return null; } } };

export const RELAYS = {
  direct: u => u,
  allorigins: u => "https://api.allorigins.win/raw?url=" + encodeURIComponent(u),
  codetabs: u => "https://api.codetabs.com/v1/proxy?quest=" + encodeURIComponent(u),
  corsproxy: u => "https://corsproxy.io/?url=" + encodeURIComponent(u),
  jina: u => "https://r.jina.ai/" + u,
};

// An ordered set of routes with a per-run memory of what works.
export class Routes {
  constructor(names, { maxStrikes = 4, timeout = 15000 } = {}) { this.order = [...names]; this.strikes = {}; this.wins = {}; this.maxStrikes = maxStrikes; this.timeout = timeout; this.stat = {}; }
  alive() { return this.order.filter(n => (this.strikes[n] || 0) < this.maxStrikes || this.wins[n]); }
  // try each live route until `accept(text, status)` returns a value; `wrap(name, url)` builds the URL for a route
  async get(url, accept, { wrap = (n, u) => RELAYS[n](u), timeout = this.timeout, accept: acc } = {}) {
    for (const name of this.alive()) {
      try {
        const r = await fetchText(wrap(name, url), { timeout, accept: acc });
        const v = r.ok ? accept(r.text, r.status) : undefined;
        if (v === null) return null;                  // a definite "no such symbol": stop
        if (v !== undefined) { this.wins[name] = (this.wins[name] || 0) + 1; this.strikes[name] = 0; this.order = [name, ...this.order.filter(x => x !== name)];
          this.stat[name] = (this.stat[name] || 0) + 1; return v; }
        this.fail(name, `HTTP ${r.status}`);
      } catch (e) { this.fail(name, e.cause?.code || e.message); }
    }
    return undefined;
  }
  fail(name, why) { this.strikes[name] = (this.strikes[name] || 0) + 1; this.stat[name + "_fail"] = (this.stat[name + "_fail"] || 0) + 1; this.stat[name + "_last"] = why;
    if (this.strikes[name] === this.maxStrikes && !this.wins[name]) console.log(`route ${name} dropped for this run (${why})`); }
}

// Yahoo daily chart: direct (query1, query2) then the relays. Returns the chart result object, null for an unknown symbol,
// undefined when every route failed.
const yRoutes = new Routes(["query1", "query2", "allorigins", "codetabs", "corsproxy", "jina"]);
export async function yahooChart(sym, range = "2y", { timeout } = {}) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(sym)}?range=${range}&interval=1d`;
  return yRoutes.get(url, t => { const j = parseLoose(t), res = j?.chart?.result?.[0];
    if (res?.timestamp?.length) return res; if (j?.chart?.error?.code === "Not Found") return null; return undefined; },
  { wrap: (n, u) => n === "query1" ? u : n === "query2" ? u.replace("query1", "query2") : RELAYS[n](u), timeout });
}
export const yahooStats = () => yRoutes.stat;

// FRED series → Map(date → value), or null.
const fredRoutes = new Routes(["direct", "jina", "allorigins", "codetabs"], { maxStrikes: 2, timeout: 30000 });
export const fredBudget = { failedSeries: 0, maxFailedSeries: 1 };
export async function fred(id, cosd = "2006-01-01") {
  const key = process.env.FRED_API_KEY;
  if (key) {
    try {
      const j = await getJSON(`https://api.stlouisfed.org/fred/series/observations?series_id=${id}&observation_start=${cosd}&file_type=json&api_key=${key}`, { timeout: 30000 });
      const m = new Map((j.observations || []).filter(o => o.value !== "." && !isNaN(+o.value)).map(o => [o.date, +o.value]));
      if (m.size > 30) return m;
    } catch (e) { console.log("FRED API", id, e.message.replace(key, "***").slice(0, 120)); }
  }
  if (fredBudget.failedSeries >= fredBudget.maxFailedSeries) { console.log(`FRED ${id}: skipped (FRED unreachable earlier in this run; last good value kept)`); return null; }
  const base = `https://fred.stlouisfed.org/graph/fredgraph.csv?id=${id}&cosd=${cosd}`;
  const m = await fredRoutes.get(base, t => { const m = new Map(t.trim().split("\n").map(l => l.trim().split(","))
    .filter(x => /^\d{4}-\d{2}-\d{2}$/.test(x[0]) && x[1] && !isNaN(+x[1])).map(x => [x[0], +x[1]])); return m.size > 30 ? m : undefined; }, { accept: "text/csv" });
  if (!m) { fredBudget.failedSeries++; console.log(`FRED ${id}: no route worked (${JSON.stringify(fredRoutes.stat)})`); return null; }
  return m;
}
