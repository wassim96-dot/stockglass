"""ETF fund flows (context only, never scored): money coming into or leaving the fund over the last four quarters.

Input: input.json -> etf.flows (see references/etf.md §8)
  points  : quarter-end snapshots {date, aum, units, nav} (full units; nav per unit). Units outstanding change = pure flow.
  windows : cumulative net flows from ONE dated source {as_of, source_aum, 1m, 3m, 6m, 1y}
Evidence: flows chase past returns, and ETF inflows are followed by slightly weaker index returns
(Brown, Davies & Ringgenberg 2021, "ETF Arbitrage, Non-Fundamental Demand, and Return Predictability", Review of Finance).
"""
from datetime import date

def _n(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None

def _d(x):
    try: return date.fromisoformat(str(x)[:10])
    except Exception: return None

def flows_block(F, REF, aum_now=None, perf_6m=None, perf_1y=None):
    if not isinstance(F, dict): return None
    warn = []
    pts = []
    for p in F.get("points") or []:
        if not isinstance(p, dict): continue
        d = _d(p.get("date"))
        if d is None or d > REF: continue
        aum, units, nav = _n(p.get("aum")), _n(p.get("units")), _n(p.get("nav"))
        if nav is None and aum and units: nav = aum / units
        pts.append({"date": str(d), "period": p.get("period") or str(d), "aum": aum, "units": units, "nav": nav})
    pts.sort(key=lambda x: x["date"]); pts = pts[-5:]
    bars = []
    for a, b in zip(pts, pts[1:]):
        flow, how = None, None
        if a["units"] is not None and b["units"] is not None and (a["nav"] or b["nav"]):
            navm = ((a["nav"] or b["nav"]) + (b["nav"] or a["nav"])) / 2
            flow, how = (b["units"] - a["units"]) * navm, "units"
        elif a["aum"] and b["aum"] and a["nav"] and b["nav"]:
            flow, how = b["aum"] - a["aum"] * (b["nav"] / a["nav"]), "aum-return"
        base = a["aum"] or (a["units"] * a["nav"] if a["units"] and a["nav"] else None)
        if flow is None and a["aum"] and b["aum"]:
            bars.append({"label": f'{a["period"]} → {b["period"]}', "flow": None, "aum_change": b["aum"] - a["aum"], "pct": None, "how": "aum only (includes market moves)"})
            continue
        if flow is None: continue
        bars.append({"label": f'{a["period"]} → {b["period"]}', "flow": round(flow), "pct": round(flow / base * 100, 1) if base else None, "how": how})
    win = None
    W = F.get("windows") if isinstance(F.get("windows"), dict) else None
    if W:
        sa = _n(W.get("source_aum"))
        stale = sa is not None and aum_now and abs(sa / aum_now - 1) > 0.10
        asof = _d(W.get("as_of"))
        if stale:
            warn.append(f"Flow windows dropped: the source's fund size ({sa:,.0f}) differs from the current one ({aum_now:,.0f}) by more than 10%, so its figures are stale.")
        elif asof is None or asof > REF or (REF - asof).days > 45:
            warn.append("Flow windows dropped: no as-of date, dated after the scoring date, or older than 45 days.")
        else:
            m3, m6, y1 = _n(W.get("3m")), _n(W.get("6m")), _n(W.get("1y"))
            ref_aum = aum_now or sa
            seg = []
            if m3 is not None: seg.append({"label": "last 3 months", "flow": m3})
            if m3 is not None and m6 is not None: seg.append({"label": "3–6 months ago", "flow": m6 - m3})
            if m6 is not None and y1 is not None: seg.append({"label": "6–12 months ago", "flow": y1 - m6})
            for s in seg: s["pct"] = round(s["flow"] / ref_aum * 100, 1) if ref_aum else None
            win = {"as_of": str(asof), "segments": seg[::-1], "1y": y1, "1y_pct": round(y1 / ref_aum * 100, 1) if (y1 is not None and ref_aum) else None, "1m": _n(W.get("1m"))}
    if not pts and not win: return {"points": [], "bars": [], "windows": None, "warnings": warn, "note": None, "scored": False} if warn else None
    # reading
    tot_pct = None
    if bars and all(b.get("pct") is not None for b in bars): tot_pct = round(sum(b["pct"] for b in bars), 1)
    elif win and win.get("1y_pct") is not None: tot_pct = win["1y_pct"]
    label = None if tot_pct is None else "inflows" if tot_pct > 2 else "outflows" if tot_pct < -2 else "flat"
    notes = []
    perf = perf_1y if perf_1y is not None else perf_6m
    if tot_pct is not None and perf is not None:
        if tot_pct > 10 and perf > 10:
            notes.append("Money poured in after a strong run: flows tend to chase past returns, and ETF inflows have been followed by slightly weaker returns (Brown, Davies & Ringgenberg 2021). A mild caution, not a signal.")
        elif tot_pct < -10 and perf > 0:
            notes.append("Investors left even though the market rose: often a rotation to cheaper share classes or competing funds, or profit-taking; check whether a peer fund gathered the money.")
        elif tot_pct < -10 and perf < 0:
            notes.append("Outflows during a falling market: selling pressure on the fund, which historically tends to precede slightly better, not worse, index returns.")
    if label == "outflows" and aum_now and aum_now < 100e6:
        notes.append("Small fund losing assets: closure risk rises below about 50–100 M.")
    parts = []
    if tot_pct is not None: parts.append(f"Net {label} of {tot_pct:+.1f}% of fund size over the period shown")
    if pts and pts[0].get("units") and pts[-1].get("units"):
        parts.append(f"units outstanding {pts[0]['units']:,.0f} → {pts[-1]['units']:,.0f} ({(pts[-1]['units'] / pts[0]['units'] - 1) * 100:+.1f}%)")
    return {"points": pts, "bars": bars, "windows": win, "total_pct": tot_pct, "label": label, "notes": notes, "warnings": warn,
            "source": F.get("source"), "basis": F.get("basis"), "currency": F.get("currency"),
            "note": "; ".join(parts) + "." if parts else None, "scored": False}
