#!/usr/bin/env python3
"""Test 3 (backtest/HYPOTHESES3.md, 28 Nov 2026): StockGlass's full Minervini check (index.html trendTemplate(), ported
line by line) + the timing score's technical part, without market fear and valuation. No network.
Reads backtest/results.csv and backtest/cache/*.json; writes backtest/setup3_features.csv, backtest/stats3.json and
backtest/charts/setup3_*.csv.
"""
import json, os
import numpy as np, pandas as pd
from setup import load, nw, block_boot, icsum, qspread, holm, HERE, OUT, SPLIT

SECTOR = {"Information Technology": "XLK", "Financials": "XLF", "Health Care": "XLV", "Energy": "XLE", "Industrials": "XLI",
          "Consumer Discretionary": "XLY", "Consumer Staples": "XLP", "Utilities": "XLU", "Materials": "XLB",
          "Real Estate": "XLRE", "Communication Services": "XLC"}
POINTS = ["b_stack", "b_rising", "b_low", "b_high", "b_rs", "e_rshigh", "e_notext", "e_nospike", "e_volume", "e_liquid", "e_sector"]

def ttw(c):
    """index.html ttW: IBD-weighted return in % from a close array ending at the as-of bar"""
    n = len(c)
    r = [(c[-1] / c[n - 1 - k] - 1) * 100 if n > k and c[n - 1 - k] > 0 else None for k in (63, 126, 189, 252)]
    return None if None in r else .4 * r[0] + .2 * (r[1] + r[2] + r[3])

def full_check(P, i, S, si, B, bi):
    """index.html trendTemplate() on bars up to i (last 2 years, as the page loads), market = SPY, sector ETF = B"""
    lo_i = max(0, i - 504)
    d = {k: P[k][lo_i:i + 1] for k in ("c", "h", "l", "v")}; dates = P["d"][lo_i:i + 1]
    c, h, l, v = d["c"], d["h"], d["l"], d["v"]; n = len(c); p = c[-1]
    if n < 200: return None
    at = lambda k, m: c[:n - k][-m:].mean() if n - k >= m else None
    s50, s150, s200, s200m1 = at(0, 50), at(0, 150), at(0, 200), at(21, 200)
    hi, lo = h[-252:].max(), l[-252:].min()
    sl1 = (s200 / s200m1 - 1) * 100 if s200m1 else None
    up = sl1 is not None and sl1 > 0
    aL = (p / lo - 1) * 100 if lo > 0 else None; bH = (1 - p / hi) * 100 if hi > 0 else None
    mk = S["c"][max(0, si - 504):si + 1]
    sw = ttw(c); mw = ttw(mk) if len(mk) > 253 else None
    rsW = sw - mw if sw is not None and mw is not None else None
    R0 = s150 is not None and p > s150 and p > s200; R1 = s150 is not None and s150 > s200
    R3 = s50 is not None and s150 is not None and s50 > s150 and s50 > s200; R4 = s50 is not None and p > s50
    f = {"b_stack": R0 and R1 and R3 and R4, "b_rising": up, "b_low": aL is not None and aL >= 25,
         "b_high": bH is not None and bH <= 25, "b_rs": None if rsW is None else rsW >= 0}
    # RS line at a 52-week high (dates matched with the market)
    smap = {S["d"][k]: S["c"][k] for k in range(max(0, si - 600), si + 1)}
    rl = [c[k] / smap[dates[k]] for k in range(max(0, n - 252), n) if dates[k] in smap]
    f["e_rshigh"] = (rl[-1] >= max(rl) * .999) if len(rl) > 200 else None
    tr = [max(h[k] - l[k], abs(h[k] - c[k - 1]), abs(l[k] - c[k - 1])) for k in range(n - 20, n)]
    atr = sum(tr) / 20
    ext = (p - s50) / atr if atr and s50 else None; extPct = (p / s50 - 1) * 100 if s50 else None
    f["e_notext"] = None if ext is None else (extPct >= 0 and ext <= 4)
    f["e_nospike"] = max((c[k] / c[k - 1] - 1) * 100 for k in range(max(1, n - 21), n)) < 10
    vv = [x for x in v[-50:] if x > 0]; upVol = dry = None
    if len(vv) >= 40:
        av = sum(vv) / len(vv); dry = v[-10:].mean() / av
        for k in range(n - 1, max(1, n - 5) - 1, -1):
            if c[k] > c[k - 1]: upVol = v[k] / av; break
        to = sorted(c[k] * v[k] for k in range(n - 50, n) if v[k] > 0); med = to[len(to) // 2]
        f["e_liquid"] = med * .92 >= 1e6
    else: f["e_liquid"] = None
    f["e_volume"] = None if (upVol is None and dry is None) else ((upVol is not None and upVol >= 1.4) or (dry is not None and dry < .75))
    f["e_sector"] = None
    if B is not None and bi is not None and mw is not None:
        bw = ttw(B["c"][max(0, bi - 504):bi + 1])
        if bw is not None: f["e_sector"] = bw - mw >= 0
    av_ = [k for k in POINTS if f[k] is not None]; ok = sum(1 for k in av_ if f[k])
    f.update(M=10 * ok / len(av_), M_tt=10 * sum(1 for k in POINTS[:5] if f[k]) / len([k for k in POINTS[:5] if f[k] is not None]),
             points=len(av_), mae40=float(P["a"][i + 1:i + 41].min() / P["a"][i] - 1) if i + 30 < len(P["a"]) else np.nan)
    return f

def build():
    R = pd.read_csv(os.path.join(HERE, "results.csv"))
    S = load("SPY"); SI = {d: k for k, d in enumerate(S["d"])}
    ETF = {e: load(e) for e in set(SECTOR.values())}
    EI = {e: ({d: k for k, d in enumerate(B["d"])} if B else {}) for e, B in ETF.items()}
    rows = []
    for t, g in R.groupby("ticker"):
        P = load(t)
        if P is None: continue
        PI = {d: k for k, d in enumerate(P["d"])}; e = SECTOR.get(g.sector.iloc[0])
        for _, row in g.iterrows():
            i = PI.get(row.date)
            if i is None or i < 260: continue
            B = ETF.get(e); bi = EI.get(e, {}).get(row.date)
            if B is not None and bi is not None and bi < 253: B = None
            f = full_check(P, i, S, SI[row.date], B, bi)
            if f: f.update(ticker=t, date=row.date); rows.append(f)
    D = R.merge(pd.DataFrame(rows), on=["ticker", "date"], how="inner")
    D["T"] = D.tech_part; D["C"] = .5 * D.M + .5 * D["T"]
    for w in (0, .25, .5, .75, 1): D[f"C{int(w * 100)}"] = w * D.M + (1 - w) * D["T"]
    return D

def main():
    D = build(); D.to_csv(os.path.join(HERE, "setup3_features.csv"), index=False)
    des, hol = D[D.date < SPLIT], D[D.date >= SPLIT]
    out = {"rows": int(len(D)), "months_design": int(des.date.nunique()), "months_holdout": int(hol.date.nunique()),
           "mean_points": float(D.points.mean()), "sector_point_share": float(D.e_sector.notna().mean()), "ic": {}}
    best = max((0, 25, 50, 75, 100), key=lambda w: icsum(des, f"C{w}")[0]["ic"]); out["w_selected"] = best / 100
    D["Cw"] = D[f"C{best}"]; des, hol = D[D.date < SPLIT], D[D.date >= SPLIT]
    for col in ("C", "M", "M_tt", "T", "Cw", "score", "mom12_1"):
        out["ic"][col] = {nm: {f"h{h}": icsum(df, col, h)[0] for h in (20, 40, 60)} for nm, df in (("design", des), ("holdout", hol), ("all", D))}
        by, sp = qspread(hol, col); out["ic"][col]["holdout_q5_q1_8w"] = {"mean": float(sp.mean()), "ci95": block_boot(sp.values)}
        if col in ("C", "M"): by.to_csv(os.path.join(OUT, f"setup3_quintiles_{col}.csv"))
    p1, icC = icsum(hol, "C"); _, icO = icsum(hol, "score"); p3, icM = icsum(hol, "M")
    p2 = nw((icC - icO).dropna().values, 2)
    out["primary"] = {"P1_C_ic": p1, "P2_C_minus_current": p2, "P3_M_ic": p3, "holm": holm([p1["p"], p2["p"], p3["p"]])}
    pd.DataFrame({"C": icC, "current": icO, "M": icM}).to_csv(os.path.join(OUT, "setup3_ic_holdout.csv"))
    # bands of C
    D["band"] = pd.cut(D.C, [-1, 4, 5.5, 7, 11], labels=["<4", "4-5.5", "5.5-7", ">=7"])
    out["bands"] = {str(b): {"n": int(len(g)), "excess8w": float(g.x40.mean()), "hit": float((g.x40 > 0).mean()),
                             "abs8w": float(g.r40.mean()), "mae40": float(g.mae40.mean())} for b, g in D.groupby("band", observed=True)}
    # each point: passed minus failed, monthly paired
    out["points"] = {}
    for k in ("b_stack", "b_rising", "b_low", "b_high", "b_rs", "e_rshigh", "e_notext", "e_nospike", "e_volume", "e_liquid", "e_sector"):
        q = D[D[k].notna()].copy(); q[k] = q[k].astype(bool)
        g = q.groupby(["date", k]).x40.mean().unstack()
        if True in g and False in g:
            r = nw((g[True] - g[False]).dropna().values, 2)
            out["points"][k] = {"pass_share": float(q[k].mean()), "diff8w": r["mean"], "t": r["t"], "months": r["n"]}
    out["overlap"] = {c: {"vs_mom12_1": float(D[[c, "mom12_1"]].corr("spearman").iloc[0, 1]),
                          "vs_current": float(D[[c, "score"]].corr("spearman").iloc[0, 1])} for c in ("M", "T", "C")}
    json.dump(out, open(os.path.join(HERE, "stats3.json"), "w"), indent=1, default=float)
    print(json.dumps({"w_selected": out["w_selected"], "primary": out["primary"], "overlap": out["overlap"]}, indent=1, default=float))

if __name__ == "__main__":
    main()
