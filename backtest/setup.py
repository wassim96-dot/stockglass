#!/usr/bin/env python3
"""Minervini setup-score backtest (pre-registered in backtest/HYPOTHESES2.md, 28 Nov 2026). No network.

Reads backtest/results.csv (panel, current timing score, forward returns) and backtest/cache/*.json (daily bars);
writes backtest/setup_features.csv, backtest/stats2.json and backtest/charts/setup_*.csv. Deterministic (seed 20261128).
"""
import json, math, os
import numpy as np, pandas as pd
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__)); CACHE = os.path.join(HERE, "cache"); OUT = os.path.join(HERE, "charts")
os.makedirs(OUT, exist_ok=True)
RNG = np.random.default_rng(20261128)
SPLIT = "2019-01-01"
COMP = ["tt", "rs", "mad", "hi52", "tight", "dry", "ext"]
SIGN = {"tt": 1, "rs": 1, "mad": 1, "hi52": 1, "tight": -1, "dry": -1, "ext": -1}   # hypothesised direction of the raw measure

def lin(x, a0, a10):
    """0 at a0, 10 at a10, linear, clipped"""
    if x is None or not np.isfinite(x): return np.nan
    return float(np.clip((x - a0) / (a10 - a0) * 10, 0, 10))

SCALE = {"tt": lambda x: lin(x, 0, 5), "rs": lambda x: lin(x, -30, 30), "mad": lambda x: lin(x, -15, 15),
         "hi52": lambda x: lin(x, .70, .98), "tight": lambda x: lin(x, 1.5, .5), "dry": lambda x: lin(x, 1.4, .6),
         "ext": lambda x: lin(x, 25, 8)}

def load(t):
    p = os.path.join(CACHE, t + ".json")
    if not os.path.exists(p): return None
    P = json.load(open(p)); return {k: np.array(P[k], float) if k != "d" else P[k] for k in ("d", "h", "l", "c", "v", "a")}

def sma(x, i, n, lag=0):
    j = i - lag; return x[j - n + 1:j + 1].mean() if j - n + 1 >= 0 else np.nan

def ibd(a, i, k=63):
    r = [a[i] / a[i - m * k] - 1 if i - m * k >= 0 else np.nan for m in (1, 2, 3, 4)]
    return (.4 * r[0] + .2 * (r[1] + r[2] + r[3])) * 100

def feats(P, i, S, si):
    c, h, l, v, a = P["c"], P["h"], P["l"], P["v"], P["a"]
    s50, s150, s200, s200m = sma(c, i, 50), sma(c, i, 150), sma(c, i, 200), sma(c, i, 200, 21)
    hi, lo = np.nanmax(h[i - 251:i + 1]), np.nanmin(l[i - 251:i + 1])
    rs = ibd(a, i) - ibd(S["a"], si)
    blocks = [c[i] > s50 > s150 > s200, s200 > s200m, c[i] >= 1.25 * lo, c[i] >= .75 * hi, rs >= 0]
    r = np.diff(np.log(a[i - 63:i + 1]))
    vv = v[i - 49:i + 1]; v10 = vv[-10:].mean(); v50 = vv.mean()
    f = {"tt": float(sum(blocks)), "rs": rs, "mad": (sma(c, i, 21) / s200 - 1) * 100, "hi52": c[i] / hi,
         "tight": r[-10:].std() / r.std() if r.std() > 0 else np.nan, "dry": v10 / v50 if v50 > 0 else np.nan,
         "ext": (c[i] / s50 - 1) * 100}
    # risk: worst close vs entry within the next 40 trading days of the stock
    fut = a[i + 1:i + 41]
    f["mae40"] = float(fut.min() / a[i] - 1) if len(fut) >= 30 else np.nan
    return f

def build():
    R = pd.read_csv(os.path.join(HERE, "results.csv"))
    S = load("SPY"); SI = {d: k for k, d in enumerate(S["d"])}
    gate = {}
    for d in R.date.unique():
        k = SI[d]; c = S["c"]
        gate[d] = bool(c[k] > sma(c, k, 50) > sma(c, k, 200) and sma(c, k, 200) > sma(c, k, 200, 21))
    rows = []
    for t, g in R.groupby("ticker"):
        P = load(t)
        if P is None: continue
        PI = {d: k for k, d in enumerate(P["d"])}
        for _, row in g.iterrows():
            i = PI.get(row.date)
            if i is None or i < 260: continue
            f = feats(P, i, S, SI[row.date]); f.update(ticker=t, date=row.date); rows.append(f)
    F = pd.DataFrame(rows)
    D = R.merge(F, on=["ticker", "date"], how="inner")
    D["gate"] = D.date.map(gate)
    for k in COMP: D[k + "_s"] = D[k].map(SCALE[k])
    return D

# ---------- statistics (same estimators as stats.py) ----------
def nw(x, lag):
    x = np.asarray(x, float); x = x[~np.isnan(x)]; n = len(x)
    if n < 10: return dict(mean=float("nan"), t=float("nan"), p=float("nan"), n=n)
    m = x.mean(); e = x - m; s = (e @ e) / n
    for L in range(1, lag + 1): s += 2 * (1 - L / (lag + 1)) * (e[L:] @ e[:-L]) / n
    se = math.sqrt(s / n); t = m / se if se > 0 else float("nan")
    return dict(mean=float(m), t=float(t), p=float(2 * stats.t.sf(abs(t), n - 1)), n=n)

def block_boot(x, block=6, B=10000):
    x = np.asarray(x, float); x = x[~np.isnan(x)]; n = len(x); k = math.ceil(n / block); means = np.empty(B)
    for b in range(B):
        st = RNG.integers(0, n - block + 1, k); means[b] = np.concatenate([x[s:s + block] for s in st])[:n].mean()
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]

def mic(df, col, y="x40"):
    g = df.dropna(subset=[col, y]).groupby("date")
    return g.apply(lambda s: stats.spearmanr(s[col], s[y]).statistic if len(s) >= 20 and s[col].nunique() > 1 else np.nan,
                   include_groups=False).dropna()

def icsum(df, col, h=40, sign=1):
    ic = sign * mic(df, col, f"x{h}"); r = nw(ic.values, h // 20)
    return {"ic": r["mean"], "t": r["t"], "p": r["p"], "months": r["n"], "pos": float((ic > 0).mean()) if len(ic) else None}, ic

def qspread(df, col, y="x40"):
    q = df.dropna(subset=[col, y]).copy()
    q["q"] = q.groupby("date")[col].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1)
    by = q.groupby(["date", "q"])[y].mean().unstack(); sp = by[5] - by[1]
    return by, sp

def holm(ps):
    o = np.argsort(ps); m = len(ps); adj = np.empty(m); run = 0
    for r, k in enumerate(o): run = max(run, min(1, (m - r) * ps[k])); adj[k] = run
    return adj.tolist()

def main():
    D = build(); D.to_csv(os.path.join(HERE, "setup_features.csv"), index=False)
    des, hol = D[D.date < SPLIT], D[D.date >= SPLIT]
    out = {"rows": int(len(D)), "months_design": int(des.date.nunique()), "months_holdout": int(hol.date.nunique()),
           "stocks": int(D.ticker.nunique()), "components": {}, "composites": {}}
    # component ICs (raw measure, hypothesised sign) and selection on the design period only
    sel = []
    for k in COMP:
        e = {}
        for nm, df in (("design", des), ("holdout", hol), ("all", D)):
            e[nm] = {f"h{h}": icsum(df, k, h, SIGN[k])[0] for h in (20, 40, 60)}
        out["components"][k] = e
        if e["design"]["h40"]["t"] >= 1.0: sel.append(k)
    out["selected"] = sel
    D["prior"] = D[[k + "_s" for k in COMP]].mean(axis=1)
    D["selected"] = D[[k + "_s" for k in sel]].mean(axis=1) if sel else np.nan
    des, hol = D[D.date < SPLIT], D[D.date >= SPLIT]
    for col in ("selected", "prior", "score", "mom12_1"):
        e = {}
        for nm, df in (("design", des), ("holdout", hol), ("all", D)):
            e[nm] = {f"h{h}": icsum(df, col, h)[0] for h in (20, 40, 60)}
        if D[col].notna().any():
            by, sp = qspread(hol, col); e["holdout_q5_q1_8w"] = {"mean": float(sp.mean()), "ci95": block_boot(sp.values)}
            by.to_csv(os.path.join(OUT, f"setup_quintiles_{col}.csv"))
        out["composites"][col] = e
    # primary tests (holdout, 8 weeks)
    p1, ic_sel = icsum(hol, "selected") if sel else ({"p": 1.0, "ic": None, "t": None}, pd.Series(dtype=float))
    _, ic_old = icsum(hol, "score")
    dif = (ic_sel - ic_old).dropna() if sel else pd.Series(dtype=float)
    p2 = nw(dif.values, 2) if len(dif) else {"p": 1.0, "mean": None, "t": None}
    p3, ic_pri = icsum(hol, "prior")
    ps = [p1["p"], p2["p"], p3["p"]]
    out["primary"] = {"P1_selected_ic": {"ic": p1["ic"], "t": p1["t"], "p": p1["p"]},
                      "P2_selected_minus_current": {"diff": p2["mean"], "t": p2["t"], "p": p2["p"]},
                      "P3_prior_ic": {"ic": p3["ic"], "t": p3["t"], "p": p3["p"]}, "holm": holm(ps)}
    pd.DataFrame({"selected": ic_sel, "current": ic_old, "prior": ic_pri}).to_csv(os.path.join(OUT, "setup_ic_holdout.csv"))
    # S2 overlap
    out["overlap"] = {c: {"vs_mom12_1": float(D[[c, "mom12_1"]].corr("spearman").iloc[0, 1]),
                          "vs_current": float(D[[c, "score"]].corr("spearman").iloc[0, 1])} for c in ("selected", "prior") if D[c].notna().any()}
    # S3 market gate: absolute 8-week returns, monthly means
    D["q_sel"] = D.groupby("date")["selected" if sel else "prior"].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1)
    m_all = D.groupby("date").agg(r=("r40", "mean"), g=("gate", "first"))
    m_top = D[D.q_sel == 5].groupby("date").agg(r=("r40", "mean"), g=("gate", "first"))
    def gate_cmp(m):
        on, off = m[m.g].r, m[~m.g].r
        return {"on_mean": float(on.mean()), "off_mean": float(off.mean()), "on_months": int(len(on)), "off_months": int(len(off)),
                "on_hit": float((on > 0).mean()), "off_hit": float((off > 0).mean()),
                "welch_t": float(stats.ttest_ind(on, off, equal_var=False).statistic)}
    out["S3_gate"] = {"all_stocks": gate_cmp(m_all), "top_quintile": gate_cmp(m_top)}
    # S4 risk: template 5/5 vs not
    D["pass"] = D.tt == 5
    g = D.groupby(["date", "pass"]).agg(mae=("mae40", "mean"), big=("r40", lambda s: (s < -.10).mean()), x=("x40", "mean")).unstack()
    out["S4_template_risk"] = {"mae_pass": float(g["mae"][True].mean()), "mae_fail": float(g["mae"][False].mean()),
                               "mae_diff": nw((g["mae"][True] - g["mae"][False]).values, 2),
                               "loss10_pass": float(g["big"][True].mean()), "loss10_fail": float(g["big"][False].mean()),
                               "loss10_diff": nw((g["big"][True] - g["big"][False]).values, 2),
                               "excess_pass": float(g["x"][True].mean()), "excess_fail": float(g["x"][False].mean()),
                               "excess_diff": nw((g["x"][True] - g["x"][False]).values, 2), "share_pass": float(D["pass"].mean())}
    # S5 VCP setup inside template-5/5 stocks
    T = D[D["pass"]].copy()
    T["vcp"] = (T.tight <= .8) & (T.dry <= .9) & (T.hi52 >= .90) & (T.ext <= 10)
    gv = T.groupby(["date", "vcp"]).x40.mean().unstack()
    both = gv.dropna()
    out["S5_vcp"] = {"setups": int(T.vcp.sum()), "share_of_pass": float(T.vcp.mean()),
                     "excess_vcp": float(T[T.vcp].x40.mean()), "excess_other_pass": float(T[~T.vcp].x40.mean()),
                     "hit_vcp": float((T[T.vcp].x40 > 0).mean()), "hit_other_pass": float((T[~T.vcp].x40 > 0).mean()),
                     "diff_monthly": nw((both[True] - both[False]).values, 2) if True in both and False in both else None}
    json.dump(out, open(os.path.join(HERE, "stats2.json"), "w"), indent=1, default=float)
    print(json.dumps({"selected": sel, "primary": out["primary"], "overlap": out.get("overlap")}, default=float, indent=1))

if __name__ == "__main__":
    main()
