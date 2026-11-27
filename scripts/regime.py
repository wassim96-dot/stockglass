#!/usr/bin/env python3
"""Shared context rules for the Market Regime and BTC Cycle panels (27 Nov 2026). Same rules as StockGlass regime.js.

Nothing here changes a score except live_fear(), which recomputes the market-fear reading from today's quotes with the exact
rules of the nightly StockGlass job (scripts/market-fear.mjs), so a live run scores with the live reading and shows the saved
readings (last close, a week ago) for comparison.
  live_fear(hist, live)  fear phase and score for a live row appended to data/market-history.json
  fear_at(hist, back)    score of a saved row (back = 0 last close, 5 = a week ago)
  fear_zone(F), credit_zone(cc)   plain, colour-coded readings vs history (near a bottom, bull run, bearish risk); not forecasts
  rates_read(rg), inflation_read(rg)   Market Regime lines from StockGlass data/regime.json
  btc_cycle(asset, funding, fng)       BTC Cycle panel (unscored), from data/crypto-history.json
"""
import math

PH = {"calm": (5, "Calm"), "early": (5, "Early fear"), "peak": (5.5, "Peak stress"), "fading": (7.5, "Fading fear (confirmed)"),
      "fading_unconfirmed": (5.5, "Fading fear (unconfirmed)"), "after": (4.5, "After fear")}
STRESS = {"early", "peak", "fading", "fading_unconfirmed"}
GOOD, BAD, WARN, INK = "var(--good)", "var(--bad)", "var(--warn)", "var(--ink2)"
isn = lambda v: isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


# ---------- market fear ----------
def rows_of(hist):
    c = {k: i for i, k in enumerate(hist["columns"])}
    return [{"date": r[c["date"]], "vix": r[c["vix"]], "vix3m": r[c["vix3m"]], "spx": r[c["spx"]], "rvhar": r[c["rvhar"]], "vrp": r[c["vrp"]],
             "credit": r[c["credit"]], "phase": r[c["phase"]], "bear": bool(r[c["bear"]])} for r in hist["rows"] if r[c["vrp"]] is not None]


def _score_at(R, i, vrp=None):
    n = i + 1; win = R[max(0, n - (2520 if n >= 2520 else 1260)):n]; v = R[i]["vrp"] if vrp is None else vrp
    pv = sum(1 for s in win if s["vrp"] < v) / len(win); pk = sum(1 for s in win if s["vix"] < R[i]["vix"]) / len(win)
    prem = 3 + 4 * pv; ph = PH[R[i]["phase"]][0]; score = round(0.3 * prem + 0.7 * ph, 1)
    return {"pv": pv, "pk": pk, "prem": prem, "ph": ph, "score": score, "years": len(win) / 252,
            "label": "Supportive" if score >= 6.5 else "Unsupportive" if score <= 4.5 else "Neutral"}


def fear_at(hist, back=0):
    R = rows_of(hist); i = len(R) - 1 - back
    if i < 300: return None
    s = _score_at(R, i)
    return {"date": R[i]["date"], "vix": R[i]["vix"], "phase": R[i]["phase"], "phase_label": PH[R[i]["phase"]][1], "score": s["score"], "label": s["label"],
            "vix_pct": round(s["pk"] * 100), "vrp_pct": round(s["pv"] * 100)}


def live_fear(hist, live):
    """live = {date, vix, vix3m?, spx?, credit? (HYG/IEF price ratio), time?}; missing pieces fall back to the last close."""
    R = rows_of(hist)
    if len(R) < 600 or not live or not isn(live.get("vix")): return None
    if R[-1]["date"] >= live["date"]: R = R[:-1]          # today's close already saved: recompute today from the live quotes
    P = R[-1]
    L = {"date": live["date"], "vix": live["vix"], "vix3m": live["vix3m"] if isn(live.get("vix3m")) else P["vix3m"],
         "spx": live["spx"] if isn(live.get("spx")) else P["spx"], "credit": live["credit"] if isn(live.get("credit")) else P["credit"], "rvhar": P["rvhar"]}
    L["vrp"] = L["vix"] ** 2 - L["rvhar"]
    A = R + [L]; i = len(A) - 1; yr = A[max(0, i - 251):i + 1]
    pct = lambda arr, x: sum(1 for a in arr if a < x) / len(arr)
    stress = bool(L["vix3m"] and L["vix"] / L["vix3m"] > 1) or pct([x["vix"] for x in yr], L["vix"]) >= 0.9
    hi52 = max(x["spx"] for x in yr); ago = A[i - 251]["spx"] if i >= 251 else None
    L["bear"] = L["spx"] < 0.85 * hi52 and ago is not None and L["spx"] < ago
    L["new_low5"] = any(A[at]["spx"] <= min(y["spx"] for y in A[max(0, at - 19):at + 1]) for at in range(i - 4, i + 1))
    cw = [x["credit"] for x in A[i - 19:i + 1] if x["credit"] is not None]
    L["credit_easing"] = None if L["credit"] is None or len(cw) < 10 else L["credit"] > min(cw)
    age, peak, last = 0, 0.0, -999
    for k in range(len(R) - 1, -1, -1):
        if R[k]["phase"] not in STRESS: break
        age += 1; peak = max(peak, R[k]["vix"])
    for k in range(len(R) - 1, -1, -1):
        if R[k]["phase"] in STRESS: last = k; break
    if stress: age = age + 1 if age else 1; peak = L["vix"] if age == 1 else max(peak, L["vix"])
    else: age = 0
    if not stress: L["phase"] = "after" if i - last <= 20 else "calm"
    elif age <= 5 and L["vix"] >= 0.95 * peak: L["phase"] = "early"
    elif L["vix"] <= 0.85 * peak: L["phase"] = "fading" if (L["credit_easing"] is not False and not L["new_low5"] and not L["bear"]) else "fading_unconfirmed"
    else: L["phase"] = "peak"
    s = _score_at(A, i); ma200 = sum(x["spx"] for x in A[-200:]) / 200; a24 = A[i - 504]["spx"] if i >= 504 else None
    return {"live": True, "time": live.get("time"), "date": L["date"], "vix": round(L["vix"], 2), "vix3m": round(L["vix3m"], 2) if L["vix3m"] else None,
            "vix_vix3m": round(L["vix"] / L["vix3m"], 3) if L["vix3m"] else None, "rv_expected": L["rvhar"], "vrp": round(L["vrp"], 1),
            "vrp_pct": round(s["pv"] * 100), "vix_pct": round(s["pk"] * 100), "window_years": round(s["years"], 1), "phase": L["phase"], "phase_label": PH[L["phase"]][1],
            "stress_days": age, "vix_peak": peak if stress else None, "risk_flag": L["phase"] == "early", "premium_score": round(s["prem"], 1), "phase_score": s["ph"],
            "score": s["score"], "label": s["label"],
            "fading_checks": {"credit_easing": L["credit_easing"], "new_low_5d": L["new_low5"], "bear_state": L["bear"]} if L["phase"].startswith("fading") else None,
            "market": {"index": "S&P 500", "above_200d": L["spx"] > ma200, "ret_24m": round((L["spx"] / a24 - 1) * 100, 1) if a24 else None, "bear_state": L["bear"]},
            "live_inputs": {k: isn(live.get(k)) for k in ("vix3m", "spx", "credit")}}


# ---------- historical zones (context, never scored) ----------
def fear_zone(F):
    if not F: return None
    v, p = F.get("vix"), F.get("vix_pct"); mk = F.get("market") or {}; up, bear = mk.get("above_200d"), mk.get("bear_state"); ph = F.get("phase")
    if ph == "early": z = ["Bearish phase starting", BAD, "Fear has just begun. In past stress episodes the first days were not the bottom: the deepest follow-on drops came from here."]
    elif ph == "peak" and v is not None and v >= 40: z = ["Panic zone: near a bottom, not confirmed", WARN, "VIX closes above 40 came near the 2008–09, 2010, 2011, 2020 and 2025 lows, but in late 2008 prices still fell much further after the first one."]
    elif ph == "peak": z = ["Stress peak: possible bottom area", WARN, "Past bottoms formed around such stress peaks, often after a retest of the low. No confirmation yet."]
    elif ph == "fading": z = ["Bottoming process confirmed", GOOD, "Fear is fading with credit stable and no new low: historically how recoveries started (2009, 2016, 2020, 2022–23). Not a guarantee."]
    elif ph == "fading_unconfirmed": z = ["Possible bottom forming, not confirmed", WARN, "Fear is easing, but credit is still widening, the market made a new low or it is in a bear state: in 2008 and 2022 such pauses were followed by new lows."]
    elif ph == "after": z = ["Recovery stage after stress", INK, "Stress ended within the last month; returns right after have been below average."]
    elif up and p is not None and p <= 10: z = ["Late bull: complacency", WARN, "Very low VIX with the market in an uptrend. Sharp corrections have started from such calm (January 2018, July 2024)."]
    elif up and not bear: z = ["Bull-market conditions", GOOD, "Calm volatility with the S&P 500 above its 200-day average: the usual backdrop of bull runs."]
    else: z = ["Quiet downtrend", BAD, "Calm volatility but the S&P 500 below its 200-day average: bear markets have calm stretches too."]
    if bear: z[2] += " Bear state: the S&P 500 is more than 15% below its 52-week high with a negative 12-month return."
    return {"tag": z[0], "col": z[1], "txt": z[2] + " Based on history, not a forecast."}


def credit_zone(cc):
    sp = (cc or {}).get("spreads") or {}; H = sp.get("hy")
    if not H or not isn(H.get("value")): return None
    lv, c4, c1 = H["value"], H.get("chg_4w"), H.get("chg_1w")
    wid = (isn(c4) and c4 >= .4) or (isn(c1) and c1 >= .2); nar = isn(c4) and c4 <= -.4
    if wid and lv < 4.5: z = ["Bearish risk: stress building from tight levels", BAD, f"The high-yield spread ({lv:.2f}%) is widening from a tight level. In 2007, 2015 and early 2022 this came before or with stock declines."]
    elif wid: z = ["Credit stress, still widening", BAD, f"The high-yield spread ({lv:.2f}%) is high and still rising. In 2008, 2011, 2015–16 and 2020 stocks bottomed only once spreads stopped widening."]
    elif nar and lv >= 5: z = ["Spreads turning down from stress: near a bottom", GOOD, f"The high-yield spread ({lv:.2f}%) is falling from a stress level. Stock-market bottoms came within about three months of the spread peak in 2009, 2016, 2020 and 2022."]
    elif nar: z = ["Credit easing", GOOD, "Spreads are narrowing: lenders are calmer, consistent with a healthy or recovering market."]
    elif lv < 3: z = ["Late cycle: very tight spreads", WARN, f"At {lv:.2f}% lenders ask little extra yield: complacency with little cushion (as in 2007, 2021 and late 2024)."]
    elif lv >= 6: z = ["High but stable spreads", WARN, "Stress has paused. A turn lower would be the classic confirmation of a bottom."]
    else: z = ["Normal credit conditions", INK, "Spreads near normal levels (long-run average about 5%): no stress signal."]
    Q = sp.get("ccc")
    if Q and isn(Q.get("chg_4w")) and isn(c4) and Q["chg_4w"] >= 1 and Q["chg_4w"] > 2 * c4:
        z[2] += f" The riskiest bonds (CCC, {Q['value']:.2f}%) widen fastest ({Q['chg_4w']:+.2f} pt in 4 weeks): stress is concentrated in weak borrowers."
    elif Q and isn(Q.get("value")) and Q["value"] >= 12:
        z[2] += f" CCC spreads at {Q['value']:.2f}% signal serious stress among weak borrowers."
    return {"tag": z[0], "col": z[1], "txt": z[2] + " Based on history (ICE BofA since 1996), not a forecast."}


# ---------- live credit estimate (same rule as creditLive in regime.js) ----------
def credit_live(cc, live):
    """FRED's last spread moved by the bond fund's rate-adjusted return since that date (HYG high yield, LQD investment grade,
    IEF Treasuries): Δ ≈ −return / duration. live = {HYG, LQD, IEF (unadjusted prices), t}. A copy of cc, or None."""
    F = (cc or {}).get("fund_closes"); sp = (cc or {}).get("spreads")
    if not F or not sp or not live or not isn(live.get("IEF")): return None
    D = cc.get("durations") or {"HYG": 3.2, "LQD": 8.3, "IEF": 7.3}; n = len(F["dates"]) - 1
    def r2js(v): return math.floor(v * 100 + 0.5) / 100   # = JS Math.round(v * 100) / 100 (halves round up, negatives too)
    def adj_now(k):
        return live[k] * F[k][n] / F["raw_last"][k] if isn(live.get(k)) and (F.get("raw_last") or {}).get(k) else None
    out = dict(cc, spreads=dict(sp), live={"t": live.get("t")}); anyv = False
    for key, fund in (("hy", "HYG"), ("ig", "LQD")):
        s = sp.get(key)
        if not s or not isn(s.get("value")): continue
        i = -1
        for j in range(n + 1):
            if F["dates"][j] <= s["date"]: i = j
        p1, i1 = adj_now(fund), adj_now("IEF")
        if i < 0 or p1 is None or i1 is None: continue
        ret = (p1 / F[fund][i] - 1) - D[fund] / D["IEF"] * (i1 / F["IEF"][i] - 1); d = -ret * 100 / D[fund]
        out["spreads"][key] = dict(s, value=r2js(s["value"] + d), chg_1w=r2js(s["chg_1w"] + d) if isn(s.get("chg_1w")) else s.get("chg_1w"),
                                   chg_4w=r2js(s["chg_4w"] + d) if isn(s.get("chg_4w")) else s.get("chg_4w"), est=True, delta=r2js(d),
                                   base={"value": s["value"], "date": s["date"]}, stale=False)
        anyv = True
    return out if anyv else None


# ---------- rates and inflation ----------
_pt = lambda v: "∅" if not isn(v) else f"{v:+.2f} pt"
_pc = lambda v: "∅" if not isn(v) else f"{v:+.1f}%"


def rates_read(rg):
    R = (rg or {}).get("rates") or {}; L = []
    y2, r10, y10 = R.get("y2"), R.get("real10"), R.get("y10")
    if y2:
        c = y2.get("chg_4w"); k = "neu" if not isn(c) else "neg" if c >= .25 else "pos" if c <= -.25 else "neu"
        L.append(("2-year Treasury yield", f'{y2["value"]:.2f}% · {_pt(y2.get("chg_1w"))} over 1 week, {_pt(c)} over 4 weeks', k,
                  "markets price higher Fed rates (hawkish): a headwind" if k == "neg" else "markets price lower Fed rates; if stocks fall too, a growth scare" if k == "pos" else "little change in expected Fed rates"))
    if r10:
        c = r10.get("chg_4w"); hi = r10["value"] >= 2
        k = ("neg" if hi else "neu") if not isn(c) else "neg" if c >= .25 else "pos" if c <= -.25 else "neg" if hi else "neu"
        w = ("rising real rates weigh on valuations, most on growth stocks" if isn(c) and c >= .25 else "falling real rates support valuations" if isn(c) and c <= -.25
             else "above 2%: restrictive for valuations" if hi else "no strong pressure on valuations") + (" (level above 2% = restrictive)" if hi and isn(c) and abs(c) >= .25 else "")
        L.append(("10-year real yield", f'{r10["value"]:.2f}% · {_pt(r10.get("chg_1w"))} over 1 week, {_pt(c)} over 4 weeks', k, w))
    if y10 and y2:
        sl = round(y10["value"] - y2["value"], 2)
        L.append(("Yield curve (10-year − 2-year)", _pt(sl), "neg" if sl < 0 else "neu",
                  "inverted: a classic recession warning, with long lags" if sl < 0 else "flat to slightly positive" if sl < .5 else "positive: normal shape"))
    return L


def inflation_read(rg):
    I = (rg or {}).get("inflation") or {}; L = []
    for key, nm, hot, cool in (("cpce", "Core PCE inflation", 3.5, 2.5), ("pce", "PCE inflation", 3.5, 2.5), ("ccpi", "Core CPI", 3.5, 2.5), ("cpi", "CPI inflation", 3.5, 2.5), ("ppi", "PPI (producer prices)", 4, 2)):
        x = I.get(key)
        if not x: continue
        a3, yy = x.get("ann3m"), x.get("yoy")
        k = "neu" if not isn(a3) else "neg" if a3 >= hot else "pos" if a3 <= cool else "neu"
        acc = None if not (isn(a3) and isn(yy)) else "accelerating" if a3 > yy + .3 else "decelerating" if a3 < yy - .3 else "steady"
        p2 = lambda v: "∅" if not isn(v) else f"{v:+.2f}%"
        t = f'{x["month"]}: {p2(x.get("mom"))} on the month' + (f', {_pc(yy)} on the year' if isn(yy) else ", yearly change not published") + \
            (f', 3-month pace {_pc(a3)}/yr' if isn(a3) else "") + (f' (previous month {p2(x.get("prev_mom"))})' if isn(x.get("prev_mom")) else "")
        L.append((nm, t, k, ("running hot: keeps pressure on rates" if k == "neg" else "cooling: room for lower rates" if k == "pos" else "near the upper end of normal") + (f"; {acc}" if acc else "")))
    return L


# ---------- BTC cycle (unscored) ----------
def btc_cycle(A, funding=None, fng=None):
    if not A or not A.get("rows"): return None
    c = {k: i for i, k in enumerate(A["columns"])}
    R = [r for r in A["rows"] if r[c["PriceUSD"]]]
    if len(R) < 400: return None
    P = [r[c["PriceUSD"]] for r in R]; M = [r[c["CapMVRVCur"]] for r in R]; n = len(P) - 1; px = P[n]
    ma = lambda k, i=n: sum(P[i - k + 1:i + 1]) / k
    sd = lambda a: (lambda m: math.sqrt(sum((x - m) ** 2 for x in a) / len(a)))(sum(a) / len(a))
    m200, m50 = ma(200), ma(50)
    lr = [math.log(P[j] / P[j - 1]) for j in range(n - 89, n + 1)]
    mom90 = math.log(px / P[n - 90]) / (sd(lr) * math.sqrt(90)); mom30 = px / P[n - 30] - 1
    ath = max(P); dd = (px / ath - 1) * 100
    v30 = lambda k: sd([math.log(P[j] / P[j - 1]) for j in range(k - 29, k + 1)]) * math.sqrt(365) * 100
    vol = v30(n); vh = [v30(k) for k in range(n - 364, n + 1, 7)]; volp = sum(1 for x in vh if x < vol) / len(vh)
    mv = M[n]; mh = [x for x in M[:n + 1] if x is not None]; mvp = sum(1 for x in mh if x < mv) / len(mh) if mv is not None else None
    above10 = all(P[j] > ma(200, j) for j in range(n - 9, n + 1))
    stressed1y = False
    for j in range(n - 365, n - 10, 5):
        pk = max(P[:j + 1])
        if (P[j] / pk - 1 <= -0.4 and P[j] < ma(200, j)) or (M[j] is not None and M[j] < 1): stressed1y = True; break
    f = (funding or [])[-21:]; fa = sum(x[1] for x in f) / len(f) * 3 * 365 * 100 if f else None
    valZ = mv is not None and (mv < 1 or mvp <= .1); stress = dd <= -40 and px < m200; capit = stress and volp >= .8; euph = mvp is not None and mvp >= .9
    early = valZ and mom30 > 0 and not (isn(fa) and fa > 30); recov = above10 and mom90 > 0 and stressed1y
    defen = px < m200 and mom90 < 0; expan = px > m200 and m50 > m200 and not euph
    S = (["Euphoria warning", BAD, "Risk-management warning", "MVRV is in the top 10% of its history: holders sit on huge profits. Past cycle tops came in such zones, though each peak was lower than the last."] if euph
         else ["Capitulation", WARN, "Context", "Deep drawdown below the trend with a volatility spike: forced selling. Capitulations came near past lows, but often weeks or months before the final low."] if capit
         else ["Early high-risk setup", GOOD, "Early high-risk entry setup", "Valuation zone with the price turning up over 30 days and no leverage excess. Early: prices fell further after some past setups."] if early
         else ["Confirmed recovery", GOOD, "Confirmed recovery signal", "Price above its 200-day average for 10 days with positive 90-day momentum after a stress period: how the 2019 and 2023 recoveries looked."] if recov
         else ["Stress", WARN, "Risk warning", f"Price {abs(dd):.0f}% below its high and under its 200-day average. Past bear markets fell 75–85% from the top; stress is not yet the bottom."] if stress
         else ["Defensive (downtrend)", BAD, "Risk reduction", "Below the 200-day average with negative momentum: the trend points down."] if defen
         else ["Bull expansion", GOOD, "Trend state", "Above the 200-day average with the 50-day above the 200-day: the healthy part of the cycle."] if expan
         else ["Neutral", INK, "Trend state", "No extreme valuation or trend condition."])
    L = [("MVRV", f"{mv:.2f} · higher than {round(mvp * 100)}% of history · realized price {px / mv:,.0f} $" if mv is not None else "∅",
          "neu" if mv is None else "pos" if valZ else "neg" if euph else "neu",
          "no on-chain data" if mv is None else "below 1: holders at a loss on average, the zone of past bottoms" if mv < 1 else "euphoric zone of past tops" if euph else "between bottom and top zones"),
         ("Valuation zone", "yes" if valZ else "no", "pos" if valZ else "neu", "attractive valuation zone, not an entry signal by itself" if valZ else "no deep-value signal"),
         ("200-day average", f"{m200:,.0f} $ · price {abs(px / m200 - 1) * 100:.1f}% {'above' if px >= m200 else 'below'}; 50-day {'above' if m50 >= m200 else 'below'} the 200-day",
          "pos" if px >= m200 else "neg", "bull trend" if px >= m200 else "bear trend"),
         ("90-day momentum", f"{mom90:+.2f} (volatility-scaled) · 30-day return {_pc(mom30 * 100)}", "pos" if mom90 > 0 else "neg", "momentum up" if mom90 > 0 else "momentum down"),
         ("Drawdown from all-time high", f"{dd:.1f}% (high {ath:,.0f} $)", "neg" if dd <= -40 else "neu", "as deep as past bear-market lows" if dd <= -75 else "stress territory" if dd <= -40 else "moderate"),
         ("30-day volatility", f"{vol:.0f}%/yr · higher than {round(volp * 100)}% of the last year", "mix" if volp >= .8 else "neu", "volatility spike" if volp >= .8 else "normal"),
         ("Funding & sentiment", (f"funding {fa:+.1f}%/yr" if isn(fa) else "funding ∅") + (f" · Fear & Greed {fng}" if fng is not None else ""),
          "neg" if isn(fa) and fa > 30 else "pos" if isn(fa) and fa < 0 else "neu",
          "crowded leveraged longs" if isn(fa) and fa > 30 else "shorts pay longs: pessimism" if isn(fa) and fa < 0 else "no leverage excess")]
    return {"date": R[n][0], "price": px, "state": S[0], "col": S[1], "type": S[2],
            "note": S[3] + " Labels describe, they do not predict; only trend and MVRV have published evidence.", "lines": L,
            "flags": {"valuation_zone": valZ, "stress": stress, "capitulation": capit, "early_setup": early, "confirmed_recovery": recov,
                      "defensive": defen, "expansion": expan, "euphoria": euph}}
