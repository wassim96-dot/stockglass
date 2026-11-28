#!/usr/bin/env python3
"""Timing-score backtest harness (28 Nov 2026). No network: reads backtest/cache/*.json (fetch.mjs) and
data/market-history.json. For each stock and each month-end it builds a prices-only input, runs the skill's own
score.py in-process (copied unchanged in backtest/sv/; only TIMING is set to technicals only, because valuation needs
point-in-time fundamentals), and records the timing score, its label, the score before the market-fear blend, and the
forward total returns over 20 / 40 / 60 trading days for the stock and SPY.

Port check: on 5 stocks x 5 dates, score.py run as a separate program (unchanged weights) must give the same technical
part, and the final score must equal 0.9 x technical + 0.1 x fear-for-this-stock (score.py's own formula).
Outputs: backtest/results.csv, backtest/port_check.json, backtest/run_summary.json.
"""
import contextlib, csv, datetime as dt, io, json, math, os, subprocess, sys, tempfile
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__)); SV = os.path.join(HERE, "sv"); CACHE = os.path.join(HERE, "cache")
sys.path.insert(0, SV)
import score, market_fear                      # noqa: E402  (the skill's own code)
score.TIMING = {"tech": 100}                   # valuation (15%) left out: technicals carry the pre-fear weight
H = (20, 40, 60)                               # 4, 8, 12 weeks in trading days

def load(t):
    p = os.path.join(CACHE, t + ".json")
    return json.load(open(p)) if os.path.exists(p) else None

SPY = load("SPY"); SPY_I = {d: i for i, d in enumerate(SPY["d"])}
MH = market_fear.load(os.path.join(HERE, "..", "data", "market-history.json"))

def month_ends():
    out = []
    for i, d in enumerate(SPY["d"]):
        if d < "2012-01-01": continue
        nxt = SPY["d"][i + 1] if i + 1 < len(SPY["d"]) else None
        if (nxt is None or nxt[:7] != d[:7]) and i + max(H) < len(SPY["d"]): out.append(d)
    return out

DATES = month_ends()
FEAR = {}
for d in DATES:
    try: FEAR[d] = market_fear.reading(MH, d)
    except SystemExit: FEAR[d] = None

def back(dates, vals, i, days):
    """value on the last bar at least `days` calendar days before bar i (as score.py's prep does)"""
    tgt = (dt.date.fromisoformat(dates[i]) - dt.timedelta(days=days)).isoformat(); j = i
    while j > 0 and dates[j] > tgt: j -= 1
    return vals[j] if dates[j] <= tgt else None

def weekly(P, i, n):
    wk = {}
    for k in range(max(0, i - n * 7), i + 1):
        y, w, _ = dt.date.fromisoformat(P["d"][k]).isocalendar(); wk[(y, w)] = k
    return [wk[x] for x in sorted(wk)]

def beta_at(P, i):
    ks = weekly(P, i, 110)[-105:]; xs, ys = [], []
    for a, b in zip(ks, ks[1:]):
        da, db = P["d"][a], P["d"][b]
        if da in SPY_I and db in SPY_I:
            ys.append(math.log(P["a"][b] / P["a"][a])); xs.append(math.log(SPY["a"][SPY_I[db]] / SPY["a"][SPY_I[da]]))
    if len(xs) < 52: return None
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx if vx else None

def build_input(t, sector, P, i, d):
    bars = [{"d": P["d"][k], "h": P["h"][k], "l": P["l"][k], "c": P["c"][k], "v": P["v"][k]} for k in range(max(0, i - 299), i + 1)]
    wks = [{"d": P["d"][k], "h": P["h"][k], "l": P["l"][k], "c": P["c"][k], "v": P["v"][k]} for k in weekly(P, i, 70)[-70:]]
    j = SPY_I[d]; sp1y = back(SPY["d"], SPY["c"], j, 365)
    b = beta_at(P, i)
    return {"meta": {"ticker": t, "name": t, "currency": "USD", "sector": sector, "us_listed": True},
            "price": {}, "market": {"beta": None if b is None else round(b, 3), "benchmark": "SPY",
                                    "benchmark_perf_1y": None if sp1y is None else (SPY["c"][j] / sp1y - 1) * 100},
            "annual": [], "tech": {"ohlc": bars, "weekly": wks}, "market_fear": FEAR.get(d)}, b

def run_score(D, d, tmp):
    i, o = os.path.join(tmp, "in.json"), os.path.join(tmp, "out.json")
    json.dump(D, open(i, "w")); sys.argv = ["score.py", i, o, "--as-of", d]
    with contextlib.redirect_stdout(io.StringIO()): score.main()
    return json.load(open(o))

def fwd(P, PI, d, h):
    j = SPY_I[d]
    if j + h >= len(SPY["d"]): return None, None
    t1 = SPY["d"][j + h]; i0 = PI.get(d)
    k = PI.get(t1)
    if k is None:                                   # stock has no bar that day: last bar before it
        k = max((x for x in range(i0, min(len(P["d"]), i0 + h + 10)) if P["d"][x] <= t1), default=None)
    if i0 is None or k is None or k <= i0: return None, None
    return P["a"][k] / P["a"][i0] - 1, SPY["a"][j + h] / SPY["a"][j] - 1

def work(stock):
    t, sector = stock["ticker"], stock["sector"]; P = load(t)
    if not P: return [], {"ticker": t, "skipped": "no price data"}
    PI = {d: i for i, d in enumerate(P["d"])}; rows = []; skip = {"no_bar": 0, "short_history": 0, "no_score": 0}
    tmp = tempfile.mkdtemp(prefix="bt-" + t + "-")
    for d in DATES:
        i = PI.get(d)
        if i is None: skip["no_bar"] += 1; continue
        if i < 260: skip["short_history"] += 1; continue
        D, b = build_input(t, sector, P, i, d)
        try: R = run_score(D, d, tmp)
        except Exception as e: skip["no_score"] += 1; continue
        T = R["scores"]["timing"]; MFo = T.get("market_fear") or {}
        if T.get("score") is None: skip["no_score"] += 1; continue
        f = {h: fwd(P, PI, d, h) for h in H}
        F = FEAR.get(d) or {}
        rows.append({"ticker": t, "sector": sector, "date": d, "score": T["score"], "label": T.get("label"), "tier": T.get("tier"),
                     "score_nofear": MFo.get("timing_before", T["score"]), "tech_part": R["groups"]["tech"]["timing_score"],
                     "fear_for_stock": MFo.get("score_for_stock"), "fear_applied": MFo.get("applied"), "fear_phase": F.get("phase"),
                     "beta": None if b is None else round(b, 3),
                     "mom12_1": P["a"][i - 21] / P["a"][i - 252] - 1 if i >= 252 else None,
                     **{f"r{h}": f[h][0] for h in H}, **{f"spy{h}": f[h][1] for h in H},
                     **{f"x{h}": (f[h][0] - f[h][1]) if f[h][0] is not None else None for h in H}})
    return rows, {"ticker": t, **skip, "rows": len(rows)}

def port_check(stocks):
    out = []; tmp = tempfile.mkdtemp(prefix="bt-port-")
    picks = [DATES[k] for k in (12, 40, 70, 100, len(DATES) - 2)]
    for s in stocks[:5]:
        P = load(s["ticker"]); PI = {d: i for i, d in enumerate(P["d"])} if P else {}
        for d in picks:
            i = PI.get(d)
            if i is None or i < 260: continue
            D, _ = build_input(s["ticker"], s["sector"], P, i, d)
            R = run_score(D, d, tmp)
            ip, op = os.path.join(tmp, "p_in.json"), os.path.join(tmp, "p_out.json"); json.dump(D, open(ip, "w"))
            subprocess.run([sys.executable, os.path.join(SV, "score.py"), ip, op, "--as-of", d], capture_output=True, check=True)
            S = json.load(open(op)); tp_in, tp_sub = R["groups"]["tech"]["timing_score"], S["groups"]["tech"]["timing_score"]
            mf = R["scores"]["timing"].get("market_fear") or {}
            expect = round(.9 * tp_in + .1 * mf["score_for_stock"], 1) if mf.get("applied") else tp_in
            out.append({"ticker": s["ticker"], "date": d, "tech_inprocess": tp_in, "tech_score_py": tp_sub,
                        "final": R["scores"]["timing"]["score"], "final_expected": expect,
                        "match": abs(tp_in - tp_sub) < 1e-9 and abs(R["scores"]["timing"]["score"] - expect) <= .051})
    return out

if __name__ == "__main__":
    U = json.load(open(os.path.join(HERE, "universe.json")))["stocks"]
    pc = port_check(U); json.dump(pc, open(os.path.join(HERE, "port_check.json"), "w"), indent=1)
    print(f"port check: {sum(x['match'] for x in pc)}/{len(pc)} match")
    with Pool(os.cpu_count() or 2) as pool: res = pool.map(work, U)
    rows = [r for rs, _ in res for r in rs]; info = [s for _, s in res]
    keys = list(rows[0].keys())
    with open(os.path.join(HERE, "results.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=keys); w.writeheader(); w.writerows(rows)
    summ = {"dates": len(DATES), "first": DATES[0], "last": DATES[-1], "rows": len(rows), "stocks_with_rows": sum(1 for s in info if s.get("rows")),
            "fear_missing_dates": sum(1 for d in DATES if not FEAR.get(d)), "per_stock": info,
            "port_check": f"{sum(x['match'] for x in pc)}/{len(pc)}"}
    json.dump(summ, open(os.path.join(HERE, "run_summary.json"), "w"), indent=1)
    print(json.dumps({k: v for k, v in summ.items() if k != "per_stock"}))
