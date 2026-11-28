#!/usr/bin/env python3
"""Market fear (VIX) reading for input.json → market_fear (version 3, 21 Nov 2026).

Reads the daily series the StockGlass GitHub workflow keeps (data/market-history.json: VIX, VIX3M, S&P 500, trailing and
HAR-forecast realised variance, variance risk premium, HYG/IEF credit ratio, bear flag, fear phase) and computes, for today
or for an as-of date (historical mode: nothing after that date; the HAR forecast and the phases use past data only):
  premium = 3 + 4 × percentile of VRP (VIX² − HAR expected 22-day realised variance) over the last 10 years (5 if less)
  phase   = calm 5 · early fear 5 (risk flag) · peak stress 5.5 · fading fear 7.5 when confirmed (credit easing, no new
            20-day S&P low in the last 5 days, no bear state), else 5.5 · after fear 4.5
  score   = 0.3 × premium + 0.7 × phase; label Supportive ≥ 6.5, Unsupportive ≤ 4.5, else Neutral
  score.py applies 5 + (score − 5) × clip(beta, 0.5, 1.5) per stock, 10% of the entry-timing score.
Method, holdout test and sources: references/methodology.md §5k.

Usage:  python3 market_fear.py [--as-of YYYY-MM-DD] [--src URL_or_file] [--out market_fear.json]
        live (27 Nov 2026, every live run): add today's quotes, e.g.
        python3 market_fear.py --vix 27.4 [--vix3m 25.9] --spx-chg -0.6 --hyg-chg -0.2 --ief-chg 0.1 [--date 2026-11-27] [--time "15:40 ET"]
        (--spx-chg / --hyg-chg / --ief-chg = today's % change vs the previous close: SPY, HYG and IEF quotes from Twelve Data).
        The live reading becomes the main one (it is what score.py applies) and the saved readings are kept for comparison:
        "saved" (last official close) and "week" (five sessions earlier); "zone" = plain reading vs history (scripts/regime.py).
        Live runs also attach the Market Regime context from StockGlass data/regime.json (rates, inflation) and the credit zone.
Then copy the printed block into input.json as "market_fear".
"""
import argparse, json, sys, urllib.request, datetime as _dt
from regime import live_fear, fear_at, fear_zone, credit_zone, credit_live, rates_read, inflation_read

SRC = "https://raw.githubusercontent.com/wassim96-dot/stockglass/main/data/market-history.json"
WIN, WIN10 = 1260, 2520
PHASE = {"calm": (5, "Calm", "No market stress: no signal from the fear cycle."),
         "early": (5, "Early fear", "Fear has just begun and the VIX is near its high. Average returns after such days have been normal, but they were followed by the deepest drops: not the bottom, a high-risk entry."),
         "peak": (5.5, "Peak stress", "Fear has lasted several days with the VIX near its high: forward returns slightly above average overall, but below average in 2007–2016, with large swings."),
         "fading": (7.5, "Fading fear (confirmed)", "The VIX is 15%+ below its high, credit has stopped widening and the market made no new low: historically the best entry phase, with the smallest follow-on drops (2007–2016 and 2016–2026)."),
         "fading_unconfirmed": (5.5, "Fading fear (unconfirmed)", "The VIX is 15%+ below its high, but credit is still widening, the market made a new low or it is in a bear market: in 2008 and 2022 such pauses came before further falls."),
         "after": (4.5, "After fear", "Stress ended within the last month: returns have been below average in both 2007–2016 and 2016–2026.")}

def load(src):
    if src.startswith("http"):
        with urllib.request.urlopen(src, timeout=30) as r: return json.load(r)
    return json.load(open(src))

def credit_check(rows, c):
    """Context only: HYG/IEF ratio and S&P 500 change over 1 and 4 weeks (5 and 20 trading days) from the history file.
    Historical runs keep this plain ratio (not rate-adjusted); live runs replace it with the full version-2 credit check from
    StockGlass data/market.json (ICE BofA spreads from FRED, rate-adjusted fund ratios, 10-year Treasury yield)."""
    def chg(col, n):
        v = [r[c[col]] for r in rows if r[c[col]] is not None]
        return round((v[-1] / v[-1 - n] - 1) * 100, 2) if len(v) > n else None
    return {"date": rows[-1][0], "hy": {"series": "HYG/IEF", "chg_1w": chg("credit", 5), "chg_4w": chg("credit", 20)} if "credit" in c else None,
            "ig": None, "spx": {"chg_1w": chg("spx", 5), "chg_4w": chg("spx", 20)}}

def reading(doc, as_of=None):
    cols = doc.get("columns") or []
    if "rvhar" not in cols: raise SystemExit("market-history.json is an older version (no HAR column): rerun the StockGlass market-fear workflow")
    c = {k: i for i, k in enumerate(cols)}
    rows = [r for r in doc["rows"] if r[c["vrp"]] is not None and (as_of is None or r[0] <= as_of)]
    if len(rows) < 250: raise SystemExit("not enough history before that date")
    x = rows[-1]; w = rows[-(WIN10 if len(rows) >= WIN10 else WIN):]
    pv = sum(1 for r in w if r[c["vrp"]] < x[c["vrp"]]) / len(w); pk = sum(1 for r in w if r[1] < x[1]) / len(w)
    ph = x[c["phase"]]
    # stress age and episode high (for the note)
    age, peak = 0, None
    for r in reversed(rows):
        if r[c["phase"]] in ("early", "peak", "fading", "fading_unconfirmed"): age += 1; peak = max(peak or 0, r[1])
        else: break
    spx = [r[c["spx"]] for r in rows]; i = len(spx) - 1
    new_low5 = any(spx[k] <= min(spx[max(0, k - 19):k + 1]) for k in range(i - 4, i + 1))
    cr = [r[c["credit"]] for r in rows[-20:] if r[c["credit"]] is not None]
    credit_easing = None if x[c["credit"]] is None or len(cr) < 10 else x[c["credit"]] > min(cr)
    bear = bool(x[c["bear"]])
    ma200 = sum(spx[-200:]) / 200; r24 = (spx[-1] / spx[-505] - 1) * 100 if len(spx) > 505 else None
    prem = 3 + 4 * pv; score = round(0.3 * prem + 0.7 * PHASE[ph][0], 1)
    label = "Supportive" if score >= 6.5 else "Unsupportive" if score <= 4.5 else "Neutral"
    ratio = round(x[1] / x[2], 3) if x[2] else None
    note = (PHASE[ph][1] + (f" (day {age} of stress, VIX high {peak:.1f})" if age else "") + ": " + PHASE[ph][2]
            + f" Variance risk premium (HAR) higher than {round(pv * 100)}% of the last {len(w) / 252:.0f} years."
            + (" VIX above VIX3M: the term structure is inverted, a sign of near-term stress." if ratio and ratio > 1 else "")
            + (" Bear state: the S&P 500 is more than 15% below its 52-week high with a negative 12-month return." if bear else ""))
    return {"date": x[0], "vix": x[1], "vix3m": x[2], "vix_vix3m": ratio, "rv22": x[c["rv22"]], "rv_expected": x[c["rvhar"]], "vrp": x[c["vrp"]],
            "vrp_pct": round(pv * 100), "vix_pct": round(pk * 100), "window_years": round(len(w) / 252, 1),
            "phase": ph, "phase_label": PHASE[ph][1], "stress_days": age, "vix_peak": peak, "risk_flag": ph == "early",
            "fading_checks": {"credit_easing": credit_easing, "new_low_5d": new_low5, "bear_state": bear} if ph.startswith("fading") else None,
            "premium_score": round(prem, 1), "phase_score": PHASE[ph][0], "score": score, "label": label, "note": note,
            "market": {"index": "S&P 500", "above_200d": spx[-1] > ma200, "ret_24m": round(r24, 1) if r24 is not None else None, "bear_state": bear},
            "credit_check": credit_check(rows, c),
            "source": "StockGlass data/market-history.json (Yahoo ^VIX, ^VIX3M, ^GSPC, HYG/IEF daily closes)"}

def live_note(m):
    ph = m["phase"]
    return (PHASE[ph][1] + (f" (day {m['stress_days']} of stress, VIX high {m['vix_peak']:.1f})" if m.get("stress_days") and m.get("vix_peak") else "") + ": " + PHASE[ph][2]
            + f" Variance risk premium (HAR) higher than {m['vrp_pct']}% of the last {m['window_years']:.0f} years."
            + (" VIX above VIX3M: the term structure is inverted, a sign of near-term stress." if (m.get("vix_vix3m") or 0) > 1 else "")
            + (" Bear state: the S&P 500 is more than 15% below its 52-week high with a negative 12-month return." if (m.get("market") or {}).get("bear_state") else ""))

if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--as-of"); ap.add_argument("--src", default=SRC); ap.add_argument("--out")
    ap.add_argument("--vix", type=float); ap.add_argument("--vix3m", type=float); ap.add_argument("--spx-chg", type=float)
    ap.add_argument("--hyg-chg", type=float); ap.add_argument("--ief-chg", type=float); ap.add_argument("--date"); ap.add_argument("--time")
    ap.add_argument("--lqd-chg", type=float)   # LQD % vs previous close: live investment-grade spread estimate
    a = ap.parse_args()
    try: d = load(a.src)
    except Exception as ex: sys.exit(f"could not read {a.src}: {ex}")
    m = reading(d, a.as_of)
    if not a.as_of:
        m["saved"], m["week"] = fear_at(d, 0), fear_at(d, 5)
        if a.vix is not None:   # live: today's quotes on top of the saved history, same rules as the nightly job
            c = {k: i for i, k in enumerate(d["columns"])}; rows = [r for r in d["rows"] if r[c["vrp"]] is not None]
            day = a.date or _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=-5))).date().isoformat()
            base = rows[-2] if rows[-1][0] >= day else rows[-1]          # previous close the % changes refer to
            spx = base[c["spx"]] * (1 + a.spx_chg / 100) if a.spx_chg is not None else None
            cr = base[c["credit"]] * (1 + a.hyg_chg / 100) / (1 + a.ief_chg / 100) if a.hyg_chg is not None and a.ief_chg is not None and base[c["credit"]] else None
            L = live_fear(d, {"date": day, "vix": a.vix, "vix3m": a.vix3m, "spx": spx, "credit": cr, "time": a.time})
            if L:
                cc = m.get("credit_check"); m.update(L); m["credit_check"] = cc; m["note"] = live_note(m)
                m["source"] += "; live quotes " + (a.time or day) + " (VIX" + (", VIX3M" if a.vix3m else ", VIX3M from the last close") + (", S&P 500 via SPY" if spx else "") + (", HYG/IEF" if cr else "") + ")"
        else:
            m["live"] = False; m["live_note"] = "No live quote given: the last saved close is used."
    if not a.as_of:   # live: investment-grade ratio from the daily StockGlass reading
        try:
            mk = load(a.src.replace("market-history.json", "market.json"))
            cc = mk.get("credit_check") or {}
            if cc.get("version"): m["credit_check"] = cc          # version 2: spreads (FRED, incl. CCC), rate-adjusted fund ratios, 10-year yield
            elif cc.get("ig") and m.get("credit_check"): m["credit_check"]["ig"] = cc["ig"]
            if a.hyg_chg is not None and a.ief_chg is not None and m.get("credit_check"):
                m["credit_check"]["live"] = {"hy_vs_ief_today": round(a.hyg_chg - 3.2 / 7.3 * a.ief_chg, 2), "spx_today": a.spx_chg, "time": a.time}
        except Exception: pass
        try:   # Market Regime context (rates, inflation), never scored
            rg = load(a.src.replace("market-history.json", "regime.json"))
            m["regime"] = {"updated": rg.get("updated"), "rates": rates_read(rg), "inflation": inflation_read(rg), "raw": {"rates": rg.get("rates"), "inflation": rg.get("inflation")}}
        except Exception: m["regime"] = None
        m["credit_zone"] = credit_zone(m.get("credit_check"))
        # live spread estimate (same rule as StockGlass creditLive): FRED's last spreads moved by HYG / LQD vs IEF since that date
        fc = (m.get("credit_check") or {}).get("fund_closes")
        if fc and a.hyg_chg is not None and a.ief_chg is not None:
            day = a.date or _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=-5))).date().isoformat()
            rl, saved_today = fc["raw_last"], fc["dates"][-1] >= day       # today's close already saved: it is the live price
            px = lambda k, ch: rl[k] if saved_today else (rl[k] * (1 + ch / 100) if ch is not None else None)
            L2 = credit_live(m["credit_check"], {"HYG": px("HYG", a.hyg_chg), "LQD": px("LQD", a.lqd_chg), "IEF": px("IEF", a.ief_chg), "t": a.time})
            if L2:
                m["credit_live"] = {k: v for k, v in L2["spreads"].items() if isinstance(v, dict) and v.get("est")}
                m["credit_zone"] = credit_zone(L2); m["credit_zone"]["live_estimate"] = True
    m["zone"] = fear_zone(m)
    txt = json.dumps(m, indent=1, ensure_ascii=False)
    if a.out: open(a.out, "w").write(txt)
    print(txt)
