#!/usr/bin/env python3
"""Statistics for the timing-score backtest (28 Nov 2026), as pre-registered in backtest/HYPOTHESES.md.

Reads backtest/results.csv; writes backtest/stats.json (every number the report quotes) and backtest/charts/*.csv
(chart data). Deterministic: bootstrap seed 20261128.
- IC: monthly Spearman correlation between score and forward excess return across stocks (months with >= 20 stocks).
- Newey–West t: HAC standard error of a monthly series, lag = horizon in months (overlapping windows).
- Quintiles: within each month, score ranks cut into 5 groups; spread = top minus bottom quintile mean excess return.
- Block bootstrap: 10,000 resamples of months in blocks of 6, for the mean spread's 95% interval.
- H2: Favourable minus (Unfavourable + Poor) mean excess return per month (Poor alone: 64 observations, merged).
- H3: Fama–MacBeth: monthly OLS of excess return on z-scored timing score, 12-1 momentum and beta.
- H4: monthly IC of the final score minus IC of the score before the market-fear blend.
- Holm correction over the 6 primary tests (two-sided p-values).
"""
import json, math, os
import numpy as np, pandas as pd
from scipy import stats

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, "charts"); os.makedirs(OUT, exist_ok=True)
d = pd.read_csv(os.path.join(HERE, "results.csv"), parse_dates=["date"])
HZ = {20: ("4 weeks", 1), 40: ("8 weeks", 2), 60: ("12 weeks", 3)}
RNG = np.random.default_rng(20261128)

def nw(x, lag):
    """mean, Newey–West t and two-sided p of a 1-D series"""
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

def monthly_ic(df, col, y):
    g = df.dropna(subset=[col, y]).groupby("date")
    return g.apply(lambda s: stats.spearmanr(s[col], s[y]).statistic if len(s) >= 20 else np.nan, include_groups=False).dropna()

def ic_block(df, col, h, lag):
    ic = monthly_ic(df, col, f"x{h}"); r = nw(ic.values, lag)
    se = abs(r["mean"] / r["t"]) if r["t"] else float("nan")   # Newey–West standard error of the mean IC
    return dict(mean_ic=r["mean"], t_nw=r["t"], p=r["p"], months=r["n"], share_pos=float((ic > 0).mean()), ic_ir=float(ic.mean() / ic.std()),
                ic_ci95=[r["mean"] - 1.96 * se, r["mean"] + 1.96 * se], ic_sd=float(ic.std())), ic

def quintiles(df, col, y):
    q = df.dropna(subset=[col, y]).copy()
    q["q"] = q.groupby("date")[col].transform(lambda s: pd.qcut(s.rank(method="first"), 5, labels=False) + 1)
    by = q.groupby(["date", "q"])[y].mean().unstack()
    return by, (by[5] - by[1])

def winsor(s, lo=.01, hi=.99): a, b = s.quantile([lo, hi]); return s.clip(a, b)

res = {"sample": {"rows": int(len(d)), "stocks": int(d.ticker.nunique()), "months": int(d.date.nunique()),
                  "first": str(d.date.min().date()), "last": str(d.date.max().date()),
                  "mean_stocks_per_month": float(d.groupby("date").ticker.count().mean()),
                  "score_mean": float(d.score.mean()), "score_sd": float(d.score.std()),
                  "labels": d.label.value_counts().to_dict(), "fear_phases": d.fear_phase.value_counts().to_dict()}}

# H1: IC and quintiles
res["H1"] = {}; ic_series = {}
for h, (nm, lag) in HZ.items():
    r, ic = ic_block(d, "score", h, lag); ic_series[h] = ic
    by, spread = quintiles(d, "score", f"x{h}"); sp = nw(spread.values, lag)
    byw = quintiles(d.assign(**{f"x{h}": d.groupby("date")[f"x{h}"].transform(winsor)}), "score", f"x{h}")[0]
    r.update(quintile_mean_excess={int(k): float(v) for k, v in by.mean().items()},
             quintile_mean_excess_winsorized={int(k): float(v) for k, v in byw.mean().items()},
             spread_mean=sp["mean"], spread_t_nw=sp["t"], spread_p=sp["p"], spread_ci95=block_boot(spread.values),
             spread_share_pos=float((spread > 0).mean()))
    res["H1"][nm] = r
    by.mean().rename("mean_excess").to_csv(os.path.join(OUT, f"quintiles_{h}.csv"))
ic8 = ic_series[40]
pd.DataFrame({"ic_8w": ic8, "ic_8w_12m_avg": ic8.rolling(12).mean()}).to_csv(os.path.join(OUT, "ic_over_time.csv"))

# H2: labels
ORDER = ["Favourable entry conditions", "Mostly favourable entry conditions", "Neutral entry conditions", "Unfavourable entry conditions", "Poor entry conditions"]
res["H2"] = {}
for h, (nm, lag) in HZ.items():
    y = f"x{h}"; lab = {}
    for L in ORDER:
        s = d[d.label == L][y].dropna()
        lab[L] = dict(n=int(len(s)), mean_excess=float(s.mean()) if len(s) else None, median_excess=float(s.median()) if len(s) else None,
                      hit_rate=float((s > 0).mean()) if len(s) else None)
    best = d[d.label == ORDER[0]].groupby("date")[y].mean(); worst = d[d.label.isin(ORDER[3:])].groupby("date")[y].mean()
    spr = (best - worst).dropna(); t = nw(spr.values, lag)
    means = [lab[L]["mean_excess"] for L in ORDER[:4]]
    res["H2"][nm] = dict(labels=lab, spread_mean=t["mean"], spread_t_nw=t["t"], spread_p=t["p"], spread_months=t["n"],
                         spread_ci95=block_boot(spr.values), order_spearman=float(stats.spearmanr(range(4), means).statistic) * -1)
    pd.DataFrame(lab).T.to_csv(os.path.join(OUT, f"labels_{h}.csv"))

# H3: Fama–MacBeth with momentum and beta
res["H3"] = {}
for h, (nm, lag) in HZ.items():
    y = f"x{h}"; co = []
    for dt_, s in d.dropna(subset=["score", "mom12_1", "beta", y]).groupby("date"):
        if len(s) < 30: continue
        Z = lambda v: (v - v.mean()) / v.std()
        X = np.column_stack([np.ones(len(s)), Z(s.score), Z(s.mom12_1), Z(s.beta)])
        b = np.linalg.lstsq(X, s[y].values, rcond=None)[0]; co.append(b)
    co = np.array(co)
    res["H3"][nm] = {k: nw(co[:, i], lag) for i, k in enumerate(["intercept", "score", "momentum_12_1", "beta"])}
    res["H3"][nm]["months"] = int(len(co))
    r2, _ = ic_block(d, "mom12_1", h, lag); res["H3"][nm]["momentum_alone_ic"] = r2["mean_ic"]

# H4: market-fear blend
res["H4"] = {}
for h, (nm, lag) in HZ.items():
    a = monthly_ic(d, "score", f"x{h}"); b = monthly_ic(d, "score_nofear", f"x{h}")
    diff = (a - b).dropna(); t = nw(diff.values, lag)
    res["H4"][nm] = dict(ic_with_fear=float(a.mean()), ic_without_fear=float(b.mean()), diff_mean=t["mean"], diff_t_nw=t["t"], diff_p=t["p"], months=t["n"])

# Holm over the 6 primary tests
prim = {"H1 IC 4 weeks": res["H1"]["4 weeks"]["p"], "H1 IC 8 weeks": res["H1"]["8 weeks"]["p"], "H1 IC 12 weeks": res["H1"]["12 weeks"]["p"],
        "H2 label spread 8 weeks": res["H2"]["8 weeks"]["spread_p"], "H3 score beyond momentum 8 weeks": res["H3"]["8 weeks"]["score"]["p"],
        "H4 fear blend 8 weeks": res["H4"]["8 weeks"]["diff_p"]}
items = sorted(prim.items(), key=lambda kv: kv[1]); m = len(items); adj = {}; run = 0
for i, (k, p) in enumerate(items): run = max(run, min(1, (m - i) * p)); adj[k] = run
res["holm"] = {k: {"p": prim[k], "p_holm": adj[k], "significant_5pct": adj[k] < .05} for k in prim}
res["tests_run"] = {"primary": m, "robustness_and_secondary": 0}

# robustness
rob = {}; n_rob = 0
for nm_, mask in {"2012–2018": d.date < "2019-01-01", "2019–latest": d.date >= "2019-01-01",
                  "calm": d.fear_phase == "calm", "after stress": d.fear_phase == "after",
                  "stress (early, peak, fading)": d.fear_phase.isin(["early", "peak", "fading", "fading_unconfirmed"])}.items():
    rob[nm_] = {}
    for h, (nm, lag) in HZ.items():
        r, _ = ic_block(d[mask], "score", h, lag); _, sp = quintiles(d[mask], "score", f"x{h}"); n_rob += 1
        rob[nm_][nm] = dict(mean_ic=r["mean_ic"], t_nw=r["t_nw"], months=r["months"], spread_mean=float(sp.mean()))
sn = d.copy()
for c in ["score", "x20", "x40", "x60"]: sn[c] = sn[c] - sn.groupby(["date", "sector"])[c].transform("mean")
rob["sector-neutral"] = {}
for h, (nm, lag) in HZ.items():
    r, _ = ic_block(sn, "score", h, lag); _, sp = quintiles(sn, "score", f"x{h}"); n_rob += 1
    rob["sector-neutral"][nm] = dict(mean_ic=r["mean_ic"], t_nw=r["t_nw"], months=r["months"], spread_mean=float(sp.mean()))
res["robustness"] = rob; res["tests_run"]["robustness_and_secondary"] = n_rob + 2 * 3   # + H2–H4 at the other horizons
# checks that the null result is not a data error: the score must track the PAST return (placebo), and its link to momentum
dd = d.sort_values(["ticker", "date"]).copy(); dd["past60"] = dd.groupby("ticker")["x60"].shift(3)   # excess return over the 12 weeks before t
res["checks"] = {"placebo_ic_score_vs_past_12w": float(monthly_ic(dd, "score", "past60").mean()),
                 "ic_score_vs_momentum_12_1": float(monthly_ic(d.assign(m=d.mom12_1), "score", "m").mean())}
json.dump(res, open(os.path.join(HERE, "stats.json"), "w"), indent=1, default=float)

# short summary for the chat
f = lambda v: f"{v:+.3f}"
for nm in ("4 weeks", "8 weeks", "12 weeks"):
    r = res["H1"][nm]
    print(f"H1 {nm:8s} IC {f(r['mean_ic'])} t {r['t_nw']:+.2f} p {r['p']:.3f} pos {r['share_pos']:.0%} IR {r['ic_ir']:+.2f} | Q5−Q1 {r['spread_mean']*100:+.2f}% CI [{r['spread_ci95'][0]*100:+.2f}, {r['spread_ci95'][1]*100:+.2f}]")
for nm in ("4 weeks", "8 weeks", "12 weeks"):
    r = res["H2"][nm]; print(f"H2 {nm:8s} Fav−(Unfav+Poor) {r['spread_mean']*100:+.2f}% t {r['spread_t_nw']:+.2f} | " + " ".join(f"{L.split()[0][:6]} {v['mean_excess']*100:+.2f}%/{v['hit_rate']:.0%}" for L, v in r['labels'].items() if v['n']))
for nm in ("4 weeks", "8 weeks", "12 weeks"):
    r = res["H3"][nm]; print(f"H3 {nm:8s} FM score {r['score']['mean']*100:+.3f}% t {r['score']['t']:+.2f} | mom {r['momentum_12_1']['mean']*100:+.3f}% t {r['momentum_12_1']['t']:+.2f} | beta t {r['beta']['t']:+.2f} | mom alone IC {f(r['momentum_alone_ic'])}")
for nm in ("4 weeks", "8 weeks", "12 weeks"):
    r = res["H4"][nm]; print(f"H4 {nm:8s} IC with fear {f(r['ic_with_fear'])} without {f(r['ic_without_fear'])} diff t {r['diff_t_nw']:+.2f}")
print("Holm:", {k: round(v["p_holm"], 3) for k, v in res["holm"].items()})
for k, v in rob.items(): print("rob", k, {h: (round(x["mean_ic"], 3), round(x["t_nw"], 2)) for h, x in v.items()})
