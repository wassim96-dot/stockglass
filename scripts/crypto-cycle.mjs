// Crypto cycle phase (pure functions, no network): used by scripts/crypto-data.mjs; same rule in the skill's crypto_reading.py.
// Phase from MVRV (market value / realised value = price / average cost of all coins) and the 200-day average:
//   accumulation: MVRV <= 1 · distribution: MVRV in the top 10% of its last 4 years · bull: price above its 200-day
//   average · bear: below it. Phase age: days since the current phase began, ignoring interruptions shorter than
//   GAP days (MVRV often crosses 1 back and forth). Past accumulation phases (merged the same way, at least 5 days)
//   are listed so the current one can be compared with them.
export const GAP = 14;
const pctOf = (arr, x) => arr.filter(a => a < x).length / arr.length;
export function phaseSeries(R, c) {
  const P = R.map(r => r[c.PriceUSD]), M = R.map(r => r[c.CapMVRVCur]), out = new Array(R.length).fill(null);
  let s200 = 0;
  for (let i = 0; i < R.length; i++) {
    s200 += P[i]; if (i >= 200) s200 -= P[i - 200];
    if (i < 730 || M[i] == null || i < 199) continue;
    const hist = M.slice(Math.max(0, i - 1460), i + 1).filter(v => v != null), mp = pctOf(hist, M[i]);
    out[i] = M[i] <= 1 ? "accumulation" : mp >= .9 ? "distribution" : P[i] > s200 / 200 ? "bull" : "bear";
  }
  return out;
}
export function phaseAge(ph, R, c, i = ph.length - 1) {
  const cur = ph[i]; if (!cur) return null;
  let s = i, miss = 0;
  for (let k = i - 1; k >= 0 && ph[k] != null; k--) { if (ph[k] === cur) { s = k; miss = 0; } else if (++miss >= GAP) break; }
  const d0 = Date.parse(R[s][0]), d1 = Date.parse(R[i][0]), p0 = R[s][c.PriceUSD], p1 = R[i][c.PriceUSD];
  return { since: R[s][0], days: Math.round((d1 - d0) / 864e5) + 1, price_at_start: +p0.toPrecision(6), change_since_start: +((p1 / p0 - 1) * 100).toFixed(1) };
}
export function pastEpisodes(ph, R, c, phase = "accumulation", lastIdx = ph.length - 1) {
  const eps = []; let cur = null, miss = 0;
  for (let i = 0; i <= lastIdx; i++) {
    if (ph[i] === phase) { if (cur) cur[1] = i; else cur = [i, i]; miss = 0; }
    else if (cur && ++miss >= GAP) { eps.push(cur); cur = null; }
  }
  if (cur && cur[1] < lastIdx - GAP) eps.push(cur);   // an episode still running at lastIdx is the current one, not a past one
  return eps.filter(([a, b]) => b - a >= 4).map(([a, b]) => {
    const seg = R.slice(a, b + 1).map(r => r[c.PriceUSD]), lo = Math.min(...seg);
    return { start: R[a][0], end: R[b][0], days: Math.round((Date.parse(R[b][0]) - Date.parse(R[a][0])) / 864e5) + 1, low_vs_start: +((lo / R[a][c.PriceUSD] - 1) * 100).toFixed(0) };
  });
}
export function cycleReading(rows, cols) {   // rows: [date, ...METRICS]
  const c = Object.fromEntries(cols.map((k, i) => [k, i])), R = rows.filter(r => r[c.PriceUSD] != null);
  if (R.length < 250) return null;
  const i = R.length - 1, x = R[i], px = x[c.PriceUSD], w200 = R.slice(-200), ma200 = w200.reduce((a, r) => a + r[c.PriceUSD], 0) / 200;
  const out = { date: x[0], price: px, ma200: +ma200.toPrecision(6), above_200d: px > ma200, ret_1y: R[i - 365] ? +((px / R[i - 365][c.PriceUSD] - 1) * 100).toFixed(1) : null };
  const M = R.map(r => r[c.CapMVRVCur]);
  if (M[i] != null && R.length >= 730) {
    const ph = phaseSeries(R, c), cur = ph[i], hist = M.slice(Math.max(0, i - 1460), i + 1).filter(v => v != null), mp = pctOf(hist, M[i]);
    const adr = R.map(r => r[c.AdrActCnt]), a30 = adr.slice(-30), a30y = adr.slice(i - 394, i - 364);
    const adg = a30.every(v => v) && a30y.length === 30 && a30y.every(v => v) ? (a30.reduce((p, q) => p + q, 0) / a30y.reduce((p, q) => p + q, 0) - 1) * 100 : null;
    const past = pastEpisodes(ph, R, c, "accumulation"), L = past.map(e => e.days).sort((a, b) => a - b);
    Object.assign(out, { mvrv: +M[i].toFixed(3), mvrv_pct_4y: Math.round(mp * 100), realized_price: +(px / M[i]).toPrecision(6), phase: cur, phase_source: "own on-chain data",
      phase_age: phaseAge(ph, R, c), adr_growth_1y: adg != null ? +adg.toFixed(1) : null,
      past_accumulation: { episodes: past, median_days: L.length ? L[Math.floor((L.length - 1) / 2)] : null, min_days: L[0] ?? null, max_days: L.at(-1) ?? null } });
  }
  return out;
}
