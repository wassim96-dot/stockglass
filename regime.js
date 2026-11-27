/* StockGlass shared module (27 Nov 2026), loaded by index.html and today.html; the stock-verdict skill has the same rules in
   scripts/regime.py. Nothing here changes a score except liveFear(), which recomputes the market-fear reading from today's quotes
   with the exact rules of scripts/market-fear.mjs (the nightly job), so the entry-timing score uses the live reading and the saved
   readings are shown for comparison.
   - liveFear(hist, live): fear phase and score for a live row appended to data/market-history.json
   - fearAt(hist, i): score of a saved row (for "vs last close" and "vs a week ago")
   - fearZone(F), creditZone(cc): plain, colour-coded readings vs history (near a bottom, bull run, bearish risk); not forecasts
   - ratesRead(rg), inflationRead(rg): Market Regime panel lines from data/regime.json
   - btcCycle(asset, funding, fng): BTC Cycle panel (unscored), from data/crypto-history.json (Coin Metrics Community)
   - glossInit(G): tap any indicator or line to open a short beginner explanation (data/glossary.json, same file as the skill) */
(function (W) {
  "use strict";
  const PH = { calm: [5, "Calm"], early: [5, "Early fear"], peak: [5.5, "Peak stress"], fading: [7.5, "Fading fear (confirmed)"], fading_unconfirmed: [5.5, "Fading fear (unconfirmed)"], after: [4.5, "After fear"] };
  const STRESS = new Set(["early", "peak", "fading", "fading_unconfirmed"]);
  const isN = v => typeof v === "number" && isFinite(v);
  const C = { good: "var(--good)", bad: "var(--bad)", warn: "var(--warn)", ink: "var(--ink2)" };

  /* ---------- market fear ---------- */
  function rowsOf(hist) {
    const c = {}; hist.columns.forEach((k, i) => c[k] = i);
    return hist.rows.map(r => ({ date: r[c.date], vix: r[c.vix], vix3m: r[c.vix3m], spx: r[c.spx], rvhar: r[c.rvhar], vrp: r[c.vrp], credit: r[c.credit], phase: r[c.phase], bear: !!r[c.bear] }));
  }
  function scoreAt(R, i, vrp) {          // premium percentile over the last 10 years (5 if less), same as reading()
    const n = i + 1, win = R.slice(Math.max(0, n - (n >= 2520 ? 2520 : 1260)), n), v = vrp ?? R[i].vrp;
    const pv = win.filter(s => s.vrp < v).length / win.length, pk = win.filter(s => s.vix < R[i].vix).length / win.length;
    const prem = 3 + 4 * pv, ph = PH[R[i].phase][0], score = +(0.3 * prem + 0.7 * ph).toFixed(1);
    return { pv, pk, prem, ph, score, label: score >= 6.5 ? "Supportive" : score <= 4.5 ? "Unsupportive" : "Neutral", years: win.length / 252 };
  }
  function fearAt(hist, back = 0) {
    const R = rowsOf(hist).filter(r => r.vrp != null), i = R.length - 1 - back; if (i < 300) return null;
    const s = scoreAt(R, i);
    return { date: R[i].date, vix: R[i].vix, phase: R[i].phase, phase_label: PH[R[i].phase][1], score: s.score, label: s.label, vix_pct: Math.round(s.pk * 100), vrp_pct: Math.round(s.pv * 100) };
  }
  /* live = {date, vix, vix3m?, spx?, credit? (HYG/IEF ratio), t} — missing pieces fall back to the last close */
  function liveFear(hist, live) {
    let R = rowsOf(hist).filter(r => r.vrp != null); if (R.length < 600 || !live || !isN(live.vix)) return null;
    if (R[R.length - 1].date >= live.date) R = R.slice(0, -1);   // today's close already saved: recompute today from the live quotes
    const P = R[R.length - 1];
    const L = { date: live.date, vix: live.vix, vix3m: isN(live.vix3m) ? live.vix3m : P.vix3m, spx: isN(live.spx) ? live.spx : P.spx, credit: isN(live.credit) ? live.credit : P.credit, rvhar: P.rvhar };
    L.vrp = L.vix * L.vix - L.rvhar;
    const A = R.concat([L]), i = A.length - 1, yr = A.slice(Math.max(0, i - 251), i + 1);
    const pct = (arr, x) => arr.filter(a => a < x).length / arr.length;
    const stress = (L.vix3m && L.vix / L.vix3m > 1) || pct(yr.map(x => x.vix), L.vix) >= 0.9;
    const hi52 = Math.max(...yr.map(x => x.spx)), ago = A[i - 251] && A[i - 251].spx;
    L.bear = L.spx < 0.85 * hi52 && ago != null && L.spx < ago;
    L.new_low5 = A.slice(i - 4, i + 1).some((x, k) => { const at = i - 4 + k; return x.spx <= Math.min(...A.slice(Math.max(0, at - 19), at + 1).map(y => y.spx)); });
    const cw = A.slice(i - 19, i + 1).map(x => x.credit).filter(x => x != null);
    L.credit_easing = L.credit == null || cw.length < 10 ? null : L.credit > Math.min(...cw);
    let age = 0, peak = 0, last = -999;
    for (let k = R.length - 1; k >= 0 && STRESS.has(R[k].phase); k--) { age++; peak = Math.max(peak, R[k].vix); }
    for (let k = R.length - 1; k >= 0; k--) if (STRESS.has(R[k].phase)) { last = k; break; }
    if (stress) { age = age ? age + 1 : 1; peak = age === 1 ? L.vix : Math.max(peak, L.vix); } else age = 0;
    if (!stress) L.phase = i - last <= 20 ? "after" : "calm";
    else if (age <= 5 && L.vix >= 0.95 * peak) L.phase = "early";
    else if (L.vix <= 0.85 * peak) L.phase = (L.credit_easing !== false && !L.new_low5 && !L.bear) ? "fading" : "fading_unconfirmed";
    else L.phase = "peak";
    const s = scoreAt(A, i), w200 = A.slice(-200), ma200 = w200.reduce((a, x) => a + x.spx, 0) / w200.length, a24 = A[i - 504] && A[i - 504].spx;
    return { live: true, t: live.t, date: L.date, vix: +L.vix.toFixed(2), vix3m: L.vix3m != null ? +(+L.vix3m).toFixed(2) : null, vix_vix3m: L.vix3m ? +(L.vix / L.vix3m).toFixed(3) : null,
      vrp: +L.vrp.toFixed(1), vrp_pct: Math.round(s.pv * 100), vix_pct: Math.round(s.pk * 100), window_years: +s.years.toFixed(1), phase: L.phase, phase_label: PH[L.phase][1],
      stress_days: age, vix_peak: stress ? peak : null, risk_flag: L.phase === "early", premium_score: +s.prem.toFixed(1), phase_score: s.ph, score: s.score, label: s.label,
      fading_checks: L.phase.startsWith("fading") ? { credit_easing: L.credit_easing, new_low_5d: L.new_low5, bear_state: L.bear } : null,
      market: { index: "S&P 500", above_200d: L.spx > ma200, ret_24m: a24 ? +((L.spx / a24 - 1) * 100).toFixed(1) : null, bear_state: L.bear },
      used: { vix3m: isN(live.vix3m), spx: isN(live.spx), credit: isN(live.credit) } };
  }

  /* ---------- historical zones (context, never scored) ---------- */
  function fearZone(F) {
    if (!F) return null;
    const v = F.vix, p = F.vix_pct, up = F.market && F.market.above_200d, bear = F.market && F.market.bear_state;
    let z;
    if (F.phase === "early") z = ["Bearish phase starting", C.bad, "Fear has just begun. In past stress episodes the first days were not the bottom: the deepest follow-on drops came from here."];
    else if (F.phase === "peak" && v >= 40) z = ["Panic zone: near a bottom, not confirmed", C.warn, "VIX closes above 40 came near the 2008–09, 2010, 2011, 2020 and 2025 lows, but in late 2008 prices still fell much further after the first one."];
    else if (F.phase === "peak") z = ["Stress peak: possible bottom area", C.warn, "Past bottoms formed around such stress peaks, often after a retest of the low. No confirmation yet."];
    else if (F.phase === "fading") z = ["Bottoming process confirmed", C.good, "Fear is fading with credit stable and no new low: historically how recoveries started (2009, 2016, 2020, 2022–23). Not a guarantee."];
    else if (F.phase === "fading_unconfirmed") z = ["Possible bottom forming, not confirmed", C.warn, "Fear is easing, but credit is still widening, the market made a new low or it is in a bear state: in 2008 and 2022 such pauses were followed by new lows."];
    else if (F.phase === "after") z = ["Recovery stage after stress", C.ink, "Stress ended within the last month; returns right after have been below average."];
    else if (up && p != null && p <= 10) z = ["Late bull: complacency", C.warn, "Very low VIX with the market in an uptrend. Sharp corrections have started from such calm (January 2018, July 2024)."];
    else if (up && !bear) z = ["Bull-market conditions", C.good, "Calm volatility with the S&P 500 above its 200-day average: the usual backdrop of bull runs."];
    else z = ["Quiet downtrend", C.bad, "Calm volatility but the S&P 500 below its 200-day average: bear markets have calm stretches too."];
    if (bear) z[2] += " Bear state: the S&P 500 is more than 15% below its 52-week high with a negative 12-month return.";
    return { tag: z[0], col: z[1], txt: z[2] + " Based on history, not a forecast." };
  }
  function creditZone(cc) {
    const sp = cc && cc.spreads, H = sp && sp.hy; if (!H || !isN(H.value)) return null;
    const lv = H.value, c4 = H.chg_4w, c1 = H.chg_1w, wid = (isN(c4) && c4 >= 0.4) || (isN(c1) && c1 >= 0.2), nar = isN(c4) && c4 <= -0.4;
    let z;
    if (wid && lv < 4.5) z = ["Bearish risk: stress building from tight levels", C.bad, `The high-yield spread (${lv.toFixed(2)}%) is widening from a tight level. In 2007, 2015 and early 2022 this came before or with stock declines.`];
    else if (wid) z = ["Credit stress, still widening", C.bad, `The high-yield spread (${lv.toFixed(2)}%) is high and still rising. In 2008, 2011, 2015–16 and 2020 stocks bottomed only once spreads stopped widening.`];
    else if (nar && lv >= 5) z = ["Spreads turning down from stress: near a bottom", C.good, `The high-yield spread (${lv.toFixed(2)}%) is falling from a stress level. Stock-market bottoms came within about three months of the spread peak in 2009, 2016, 2020 and 2022.`];
    else if (nar) z = ["Credit easing", C.good, "Spreads are narrowing: lenders are calmer, consistent with a healthy or recovering market."];
    else if (lv < 3) z = ["Late cycle: very tight spreads", C.warn, `At ${lv.toFixed(2)}% lenders ask little extra yield: complacency with little cushion (as in 2007, 2021 and late 2024).`];
    else if (lv >= 6) z = ["High but stable spreads", C.warn, "Stress has paused. A turn lower would be the classic confirmation of a bottom."];
    else z = ["Normal credit conditions", C.ink, "Spreads near normal levels (long-run average about 5%): no stress signal."];
    const Q = sp.ccc;
    if (Q && isN(Q.chg_4w) && isN(c4) && Q.chg_4w >= 1 && Q.chg_4w > 2 * c4) z[2] += ` The riskiest bonds (CCC, ${Q.value.toFixed(2)}%) widen fastest (+${Q.chg_4w.toFixed(2)} pt in 4 weeks): stress is concentrated in weak borrowers.`;
    else if (Q && isN(Q.value) && Q.value >= 12) z[2] += ` CCC spreads at ${Q.value.toFixed(2)}% signal serious stress among weak borrowers.`;
    return { tag: z[0], col: z[1], txt: z[2] + " Based on history (ICE BofA since 1996), not a forecast." };
  }

  /* ---------- rates and inflation (data/regime.json) ---------- */
  const pt = v => !isN(v) ? "∅" : (v >= 0 ? "+" : "") + v.toFixed(2) + " pt", pc = (v, d = 1) => !isN(v) ? "∅" : (v >= 0 ? "+" : "") + v.toFixed(d) + "%";
  function ratesRead(rg, live) {
    const R = rg && rg.rates; if (!R) return [];
    const L = [], y2 = R.y2, r10 = R.real10, y10 = R.y10;
    if (y2) { const c = y2.chg_4w, k = !isN(c) ? "neu" : c >= .25 ? "neg" : c <= -.25 ? "pos" : "neu";
      L.push(["2-year Treasury yield", `${y2.value.toFixed(2)}% · ${pt(y2.chg_1w)} over 1 week, ${pt(c)} over 4 weeks`, k, k === "neg" ? "markets price higher Fed rates (hawkish): a headwind" : k === "pos" ? "markets price lower Fed rates; if stocks fall too, a growth scare" : "little change in expected Fed rates"]); }
    if (r10) { const c = r10.chg_4w, hi = r10.value >= 2, k = !isN(c) ? (hi ? "neg" : "neu") : c >= .25 ? "neg" : c <= -.25 ? "pos" : hi ? "neg" : "neu";
      L.push(["10-year real yield", `${r10.value.toFixed(2)}% · ${pt(r10.chg_1w)} over 1 week, ${pt(c)} over 4 weeks`, k, (isN(c) && c >= .25 ? "rising real rates weigh on valuations, most on growth stocks" : isN(c) && c <= -.25 ? "falling real rates support valuations" : hi ? "above 2%: restrictive for valuations" : "no strong pressure on valuations") + (hi && isN(c) && Math.abs(c) >= .25 ? " (level above 2% = restrictive)" : "")]); }
    if (y10 && y2) { const sl = +(y10.value - y2.value).toFixed(2), k = sl < 0 ? "neg" : "neu";
      L.push(["Yield curve (10-year − 2-year)", `${pt(sl)}${live && isN(live.y10) ? ` · live 10-year ${live.y10.toFixed(2)}%` : ""}`, k, sl < 0 ? "inverted: a classic recession warning, with long lags" : sl < .5 ? "flat to slightly positive" : "positive: normal shape"]); }
    return L;
  }
  function inflationRead(rg) {
    const I = rg && rg.inflation; if (!I) return [];
    const L = [], line = (key, nm, hot, cool) => { const x = I[key]; if (!x) return;
      const k = isN(x.ann3m) ? (x.ann3m >= hot ? "neg" : x.ann3m <= cool ? "pos" : "neu") : "neu", acc = isN(x.ann3m) && isN(x.yoy) ? (x.ann3m > x.yoy + .3 ? "accelerating" : x.ann3m < x.yoy - .3 ? "decelerating" : "steady") : null;
      L.push([nm, `${x.month}: ${pc(x.mom, 1)} on the month${isN(x.yoy) ? `, ${pc(x.yoy, 1)} on the year` : ", yearly change not published"}${isN(x.ann3m) ? `, 3-month pace ${pc(x.ann3m, 1)}/yr` : ""}${isN(x.prev_mom) ? ` (previous month ${pc(x.prev_mom, 1)})` : ""}`, k,
        (k === "neg" ? "running hot: keeps pressure on rates" : k === "pos" ? "cooling: room for lower rates" : "near the upper end of normal") + (acc ? `; ${acc}` : "")]); };
    line("cpce", "Core PCE inflation", 3.5, 2.5); line("pce", "PCE inflation", 3.5, 2.5); line("ccpi", "Core CPI", 3.5, 2.5); line("cpi", "CPI inflation", 3.5, 2.5); line("ppi", "PPI (producer prices)", 4, 2);
    return L;
  }

  /* ---------- BTC cycle (unscored) ---------- */
  function btcCycle(A, funding, fng) {
    if (!A || !A.rows) return null;
    const c = {}; A.columns.forEach((k, i) => c[k] = i);
    const R = A.rows.filter(r => r[c.PriceUSD]); if (R.length < 400) return null;
    const P = R.map(r => r[c.PriceUSD]), M = R.map(r => r[c.CapMVRVCur]), n = P.length - 1, px = P[n];
    const ma = (k, i = n) => { let s = 0; for (let j = i - k + 1; j <= i; j++) s += P[j]; return s / k; };
    const m200 = ma(200), m50 = ma(50), lr = []; for (let j = n - 89; j <= n; j++) lr.push(Math.log(P[j] / P[j - 1]));
    const sd = a => { const m = a.reduce((x, y) => x + y, 0) / a.length; return Math.sqrt(a.reduce((x, y) => x + (y - m) ** 2, 0) / a.length); };
    const mom90 = Math.log(px / P[n - 90]) / (sd(lr) * Math.sqrt(90)), mom30 = px / P[n - 30] - 1;
    const ath = Math.max(...P), dd = (px / ath - 1) * 100;
    const v30 = k => { const a = []; for (let j = k - 29; j <= k; j++) a.push(Math.log(P[j] / P[j - 1])); return sd(a) * Math.sqrt(365) * 100; };
    const vol = v30(n), vh = []; for (let k = n - 364; k <= n; k += 7) vh.push(v30(k)); const volp = vh.filter(x => x < vol).length / vh.length;
    const mv = M[n], mh = M.slice(0, n + 1).filter(x => x != null), mvp = mv != null ? mh.filter(x => x < mv).length / mh.length : null;
    let above10 = true; for (let j = n - 9; j <= n; j++) if (P[j] <= ma(200, j)) { above10 = false; break; }
    let stressed1y = false; for (let j = n - 365; j < n - 10; j += 5) { const pk = Math.max(...P.slice(0, j + 1)); if ((P[j] / pk - 1) <= -0.4 && P[j] < ma(200, j) || (M[j] != null && M[j] < 1)) { stressed1y = true; break; } }
    const f = funding && funding.length ? funding.slice(-21) : null, fa = f ? f.reduce((a, x) => a + x[1], 0) / f.length * 3 * 365 * 100 : null;
    const valZ = mv != null && (mv < 1 || mvp <= .1), stress = dd <= -40 && px < m200, capit = stress && volp >= .8, euph = mvp != null && mvp >= .9;
    const early = valZ && mom30 > 0 && !(isN(fa) && fa > 30), recov = above10 && mom90 > 0 && stressed1y, defen = px < m200 && mom90 < 0, expan = px > m200 && m50 > m200 && !euph;
    const S = euph ? ["Euphoria warning", C.bad, "Risk-management warning", "MVRV is in the top 10% of its history: holders sit on huge profits. Past cycle tops came in such zones, though each peak was lower than the last."]
      : capit ? ["Capitulation", C.warn, "Context", "Deep drawdown below the trend with a volatility spike: forced selling. Capitulations came near past lows, but often weeks or months before the final low."]
      : early ? ["Early high-risk setup", C.good, "Early high-risk entry setup", "Valuation zone with the price turning up over 30 days and no leverage excess. Early: prices fell further after some past setups."]
      : recov ? ["Confirmed recovery", C.good, "Confirmed recovery signal", "Price above its 200-day average for 10 days with positive 90-day momentum after a stress period: how the 2019 and 2023 recoveries looked."]
      : stress ? ["Stress", C.warn, "Risk warning", `Price ${Math.abs(dd).toFixed(0)}% below its high and under its 200-day average. Past bear markets fell 75–85% from the top; stress is not yet the bottom.`]
      : defen ? ["Defensive (downtrend)", C.bad, "Risk reduction", "Below the 200-day average with negative momentum: the trend points down."]
      : expan ? ["Bull expansion", C.good, "Trend state", "Above the 200-day average with the 50-day above the 200-day: the healthy part of the cycle."]
      : ["Neutral", C.ink, "Trend state", "No extreme valuation or trend condition."];
    const L = [
      ["MVRV", mv != null ? `${mv.toFixed(2)} · higher than ${Math.round(mvp * 100)}% of history · realized price ${Math.round(px / mv).toLocaleString("en-US")} $` : "∅", mv == null ? "neu" : valZ ? "pos" : euph ? "neg" : "neu", mv == null ? "no on-chain data" : mv < 1 ? "below 1: holders at a loss on average, the zone of past bottoms" : euph ? "euphoric zone of past tops" : "between bottom and top zones"],
      ["Valuation zone", valZ ? "yes" : "no", valZ ? "pos" : "neu", valZ ? "attractive valuation zone, not an entry signal by itself" : "no deep-value signal"],
      ["200-day average", `${Math.round(m200).toLocaleString("en-US")} $ · price ${((px / m200 - 1) * 100).toFixed(1)}% ${px >= m200 ? "above" : "below"}; 50-day ${m50 >= m200 ? "above" : "below"} the 200-day`, px >= m200 ? "pos" : "neg", px >= m200 ? "bull trend" : "bear trend"],
      ["90-day momentum", `${mom90 >= 0 ? "+" : ""}${mom90.toFixed(2)} (volatility-scaled) · 30-day return ${pc(mom30 * 100)}`, mom90 > 0 ? "pos" : "neg", mom90 > 0 ? "momentum up" : "momentum down"],
      ["Drawdown from all-time high", `${dd.toFixed(1)}% (high ${Math.round(ath).toLocaleString("en-US")} $)`, dd <= -40 ? "neg" : "neu", dd <= -75 ? "as deep as past bear-market lows" : dd <= -40 ? "stress territory" : "moderate"],
      ["30-day volatility", `${vol.toFixed(0)}%/yr · higher than ${Math.round(volp * 100)}% of the last year`, volp >= .8 ? "mix" : "neu", volp >= .8 ? "volatility spike" : "normal"],
      ["Funding & sentiment", `${isN(fa) ? `funding ${fa >= 0 ? "+" : ""}${fa.toFixed(1)}%/yr` : "funding ∅"}${fng ? ` · Fear & Greed ${fng}` : ""}`, isN(fa) && fa > 30 ? "neg" : isN(fa) && fa < 0 ? "pos" : "neu", isN(fa) && fa > 30 ? "crowded leveraged longs" : isN(fa) && fa < 0 ? "shorts pay longs: pessimism" : "no leverage excess"]];
    return { date: R[n][0], price: px, state: S[0], col: S[1], type: S[2], note: S[3] + " Labels describe, they do not predict; only trend and MVRV have published evidence.", lines: L,
      flags: { valuation_zone: valZ, stress, capitulation: capit, early_setup: early, confirmed_recovery: recov, defensive: defen, expansion: expan, euphoria: euph } };
  }

  /* ---------- tap-to-explain glossary ---------- */
  function glossInit(G) {
    if (!G || W.__gloss) return; W.__gloss = G;
    const idx = []; for (const [k, v] of Object.entries(G)) for (const a of (v.a || [])) idx.push([a.toLowerCase(), k]);
    idx.sort((x, y) => y[0].length - x[0].length);
    const norm = t => String(t || "").toLowerCase().replace(/\s+/g, " ").trim();
    const find = t => { t = norm(t); for (const [a, k] of idx) if (t.startsWith(a)) return k; return null; };
    const st = document.createElement("style");
    st.textContent = `[data-g]{cursor:pointer}[data-g]:not(.m)::after,.m[data-g] .mr>span::after{content:"ⓘ";font-size:.8em;margin-left:4px;opacity:.5;font-weight:400}
#gpop{position:fixed;inset:auto 12px 12px 12px;max-width:440px;margin:0 auto;z-index:9999;background:var(--bg3,var(--bg,#fff));color:var(--ink,#111);border:1px solid var(--ln,#ccd);border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.25);padding:14px 16px 12px;font-size:13.5px;line-height:1.45;max-height:70vh;overflow:auto}
#gpop h5{margin:0 26px 6px 0;font-size:15px}#gpop p{margin:6px 0}#gpop b{font-weight:650}#gpop .x{position:absolute;top:8px;right:10px;border:0;background:none;font-size:20px;cursor:pointer;color:inherit;opacity:.6}
#gpop .lv{background:color-mix(in srgb,var(--warn,#c80) 10%,transparent);border-radius:8px;padding:6px 8px}#gpop .s{opacity:.7;font-size:12px}`;
    document.head.appendChild(st);
    const pop = document.createElement("div"); pop.id = "gpop"; pop.hidden = true; pop.setAttribute("role", "dialog"); document.body.appendChild(pop);
    const esc = s => String(s).replace(/[&<>"]/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));
    const cl = t => { t = String(t).replace(/^(higher|lower|above|below)[^=]{0,40}=\s*/i, m => /^(higher|lower)\s*=/i.test(m) ? "" : m); return t.charAt(0).toUpperCase() + t.slice(1); };
    const show = k => { const x = G[k]; if (!x) return;
      pop.innerHTML = `<button class="x" aria-label="Close">×</button><h5>${esc(x.n)}</h5><p>${esc(x.w)}</p><p><b>Higher ↑</b> ${esc(cl(x.hi))}</p><p><b>Lower ↓</b> ${esc(cl(x.lo))}</p>${x.lv ? `<p class="lv"><b>Levels to know</b> ${esc(x.lv)}</p>` : ""}<p class="s">Plain explanation for beginners; context, not advice.</p>`;
      pop.hidden = false; };
    const mark = () => {
      document.querySelectorAll(".m[data-k]:not([data-g])").forEach(el => { if (G[el.dataset.k]) el.dataset.g = el.dataset.k; });
      document.querySelectorAll(".cws h4:not([data-g]),.fw h4:not([data-g]),.cw h3>span:first-child:not([data-g]),.cw>h3:not([data-g]),#mrp>h3:not([data-g]),#btcp>h3:not([data-g]),.gl-t:not([data-g]),.grp .gh h3:not([data-g]),.snm:not([data-g]),.br>span:first-child:not([data-g]),.tile h3:not([data-g]),.tile>b:not([data-g])").forEach(el => { const k = el.querySelector("[data-g]") ? null : find(el.textContent); el.dataset.g = k || ""; });
      document.querySelectorAll('[data-g=""]').forEach(el => el.removeAttribute("data-g"));
    };
    document.addEventListener("click", ev => {
      if (ev.target.closest("#gpop .x")) { pop.hidden = true; return; }
      if (ev.target.closest("#gpop")) return;
      const el = ev.target.closest("[data-g]"); if (el && !ev.target.closest("a,button,input")) { ev.stopPropagation(); show(el.dataset.g); return; }
      pop.hidden = true;
    }, true);
    document.addEventListener("keydown", ev => { if (ev.key === "Escape") pop.hidden = true; });
    mark(); new MutationObserver(() => { clearTimeout(W.__gm); W.__gm = setTimeout(mark, 120); }).observe(document.body, { childList: true, subtree: true });
  }

  W.SGRegime = { liveFear, fearAt, fearZone, creditZone, ratesRead, inflationRead, btcCycle, glossInit, PH };
  if (typeof module !== "undefined") module.exports = W.SGRegime;
})(typeof window !== "undefined" ? window : globalThis);
