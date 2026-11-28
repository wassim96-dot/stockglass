#!/usr/bin/env python3
"""Score a stock from input.json -> result.json.

Usage: python3 score.py input.json result.json [--lens balanced|value|growth|dividend] [--prev prev.json] [--news analysis.json] [--as-of YYYY-MM-DD]

Same 0-10 banded scoring as the StockGlass Lite dashboard: each metric is mapped
through piecewise-linear bands, groups average their scored metrics, the total is
a lens-weighted average of group scores. Missing values are excluded, never guessed.
"""
import re, json, math, sys, statistics as st
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from catalyst import guidance_block, news_block, third_score
from ownership import ownership_block
from flows import flows_block
from datetime import date, timedelta

def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) else None

def band(v, s):
    if v is None or not s: return None
    if v <= s[0][0]: return s[0][1]
    for (a, x), (b, y) in zip(s, s[1:]):
        if v <= b: return x + (y - x) * (v - a) / (b - a)
    return s[-1][1]

def cagr(a, b, n):
    if a is None or b is None or a <= 0 or n <= 0: return None
    return -100.0 if b <= 0 else ((b / a) ** (1 / n) - 1) * 100

def div(a, b, k=1.0):
    return a / b * k if a is not None and b not in (None, 0) else None

pct = lambda d=1: (lambda v: f"{v:.{d}f}%")
xf = lambda d=1: (lambda v: f"{v:.{d}f}×")
G6 = [[-5, 0], [0, 2], [5, 4.5], [10, 6.5], [15, 8], [25, 10]]
PE = [[5, 9.5], [8, 9], [12, 8.5], [18, 7.5], [25, 6], [35, 4], [50, 2], [80, .5]]

# key, group, label, formatter, bands, explanation
REG = [
 ("revCagr5","growth","Revenue CAGR 5y",pct(),G6,"5-year compound revenue growth"),
 ("revCagr3","growth","Revenue CAGR 3y",pct(),G6,"3-year compound revenue growth"),
 ("epsCagr5","growth","EPS CAGR 5y",pct(),[[-5,0],[0,2],[5,4.5],[10,6.5],[20,9],[30,10]],"5-year diluted EPS growth"),
 ("fcfCagr5","growth","FCF CAGR 5y",pct(),[[-5,0],[0,2.5],[5,4.5],[10,6.5],[20,9],[30,10]],"5-year free-cash-flow growth"),
 ("revYoY","growth","Revenue growth YoY",pct(),[[-10,0],[0,3],[5,5],[10,6.5],[20,8.5],[35,10]],"latest year vs prior"),
 ("epsYoY","growth","EPS growth YoY",pct(),[[-15,0],[0,3],[8,5.5],[15,7.5],[25,9],[40,10]],"latest EPS vs prior"),
 ("gross","profit","Gross margin",pct(),[[10,1],[25,4],[40,6.5],[55,8.5],[70,10]],"pricing power"),
 ("op","profit","Operating margin",pct(),[[0,1],[8,4],[15,6],[25,8],[35,9.5],[50,10]],"core profitability"),
 ("net","profit","Net margin",pct(),[[-5,0],[0,2],[5,4],[10,6],[20,8.5],[30,10]],"net profit / sales"),
 ("fcfM","profit","FCF margin",pct(),[[0,1],[5,3.5],[10,5.5],[20,8],[30,10]],"FCF / revenue"),
 ("roe","profit","ROE",pct(),[[0,1],[5,3.5],[10,5.5],[15,7],[25,9],[40,10]],"return on equity"),
 ("roe5","profit","ROE 5y avg",pct(),[[0,1],[5,3.5],[10,5.5],[15,7],[25,9],[40,10]],"average ROE"),
 ("roic","profit","ROIC",pct(),[[2,.5],[6,3.5],[10,6],[15,8],[25,10]],"NOPAT / invested capital"),
 ("gpa","profit","Gross profit / assets",pct(),[[5,1],[15,4],[25,6.5],[35,8.5],[50,10]],"gross profitability (Novy-Marx 2013)"),
 ("ndEbitda","health","Net debt / EBITDA",xf(),[[-2,10],[0,9.5],[1,8],[2,6],[3,4],[4,2],[5,.5],[7,0]],"<0 = net cash"),
 ("intCov","health","Interest cover",xf(),[[.5,0],[1,1],[2,2.5],[5,5.5],[10,8],[20,10]],"EBIT / interest"),
 ("de","health","Debt / equity",pct(0),[[0,10],[30,9],[60,8],[100,6.5],[150,4.5],[250,2],[400,0]],"total debt / equity"),
 ("current","health","Current ratio",xf(2),[[.6,.5],[.8,2],[1,4],[1.2,6],[1.5,7.5],[2,8]],"current assets / liabilities; liquidity flag: low values are penalised, high values earn no extra credit"),
 ("quick","health","Quick ratio",xf(2),[[.3,.5],[.5,1.5],[.8,3.5],[1,5.5],[1.5,7.5],[2,9],[3,10]],"(CA − inventory) / CL"),
 ("pe","value","P/E trailing",xf(),PE,"price / trailing EPS"),
 ("peFwd","value","P/E forward",xf(),[[5,9.5],[8,9],[12,8.5],[17,7.5],[23,6],[32,4],[45,2],[70,.5]],"price / next-year EPS"),
 ("peg","value","PEG",xf(2),[[.3,10],[.5,9.5],[1,8.5],[1.5,7],[2,5.5],[3,3],[5,1]],"P/E ÷ growth"),
 ("ps","value","P/S",xf(),[[.7,9.5],[1,9],[2,8],[4,6.5],[8,4],[15,1.5],[25,.5]],"market cap / revenue"),
 ("pfcf","value","P/FCF",xf(),[[6,9.5],[8,9],[12,8.5],[18,7],[25,5.5],[40,3],[60,1]],"market cap / FCF"),
 ("evEbitda","value","EV / EBITDA",xf(),[[4,9.5],[6,9],[10,8],[14,6.5],[20,4.5],[30,2],[45,.5]],"EV / EBITDA"),
 ("fcfY","value","FCF yield",pct(),[[0,.5],[2,4],[4,6.5],[6,8.5],[9,10]],"FCF / market cap"),
 ("shY","value","Net payout yield",pct(),[[-2,1],[0,2.5],[1,4.5],[3,7],[5,9],[8,10]],"(dividends + buybacks − share issuance) / market cap (Boudoukh, Michaely, Richardson & Roberts 2007)"),
 ("impG","value","Implied FCF growth",lambda v:f"{v:.1f}%/yr",[[0,10],[2,9],[3,7.5],[4,6],[5,4.5],[6,3],[8,1]],"perpetual FCF growth the price assumes: (WACC − FCF yield) / (1 + FCF yield); long-run economy ≈ 4%"),
 ("pb","value","P/B",xf(2),[[.5,9],[.8,8],[1,7],[1.5,5],[2,3.5],[3,1.5]],"price / book; scored for banks and insurers only"),
 ("piotroski","quality","Piotroski F",lambda v:f"{v:.0f}/9",[[0,0],[3,3],[5,5.5],[7,7.5],[8,9],[9,10]],"9-point strength score"),
 ("beneish","quality","Beneish M",lambda v:f"{v:.2f}",[[-3.2,10],[-2.6,9.5],[-2.22,7],[-1.78,4],[-1,2],[0,0]],"manipulation risk; safe < −2.22"),
 ("altman","quality","Altman Z",lambda v:f"{v:.1f}",[[1,.5],[1.8,2],[2.2,3.5],[3,6.5],[5,8.5],[8,10]],"distress risk; safe > 3"),
 ("conv","quality","FCF / net income",pct(0),[[0,.5],[50,4],[80,6.5],[100,8],[130,10]],"cash backing of earnings"),
 ("gmStab","quality","Gross margin σ",lambda v:f"{v:.1f} pt",[[1,9.5],[2,9],[3,8],[6,6],[10,3.5],[15,1.5]],"5y margin stability"),
 ("assetG","quality","Asset growth",pct(),[[-10,7],[0,8],[5,7.5],[10,6.5],[20,4.5],[35,2.5],[60,.5]],"total-asset growth over the last year; fast balance-sheet expansion predicts lower returns (investment factor: Cooper, Gulen & Schill 2008; Fama-French 2015 CMA)"),
 ("capexAb","quality","Abnormal capex",pct(),[[-40,6.5],[-15,7.5],[0,8],[15,7.5],[30,6.5],[50,5.5],[100,4],[200,3]],"capex / average revenue (this year and last) vs its own mean over the 3 previous years (5 for semiconductors and energy); surges predict lower returns, most in cash-rich firms (Titman, Wei & Xie 2004). Not below 7 when revenue grew faster than capex; −1 when a surge above +30% is financed by more debt. Half weight for utilities and telecoms; not used for REITs, banks and insurers"),
 ("spread","quality","ROIC − WACC",lambda v:f"{v:+.1f} pt",[[-3,0],[0,3],[3,6],[8,8.5],[15,10]],"return on capital minus WACC (CAPM cost of equity, after-tax cost of debt)"),
 ("divY","div","Dividend yield",pct(2),[[0,2],[.5,3],[1.5,5],[2.5,6.5],[4,8.5],[6,9.5],[9,6],[12,3]],">9% = trap risk"),
 ("payout","div","Payout ratio",pct(0),[[0,10],[30,9],[50,8],[70,6.5],[90,4],[120,1.5],[150,.5]],"dividends / EPS"),
 ("divCagr","div","Dividend CAGR 5y",pct(),[[0,3],[3,5],[7,7.5],[10,9],[15,10]],"5y DPS growth"),
 ("streak","div","Raise streak",lambda v:f"{v:.0f} y",[[0,2],[3,4],[5,5.5],[10,7],[25,9],[40,10]],"consecutive raises"),
 ("rsi","tech","RSI 14",lambda v:f"{v:.0f}",[[15,3],[25,4.5],[35,6],[50,7.5],[60,7],[70,4.5],[80,2],[90,.5]],"overbought >70, oversold <30"),
 ("macd","tech","MACD histogram",lambda v:f"{v:+.2f}",None,"12/26/9 momentum"),
 ("adx","tech","ADX 14",lambda v:f"{v:.0f}",None,"trend strength with direction"),
 ("boll","tech","Bollinger %B",lambda v:f"{v:.2f}",[[-.1,3],[0,4],[.2,6],[.5,7.5],[.8,6.5],[1,4.5],[1.15,3]],"position in the 20-day ±2σ band; >1 above upper, <0 below lower"),
 ("s200","tech","vs 200-day average",pct(),[[-25,.5],[-10,3],[0,5.5],[10,8],[20,9.5]],"long-term trend; monotone, flat above +20%"),
 ("stack","tech","Trend regime",lambda v:f"{v:.0f}/2",[[0,1],[1,5.5],[2,10]],"price > SMA200 and SMA50 > SMA200"),
 ("mom","tech","12-1 momentum (risk-adj.)",lambda v:f"{v:+.2f}",[[-1,.5],[-.5,2.5],[0,5],[.5,7],[1,8.5],[1.5,9.5],[2.5,10]],"12-month return skipping the last month, divided by annual volatility"),
 ("vol","tech","Volatility (ann.)",pct(0),[[12,9.5],[20,8.5],[30,7],[45,5],[65,2.5],[100,.5]],"annualised"),
 ("hi52","tech","vs 52-week high",pct(),[[-50,1],[-30,3],[-15,5.5],[-5,8],[0,9]],"proximity to the 52-week high (George-Hwang 2004)"),
 ("rev1m","tech","1-month reversal",pct(),[[-20,7.5],[-10,6.5],[0,5.5],[10,4],[20,2.5],[35,1]],"last-month return; short-term losers tend to rebound, winners to give back"),
 ("ext50","tech","ATR multiple from 50-day",lambda v:f"{v:+.1f}×",[[-4,4],[-2,5.5],[0,6.5],[2,7],[3,5.5],[4,3.5],[6,1.5]],"(price − SMA50) / ATR14; beyond +4 the stock is stretched and entries tend to give back"),
 ("rvol","tech","Relative volume 1m",lambda v:f"{v:.2f}×",[[.5,3.5],[.8,4.5],[1,5.5],[1.3,7],[1.8,8],[3,7]],"average volume of the last month vs the prior months (high-volume return premium, Gervais-Kaniel-Mingelgrin 2001)"),
 ("rs","tech","Relative strength 12m",lambda v:f"{v:+.1f} pt",[[-30,1],[-10,3.5],[0,5],[10,7],[25,9],[50,10]],"12-month return minus sector/benchmark 12-month return"),
 ("upside","mkt","Analyst upside",pct(),[[-20,1],[-5,3],[0,4.5],[10,6.5],[20,8.5],[40,10]],"target vs price; weak predictor, low weight"),
 ("beta","mkt","Beta",lambda v:f"{v:.2f}",[[.5,8.5],[.8,7.5],[1,6.5],[1.3,5],[1.7,3],[2.5,1]],"market sensitivity; lower is better (betting against beta)"),
 ("dilut","mkt","Share count Δ / yr",pct(),[[-5,10],[-2,8.5],[0,6],[2,3.5],[5,1]],"3y share CAGR; <0 = buybacks"),
 ("surprise","mkt","Earnings surprise",pct(),[[-15,1],[-5,3],[0,5],[3,6.5],[8,8.5],[15,10]],"reported EPS vs consensus, average of the last 2 quarters (post-earnings drift)"),
 ("revision","mkt","EPS estimate revision 3m",pct(),[[-10,.5],[-3,3],[0,5],[2,6.5],[5,8.5],[10,10]],"change in next-year consensus EPS over 3 months"),
]
GROUPS = [("growth","Growth"),("profit","Profitability"),("health","Financial health"),("value","Valuation"),
          ("quality","Quality"),("div","Dividend"),("tech","Technicals"),("mkt","Market & sentiment")]
# Second score: entry timing (short term), fixed weights favouring current valuation and price action
TIMING = {"tech": 85, "value": 15}  # 2–12 weeks: price setup + a valuation risk factor; earnings news lives in the third score (no double counting). Review 18 Nov 2026: references/indicator-review.md
# Per-indicator weights (long-term, timing). Weight 0 = shown as context, not scored. Evidence in references/methodology.md.
# Weights after the indicator-redundancy review (18 Nov 2026, references/indicator-review.md): correlated indicators share one
# theme weight (equal-weighted composite), weak or mechanical duplicates are context only (weight 0).
WI = {"revCagr5": (.5, 0), "revCagr3": (.5, 0), "epsCagr5": (.5, 0), "fcfCagr5": (.5, 0), "revYoY": (0, 0), "epsYoY": (0, 0),
      "gross": (.25, 0), "op": (.25, 0), "net": (0, 0), "fcfM": (1, 0), "roe": (0, 0), "roe5": (0, 0), "roic": (1.25, 0), "gpa": (1.5, 0),
      "ndEbitda": (.75, 0), "intCov": (.5, 0), "de": (.25, 0), "current": (.25, 0), "quick": (0, 0),
      "pe": (.225, .225), "peFwd": (.4, .4), "peg": (0, 0), "ps": (.25, .25), "pfcf": (0, 0), "evEbitda": (.625, .625), "fcfY": (.625, .625), "shY": (.625, .625), "impG": (0, 0), "pb": (0, 0),
      "piotroski": (1, 0), "beneish": (.5, 0), "altman": (0, 0), "conv": (1, 0), "gmStab": (.75, 0), "assetG": (.5, 0), "capexAb": (.25, 0), "spread": (0, 0),
      "divY": (.5, 0), "payout": (1, 0), "divCagr": (.75, 0), "streak": (0, 0),
      "rsi": (0, .2), "macd": (0, 0), "adx": (0, 0), "boll": (0, .1), "s200": (0, .25), "stack": (0, .25), "mom": (0, .5), "vol": (1.25, .5),
      "hi52": (0, .5), "rev1m": (0, .5), "rs": (0, .25), "ext50": (0, .2), "rvol": (0, 0),
      "upside": (0, 0), "beta": (0, 0), "dilut": (1.25, 0), "surprise": (0, 0), "revision": (0, 0)}
# Composites (members share one theme weight) and why dropped indicators are context only; shown on the page.
COMPOSITES = {"Revenue growth": ["revCagr5", "revCagr3"], "Earnings-power growth": ["epsCagr5", "fcfCagr5"], "Margins": ["gross", "op"],
              "Leverage": ["ndEbitda", "intCov", "de"], "Value": ["peFwd", "pe", "evEbitda", "fcfY", "shY"],
              "Trend": ["mom", "hi52", "s200", "stack"], "Reversal / overextension": ["rev1m", "rsi", "ext50", "boll"], "Earnings news": ["surprise", "revision"], "Investment": ["assetG", "capexAb"]}
CONTEXT_WHY = {"revYoY": "inside the 3y/5y revenue growth", "epsYoY": "noisy one-year change", "net": "dominated by gross profitability; already inside the earnings yield",
               "roe": "leverage-driven; ROIC and gross profitability cover it (ρ≈0.95 with ROIC)", "roe5": "overlaps ROIC; stability is measured in Quality",
               "quick": "near-duplicate of the current ratio (ρ≈0.9)", "peg": "no evidence it beats its parts; relies on optimistic growth forecasts",
               "pfcf": "exact inverse of the FCF yield", "pb": "scored for banks and insurers only", "impG": "expectations check, shown under the timing score",
               "altman": "its parts (leverage, profitability, valuation) are already scored; distress risk is not rewarded (Dichev 1998)",
               "spread": "ranks almost exactly like ROIC (ρ≈1.0)", "streak": "no evidence that raise streaks predict returns",
               "macd": "technical rule without out-of-sample support (Bajgrowicz & Scaillet 2012)", "adx": "technical rule without out-of-sample support",
               "rvol": "weak, unreplicated signal", "upside": "analyst targets predict returns weakly and lag prices", "beta": "volatility carries the low-risk effect; beta would count it twice",
               "surprise": "scored once, in the third score (timing + guidance & news)", "revision": "scored once, in the third score (timing + guidance & news)"}
FIN_OVERRIDE = {"pb": (1, .75)}  # banks and insurers: price/book replaces the EBITDA and FCF multiples
VAL_STRESS = (4.0, 2.0)          # valuation group below 4/10 gets extra weight in both scores: × (1 + 2 × (4 − v) / 4), up to × 3 at 0
EVENT_WINDOW = 84                 # days: an earnings date within 12 weeks falls inside the entry-timing horizon
def vmult(v):
    t, k = VAL_STRESS
    return 1.0 if v is None or v >= t else 1 + k * (t - max(v, 0)) / t
def direction_note(tscore, s200, mom, beta, phase, is_etf=False, market=None):
    """Long / short setup note under the timing score (references/methodology.md §5l, version 2). Not a score.
    A trend counts only when 12-1 momentum is large relative to volatility (|mom| > 0.5; mom is already the 12-1 return
    divided by annual volatility): revised time-series momentum (Lim, Wang & Yao 2018), vol-scaled momentum (Barroso &
    Santa-Clara 2015). Shorts are flagged only in a calm, rising market (S&P 500 above its 200-day average with a positive
    24-month return): momentum crashes hit shorts when losers rebound after high-volatility bear markets, worst for high
    beta (Daniel & Moskowitz 2016)."""
    if tscore is None: return None
    up = s200 is not None and s200 > 0 and mom is not None and mom > .5
    down = s200 is not None and s200 < 0 and mom is not None and mom < -.5
    calm = phase == "calm"; mk = market or {}
    bull = not mk or (bool(mk.get("above_200d")) and (mk.get("ret_24m") or 0) > 0)
    fad = bool(phase) and phase.startswith("fading")
    hb = beta is not None and beta >= 1.3; lb = beta is not None and beta <= 0.8
    bt = f" (beta {beta:.2f})" if beta is not None else ""
    if tscore >= 6 and up:
        lab = "Long setups favoured"
        note = "Strong uptrend (momentum above half its volatility) and favourable timing."
        if phase == "early": note += " Early fear is a high-risk entry: spreading entries over the coming weeks has historically beaten buying the first days of a panic."
    elif tscore <= 4 and down and calm and bull:
        lab = "Short setups favoured"
        note = "Strong downtrend with weak timing in a calm, rising market: trend-following shorts have worked on average; the risk is a squeeze on good news" + (f", larger with high beta{bt}" if hb else "") + "."
    elif tscore <= 4 and down:
        why = "the market is in a downtrend" if not bull else "market fear is " + ("fading" if fad else "only just over" if phase == "after" else "high")
        lab = "Shorts risky, no long setup"
        note = (f"Strong downtrend, but {why}: losers tend to rebound hardest after high-volatility declines" + (f", especially high-beta stocks{bt}" if hb else bt) +
                ". Shorting now carries momentum-crash risk; a long entry needs the trend to turn first.")
    else:
        lab = "Neutral"
        note = "No clear edge for longs or shorts: trend, momentum and timing do not line up."
        if phase == "fading": note += " Fear is fading with confirmation, historically the best market phase for adding long exposure" + (f"; high-beta stocks{bt} tend to rebound most." if hb else ".")
        elif phase == "early": note += " Fear has only just begun: bottoms usually come after a period of fear, not at its start."
    if lb and phase and not calm: note += f" Low beta{bt}: moves less than the market in both directions."
    return {"label": lab, "note": note, "phase": phase}

TT_FX = {"EUR": 1, "USD": .92, "GBP": 1.17, "GBp": .0117, "GBX": .0117, "CHF": 1.06, "SEK": .087, "NOK": .085, "DKK": .134, "PLN": .23, "CAD": .66, "JPY": .006, "HKD": .118, "AUD": .6}

def _ttw(c, k):
    """IBD-style weighted return in percent: 40% last quarter, 20% each of the 6-, 9- and 12-month returns. k = bars per quarter."""
    r = [(c[-1] / c[-1 - n] - 1) * 100 if len(c) > n and c[-1 - n] else None for n in (k, 2 * k, 3 * k, 4 * k)]
    return None if None in r else {"w": .4 * r[0] + .2 * (r[1] + r[2] + r[3]), "r3": r[0], "r6": r[1], "r9": r[2], "r12": r[3]}

def trend_template(day, wk, price, rs, phase, regime_lab, bench_wk=None, vix_pct=None, mkt=None, cur=None, bench_name=None):
    """Minervini Trend Template (Trade Like a Stock Market Wizard, 2013; Think & Trade Like a Champion, 2017). Context only, never scored.
    Version 2 (24 Nov 2026, references/methodology.md §5o): rules 1, 2, 4 and 5 are one condition (price > 50 > 150 > 200-day), so the verdict
    counts 5 blocks (moving-average stack, rising 200-day, >= 25% above the 52-week low, within 25% of the high, relative strength); a falling
    200-day is a hard fail. Relative strength: IBD-style weighted return vs the broad index (tech.benchmark_weekly), passing when ahead of it,
    else the 12-month relative strength. Stop guide 2 x ATR(20), flagged (not capped) above 10%, with his 1.25% risk sizing rule. Extra
    context lines (RS line high, extension, one-day spike, volume, liquidity) are not counted. Daily closes (>= 200 bars) or weekly 10/30/40-week."""
    def avg(c, k, n):
        a = c[:len(c) - k] if k else c
        return sum(a[-n:]) / n if len(a) >= n else None
    if len(day) >= 200: c, h, l, n50, n150, n200, m1, m5, yr, q, src = [b["c"] for b in day], [num(b.get("h")) or b["c"] for b in day], [num(b.get("l")) or b["c"] for b in day], 50, 150, 200, 21, 105, 252, 63, "daily"
    elif len(wk) >= 62: c, h, l, n50, n150, n200, m1, m5, yr, q, src = [b["c"] for b in wk], [num(b.get("h")) or b["c"] for b in wk], [num(b.get("l")) or b["c"] for b in wk], 10, 30, 40, 4, 22, 52, 13, "weekly (10/30/40-week averages)"
    else: return None
    p = price or c[-1]
    s50, s150, s200, s200m1, s200m5 = avg(c, 0, n50), avg(c, 0, n150), avg(c, 0, n200), avg(c, m1, n200), avg(c, m5, n200)
    hi, lo = max(h[-yr:]), min(l[-yr:])
    sl1 = (s200 / s200m1 - 1) * 100 if s200 and s200m1 else None; sl5 = (s200 / s200m5 - 1) * 100 if s200 and s200m5 else None
    up = sl1 is not None and sl1 > 0; up5 = up and sl5 is not None and sl5 > 0; fall = sl1 is not None and sl1 < 0
    aL = (p / lo - 1) * 100 if lo else None; bH = (1 - p / hi) * 100 if hi else None
    bw = [b for b in (bench_wk or []) if num(b.get("c"))]
    sw = _ttw(c, q); mw = _ttw([b["c"] for b in bw], 13) if len(bw) > 52 else None
    rs_w = sw["w"] - mw["w"] if sw and mw else None
    rs_val, rs_src = (rs_w, "IBD weighting vs " + (bench_name or "the broad index")) if rs_w is not None else ((rs, "12-month relative strength vs the benchmark") if rs is not None else (None, None))
    sg = lambda v: ("+" if v >= 0 else "") + f"{v:.1f}"
    rules = [("Price above the 150- and 200-day averages", s150 is not None and p > s150 and p > s200),
             ("150-day average above the 200-day", s150 is not None and s150 > s200),
             (f"200-day average rising for at least 1 month ({sg(sl1) + '% over 1 month' if sl1 is not None else '∅'}{', ' + sg(sl5) + '% over 5 months' if sl5 is not None else ''}{'; 4–5 months preferred' if up and not up5 else ''})", up),
             ("50-day average above the 150- and 200-day", s50 is not None and s150 is not None and s50 > s150 and s50 > s200),
             ("Price above the 50-day average", s50 is not None and p > s50),
             (f"At least 25% above the 52-week low ({'+%.0f%%' % aL if aL is not None else '∅'}; 30% in the 2013 book; best setups +100–300%)", aL is not None and aL >= 25),
             (f"Within 25% of the 52-week high ({'−%.0f%%' % bH if bH is not None else '∅'})", bH is not None and bH <= 25),
             (f"Relative strength (rule 8): {sg(rs_val) + ' pt, ' + rs_src if rs_val is not None else '∅'}; passes when ahead of the market (stand-in for his IBD rank ≥ 70)", None if rs_val is None else rs_val >= 0)]
    blocks = [("moving-average stack (price > 50 > 150 > 200-day)", rules[0][1] and rules[1][1] and rules[3][1] and rules[4][1]), ("rising 200-day", up),
              ("25% above the low", rules[5][1]), ("within 25% of the high", rules[6][1]), ("relative strength", rules[7][1])]
    bk = [b for b in blocks if b[1] is not None]; n = sum(1 for b in bk if b[1]); miss = [b[0] for b in bk if not b[1]]; met = not miss
    stop = None
    if len(day) > 21:
        tr = [max(day[i]["h"] - day[i]["l"], abs(day[i]["h"] - day[i - 1]["c"]), abs(day[i]["l"] - day[i - 1]["c"])) for i in range(len(day) - 20, len(day)) if num(day[i].get("h")) and num(day[i].get("l"))]
        if len(tr) == 20:
            st = 2 * (sum(tr) / 20) / p * 100
            stop = {"pct": round(st, 1), "level": round(p * (1 - st / 100), 4), "over_10": st > 10, "max_position_pct": round(min(100, 1.25 / min(max(st, .1), 10) * 100))}
    m = mkt or {}; r24 = num(m.get("ret_24m"))
    crash = ((r24 is not None and r24 < 0) or bool(m.get("bear_state"))) and vix_pct is not None and vix_pct >= 80
    why = [x for x in ((f"fear phase: {phase}" if phase in ("early", "peak") else None), ("market regime hostile" if regime_lab == "Hostile" else None),
                       ("momentum-crash risk: S&P 500 down over 24 months with the VIX high" if crash else None)) if x]
    if fall: v = ("🔴", "Not a stage-2 uptrend under his rules: the 200-day average is falling, which he treats as disqualifying.")
    elif met and why: v = ("🟡", f"Template met, but market-stress conditions he says call for caution ({'; '.join(why)}).")
    elif met: v = ("🟢", "Meets Minervini's Trend Template: a setup filter, not a buy signal. He also requires a proper base with a breakout above its pivot on volume, and strong earnings.")
    elif len(miss) <= 2 and rules[6][1]: v = ("🟡", f"Partial: {' and '.join(miss)} missing. Not a setup under his rules yet.")
    else: v = ("🔴", "Not a stage-2 uptrend under his rules.")
    # context only (not counted)
    X = {}
    if len(day) >= 60:
        dc = [b["c"] for b in day]
        iso = lambda s: tuple(_d(s).isocalendar()[:2])
        sw_ = {}
        for b in day: sw_[iso(b["d"])] = b["c"]          # last daily close of each ISO week
        if len(sw_) < 52: sw_ = {iso(b["d"]): b["c"] for b in wk if _d(b.get("d"))}
        if bw and len(sw_) >= 52:
            bm = {iso(b["d"]): b["c"] for b in bw if _d(b.get("d"))}
            rl = [v_ / bm[k_] for k_, v_ in list(sw_.items())[-52:] if k_ in bm]
            if len(rl) >= 40: X["rs_line_high"] = rl[-1] >= max(rl) * .999; X["rs_line_leads"] = X["rs_line_high"] and bH is not None and bH > 2
        if stop and s50:
            atr = stop["pct"] / 200 * p; X["ext_atr"] = round((p - s50) / atr, 1) if atr else None; X["ext_pct"] = round((p / s50 - 1) * 100, 1)
        X["max_1d"] = round(max((dc[i] / dc[i - 1] - 1) * 100 for i in range(len(dc) - 21, len(dc))), 1)
        vv = [num(b.get("v")) for b in day[-50:] if num(b.get("v"))]
        if len(vv) >= 40:
            av = sum(vv) / len(vv); v10 = [num(b.get("v")) for b in day[-10:] if num(b.get("v"))]
            X["vol_dry"] = round(sum(v10) / len(v10) / av, 2) if v10 else None
            for i in range(len(day) - 1, len(day) - 6, -1):
                if day[i]["c"] > day[i - 1]["c"] and num(day[i].get("v")): X["up_vol"] = round(day[i]["v"] / av, 2); X["up_day"] = day[i]["d"]; break
            to = sorted(b["c"] * b["v"] for b in day[-50:] if num(b.get("v"))); med = to[len(to) // 2]
            X["turnover"] = round(med); X["turnover_eur"] = round(med * TT_FX[cur]) if cur in TT_FX else None
    # second count, "full check": template blocks + entry points (weaker evidence, rule-of-thumb thresholds); the template count stays the main reading
    FI = []
    if X.get("rs_line_high") is not None: FI.append(("RS line at a new high", bool(X["rs_line_high"])))
    if X.get("ext_atr") is not None: FI.append(("not extended above the 50-day", X["ext_pct"] >= 0 and X["ext_atr"] <= 4))
    if X.get("max_1d") is not None: FI.append(("no lottery-like spike", X["max_1d"] < 10))
    if X.get("up_vol") is not None or X.get("vol_dry") is not None: FI.append(("volume support", (X.get("up_vol") or 0) >= 1.4 or (X.get("vol_dry") is not None and X["vol_dry"] < .75)))
    if X.get("turnover_eur") is not None: FI.append(("enough liquidity", X["turnover_eur"] >= 1e6))
    f_ok = [f for f in FI if f[1]]; f_no = [f[0] for f in FI if not f[1]]
    f_read = ("The 200-day average is falling: the extra points don't change that." if fall else
              (f"Trend qualifies; entry not ideal (missing: {'; '.join(f_no)})." if f_no else "Trend and entry points all line up under his checks.") if met else
              f"Trend not qualified yet (missing: {'; '.join(miss)}); entry points {len(f_ok)}/{len(FI)}.")
    full = {"passed": n + len(f_ok), "total": len(bk) + len(FI), "entry": [{"point": a_, "pass": b_} for a_, b_ in FI], "entry_missing": f_no, "read": f_read}
    return {"version": 2, "rules": [{"rule": r, "pass": ok if ok is None else bool(ok)} for r, ok in rules], "passed": n, "total": len(bk), "met": met, "full": full,
            "falling_200": fall, "missing": miss, "source": src, "slope_200": {"m1": None if sl1 is None else round(sl1, 2), "m5": None if sl5 is None else round(sl5, 2)},
            "rs_proxy": None if rs_val is None else round(rs_val, 1), "rs_source": rs_src,
            "rs_w": None if not sw else {k: round(x, 1) for k, x in sw.items()}, "stop": stop, "stress": why, "context": X,
            "verdict_icon": v[0], "verdict": v[1],
            "note": "Rule-based description of Minervini's criteria, not investment advice. Not scored. Each ingredient (momentum, nearness to the 52-week high, moving-average trend) has academic support; the full template has never been tested in a peer-reviewed study."}

def crypto_direction(tscore, s200, mom, phase):
    """Long / short note for a coin (references/crypto.md §5): a trend counts when 12-1 momentum exceeds half its volatility;
    shorts only in a bear phase (holders still in profit, historically the weakest phase); risky in accumulation (bottom zone)."""
    if tscore is None: return None
    up = s200 is not None and s200 > 0 and mom is not None and mom > .5
    down = s200 is not None and s200 < 0 and mom is not None and mom < -.5
    if tscore >= 6 and up:
        lab, note = "Long setups favoured", "Strong uptrend (momentum above half its volatility) and favourable timing." + (" But the cycle is in distribution: holders sit on large profits, so trail the position tightly." if phase == "distribution" else "")
    elif tscore <= 4 and down and phase == "bear":
        lab, note = "Short setups favoured", "Strong downtrend in a crypto bear phase with holders still in profit: historically the weakest phase. The risk is violent short squeezes."
    elif tscore <= 4 and down:
        lab = "Shorts risky, no long setup"
        note = ("Downtrend, but price is below holders' average cost (accumulation): the zone where bottoms form and short squeezes are violent. A long entry needs the trend to turn first."
                if phase == "accumulation" else "Downtrend outside a bear phase: no clear edge for shorts. A long entry needs the trend to turn first.")
    else:
        lab = "Neutral"
        note = "No clear edge for longs or shorts: trend, momentum and timing do not line up." + (
            " The cycle is in accumulation: historically the best one-year entry zone, but timing within it is uncertain." if phase == "accumulation" else
            " The cycle is still in a bear phase: in past cycles the bull market returned only after price fell below holders' average cost (accumulation)." if phase == "bear" else "")
    return {"label": lab, "note": note, "phase": phase}

FEAR_W = .10                     # market fear (S&P 500 variance risk premium) share of the entry-timing score, applied after the groups
MIN_COVERAGE = .4               # a group with less than 40% of its indicator weight found is left out of a score
# Cost of capital defaults: Damodaran, 1 Nov 2026 (US T-bond 4.94%, implied ERP 4.41%). Override with market.rf / market.erp.
DEFAULT_RF, DEFAULT_ERP = 4.94, 4.41
# Sector-relative bands, used when meta.industry_medians is given (blended 2/3 relative, 1/3 absolute)
REL_DIFF = {"gross": [[-25, 1], [-10, 3.5], [0, 5.5], [10, 7.5], [20, 9], [30, 10]], "op": [[-15, 1], [-7, 3], [0, 5.5], [7, 7.5], [15, 9], [25, 10]],
            "net": [[-10, 1], [-5, 3], [0, 5.5], [5, 7.5], [10, 9], [20, 10]], "roic": [[-10, .5], [-4, 3], [0, 5.5], [5, 7.5], [10, 9], [20, 10]]}
REL_RATIO = [[.4, 9.5], [.6, 8.5], [.8, 7], [1, 5.5], [1.3, 4], [1.7, 2.5], [2.5, 1]]
REL_MAP = {"gross": "gross", "op": "op", "net": "net", "roic": "roic", "pe": "pe", "evEbitda": "ev_ebitda", "ps": "ps"}
import re as _re
FIN_RX = _re.compile(r"\b(bank|banks|banking|insurance|insurer|reinsurance|savings institution|thrift|capital markets|brokers?)", _re.I)
FIN_NA = ["gross", "gpa", "capexAb", "fcfM", "conv", "ndEbitda", "intCov", "de", "current", "quick", "evEbitda", "pfcf", "fcfY", "impG", "altman", "beneish"]
LT_TIERS = [(7.5, "Strong long-term profile", "Business quality, growth and balance sheet are strong, and the price is reasonable for them."),
            (6.2, "Favourable long-term profile", "The business case is sound; one or two areas (often valuation) hold the score back."),
            (4.5, "Mixed long-term profile", "Strengths and weaknesses roughly offset; the long-term case depends on which of them improves."),
            (3.0, "Weak long-term profile", "Fundamentals or valuation are weak enough that a long-term case is hard to make."),
            (-1, "Poor long-term profile", "Most fundamental areas score poorly.")]
TM_TIERS = [(7.5, "Favourable entry conditions", "Trend and momentum support the price now, and valuation does not add unusual downside risk."),
            (6.2, "Mostly favourable entry conditions", "The setup leans positive, but one factor (stretch, weak trend or a rich price) argues for patience."),
            (4.5, "Neutral entry conditions", "Price action and valuation do not line up: one is supportive, the other is not."),
            (3.0, "Unfavourable entry conditions", "The trend is against the price, or the price is rich with weakening momentum."),
            (-1, "Poor entry conditions", "Downtrend with no valuation support.")]
def tier(sc, tiers):
    if sc is None: return None
    for i, (th, lab, mean) in enumerate(tiers):
        if sc >= th: return {"tier": i + 1, "label": lab, "meaning": mean}

# 27 Nov 2026: trend indicators and EPS surprise/revision left the long-term score (they are scored in entry timing and in the third
# score); the Technicals group now holds volatility only (low-risk factor) and Market & sentiment holds share dilution only, so their
# group weights were scaled to keep those two indicators at their former effective share: tech × 1.25/2.0, mkt × 1.25/1.5.
LENS = {"balanced":{"growth":8,"profit":21,"health":9,"value":22,"quality":14,"div":3,"tech":7.5,"mkt":9.2},
        "value":{"growth":5,"profit":15,"health":12,"value":33,"quality":15,"div":5,"tech":3.8,"mkt":7.5},
        "growth":{"growth":20,"profit":22,"health":6,"value":12,"quality":12,"div":0,"tech":10,"mkt":10},
        "dividend":{"growth":3,"profit":14,"health":15,"value":15,"quality":15,"div":28,"tech":1.9,"mkt":5.8}}

# ---------- ETF mode (meta.asset_type = "etf"): the fund is judged as a vehicle and the market it holds is judged by price ----------
# Evidence and thresholds in references/etf.md. Bands: (value, score) pairs, as for stocks.
ETF_REG = [
 ("ter","cost","TER (ongoing charges)",lambda v:f"{v:.2f}%",[[.05,10],[.1,9.5],[.2,8.5],[.3,7.5],[.45,6],[.6,4.5],[.8,3],[1,2],[1.5,.5]],"yearly fund fee, taken from the fund's assets"),
 ("td","cost","Tracking difference",lambda v:f"{v:+.2f}%/yr",[[-2,0],[-1,2],[-.6,4],[-.4,5.5],[-.25,7],[-.1,8.5],[0,9.5],[.2,10]],"fund return minus index return per year (average); the real cost of holding"),
 ("te","cost","Tracking error",lambda v:f"{v:.2f}%",[[.05,10],[.1,9],[.3,7],[.6,5],[1,3],[2,1]],"volatility of the gap between fund and index"),
 ("bas","cost","Bid-ask spread",lambda v:f"{v:.2f}%",[[.02,10],[.05,9],[.1,8],[.2,6.5],[.4,4.5],[.8,2],[1.5,.5]],"cost of one round trip on the exchange"),
 ("aum","size","Fund size (AUM)",lambda v:f"{v:,.0f} M",[[10,.5],[30,2],[50,3.5],[100,5.5],[300,7],[1000,8.5],[5000,10]],"assets in millions of the fund currency; small funds close more often"),
 ("age","size","Fund age",lambda v:f"{v:.1f} y",[[.5,1],[1,3],[3,6],[5,7.5],[10,9],[15,10]],"years since launch; length of the real track record"),
 ("adv","size","Avg daily traded value",lambda v:f"{v:,.2f} M",[[.01,1],[.05,3],[.25,5],[1,7],[5,8.5],[20,10]],"exchange volume × price, millions; understates OTC trading in Europe"),
 ("prem","size","Premium / discount to NAV",lambda v:f"{v:.2f}%",[[.05,10],[.15,9],[.3,7.5],[.6,5],[1,3],[2,1],[4,0]],"absolute gap between price and net asset value"),
 ("nhold","divers","Number of holdings",lambda v:f"{v:,.0f}",[[5,1],[10,2],[20,3.5],[30,5],[50,6.5],[100,8],[300,9],[1000,10]],"securities held"),
 ("top10","divers","Top-10 weight",lambda v:f"{v:.1f}%",[[10,10],[20,9],[30,8],[45,6.5],[60,4.5],[75,3],[90,1.5]],"share of the fund in its 10 largest holdings"),
 ("maxsect","divers","Largest sector",lambda v:f"{v:.1f}%",[[20,10],[30,8.5],[40,7],[55,5],[70,3],[90,1],[100,.5]],"weight of the biggest sector"),
 ("repl","divers","Replication",lambda v:f"{v:.0f}",None,"how the fund delivers the index: physical (holds the shares) or synthetic (swap)"),
 ("ipe","value","Index P/E (trailing)",xf(),[[8,10],[11,9],[14,7.5],[17,6],[20,4.5],[24,3],[30,1.5],[40,.5]],"weighted price / earnings of the holdings"),
 ("ifpe","value","Index P/E (forward)",xf(),[[7,10],[10,9],[13,7.5],[16,6],[19,4.5],[23,3],[28,1.5],[35,.5]],"price / next-year expected earnings of the holdings"),
 ("pedev","value","P/E vs own 10-y average",lambda v:f"{v:+.1f} σ",[[-2,10],[-1,8.5],[0,6.5],[.5,5.5],[1,4],[1.5,3],[2,2],[3,.5]],"how many standard deviations the P/E sits above its 10-year average"),
 ("idy","value","Index dividend yield",pct(2),[[.5,2],[1,3],[1.5,4],[2.5,6],[3.5,7.5],[5,9],[7,9.5]],"dividends of the holdings / price"),
 ("eyg","value","Earnings yield − bond yield",lambda v:f"{v:+.1f} pt",[[-2,1],[0,3],[2,5.5],[4,7.5],[6,9],[8,10]],"1 / P/E minus the 10-year government yield (equity risk premium proxy)"),
 ("mdd","risk","Max drawdown 3y",pct(1),[[-60,.5],[-45,2],[-35,3.5],[-25,5.5],[-15,7.5],[-8,9],[0,10]],"worst peak-to-trough fall over 3 years"),
 ("sharpe","risk","Sharpe ratio 3y",lambda v:f"{v:.2f}",[[-.5,1],[0,3],[.3,5],[.6,7],[1,8.5],[1.5,10]],"(annual return − risk-free rate) / volatility, 3 years"),
 ("cagr3","risk","Return 3y (annualised)",pct(1),[[-10,1],[0,3],[5,5],[10,7],[15,9]],"context only: past return of the market held"),
]
TECH_KEYS = ["rsi", "macd", "adx", "boll", "s200", "stack", "mom", "vol", "hi52", "rev1m", "ext50", "rvol", "rs"]
# ---------- crypto mode (meta.asset_type = "crypto"): where the coin stands in the crypto cycle (on-chain), its risk and its trend ----------
# Evidence, backtest and thresholds in references/crypto.md. Data: scripts/crypto_reading.py (Coin Metrics Community, OKX, alternative.me).
CRYPTO_PH = {"accumulation": (8.5, 6.5, "Accumulation"), "bull": (6, 6, "Bull market"), "bear": (3.5, 4, "Bear market"), "distribution": (3.5, 5, "Distribution")}
CRYPTO_REG = [
 ("cyc","chain","Cycle phase (1-year view)",lambda v:f"{v}",None,"accumulation (MVRV ≤ 1), bull (above the 200-day average), bear (below it) or distribution (MVRV in the top 10% of 4 years), scored for the next year"),
 ("cycT","chain","Cycle phase (3-month view)",lambda v:f"{v}",None,"same phase, scored for the next 2–12 weeks"),
 ("mvrv","chain","MVRV (price / average cost)",lambda v:f"{v:.2f}",[[.6,9],[.8,8.5],[1,8],[1.5,6.5],[2.5,4.5],[3.5,2],[5,1]],"market value / realised value: price divided by the average price at which all coins last moved"),
 ("mvrvP","chain","MVRV vs its last 4 years",lambda v:f"{v:.0f}th pct",None,"rank of today's MVRV among the last 4 years (context)"),
 ("adg","chain","Active addresses, 1-year change",pct(1),None,"network use (context: inconsistent as a predictor)"),
 ("fund","chain","Perpetual funding (annualised)",lambda v:f"{v:+.1f}%",None,"what leveraged longs pay shorts on perpetual swaps, last 7 days (context)"),
 ("cfng","chain","Crypto Fear & Greed",lambda v:f"{v:.0f}",None,"alternative.me sentiment index, 0–100 (context: no contrarian edge in 2018–2026)"),
]
GROUPS_CRYPTO = [("chain","Cycle & on-chain"),("risk","Risk & return"),("tech","Technicals")]
WI_CRYPTO = {"cyc": (1.5, 0), "cycT": (0, 1), "mvrv": (1, 0), "mvrvP": (0, 0), "adg": (0, 0), "fund": (0, 0), "cfng": (0, 0),
             "mdd": (1, 0), "sharpe": (.5, 0), "cagr3": (.25, 0),
             # trend predicts crypto returns (time-series momentum: Liu & Tsyvinski 2021; price / moving-average ratios: Detzel et al. 2021)
             "rsi": (0, .2), "macd": (0, 0), "adx": (0, 0), "boll": (0, .1), "s200": (.5, .5), "stack": (.5, .5), "mom": (.75, 1), "vol": (.5, .25),
             "hi52": (.5, .5), "rev1m": (0, .3), "ext50": (0, .2), "rvol": (0, 0), "rs": (0, 0)}
LENS_CRYPTO = {"crypto": {"chain": 40, "risk": 20, "tech": 40}}
TIMING_CRYPTO = {"tech": 75, "chain": 25}
CONTEXT_WHY_CRYPTO = {"mvrvP": "the MVRV level and the phase carry the signal; the 4-year rank is shown for context", "adg": "predicted returns for BTC but not ETH in our test",
                      "fund": "only 30 days of free history; crowding context", "cfng": "extreme fear gave no contrarian edge in 2018–2026",
                      "cagr3": "past return, shown with a small weight", "rs": "no benchmark for crypto"}
LT_TIERS_CRYPTO = [(7.5, "Strong cycle & trend profile", "Early in the crypto cycle (holders near or below their average cost) with a healthy trend and tolerable drawdowns."),
                   (6.2, "Favourable cycle & trend profile", "The cycle or the trend is supportive; the other holds the score back."),
                   (4.5, "Mixed cycle & trend profile", "Cycle, trend and risk point in different directions."),
                   (3.0, "Weak cycle & trend profile", "Late or bearish cycle phase with a weak trend."),
                   (-1, "Poor cycle & trend profile", "Bear or distribution phase, downtrend and deep drawdowns.")]
TM_TIERS_CRYPTO = [(7.5, "Favourable entry conditions", "Confirmed uptrend with momentum in a supportive cycle phase."),
                   (6.2, "Mostly favourable entry conditions", "The trend leans positive, but the cycle phase or stretch argues for patience."),
                   (4.5, "Neutral entry conditions", "Trend and cycle do not line up."),
                   (3.0, "Unfavourable entry conditions", "Below its trend in a weak cycle phase."),
                   (-1, "Poor entry conditions", "Downtrend in a bear phase.")]
FULL_REG = REG + ETF_REG + CRYPTO_REG
GROUPS_ETF = [("cost","Cost & tracking"),("size","Size & liquidity"),("divers","Diversification & structure"),("value","Valuation (index)"),("risk","Risk & return"),("tech","Technicals")]
WI_ETF = {"ter": (.5, 0), "td": (1.5, 0), "te": (.25, 0), "bas": (.75, 0), "aum": (.75, 0), "age": (.5, 0), "adv": (.25, 0), "prem": (.5, 0),
          "nhold": (0, 0), "top10": (1, 0), "maxsect": (.5, 0), "repl": (1, 0),
          "ipe": (.25, .25), "ifpe": (.5, .5), "pedev": (1.5, 1), "idy": (0, 0), "eyg": (0, 0), "mdd": (1, 0), "sharpe": (0, 0), "cagr3": (0, 0),
          # technicals: same composites as stocks; trend weighs more at index level (Faber 2007; Moskowitz-Ooi-Pedersen 2012)
          "rsi": (0, .2), "macd": (0, 0), "adx": (0, 0), "boll": (0, .1), "s200": (.5, .5), "stack": (.5, .5), "mom": (.75, 1), "vol": (.5, .25),
          "hi52": (.5, .5), "rev1m": (0, .3), "ext50": (0, .2), "rvol": (0, 0), "rs": (.25, .25)}
CONTEXT_WHY_ETF = {"nhold": "same information as the top-10 weight", "idy": "context: dividend yield of the index", "eyg": "mixes a real earnings yield with a nominal bond yield",
                   "sharpe": "3-year Sharpe ratios are noisy; drawdown is scored", "cagr3": "past return, shown not scored"}
LENS_ETF = {"etf": {"cost": 20, "size": 12, "divers": 13, "value": 25, "risk": 10, "tech": 20}}
TIMING_ETF = {"tech": 80, "value": 20}
VEHICLE = {"cost": 20, "size": 12, "divers": 13}   # 'ETF quality' sub-score: the fund as a product, whatever the market does
LT_TIERS_ETF = [(7.5, "Strong long-term profile", "A cheap, large, well-built fund on a market that is reasonably priced and in a healthy trend."),
                (6.2, "Favourable long-term profile", "A sound fund; one area (often the market's valuation or trend) holds the score back."),
                (4.5, "Mixed long-term profile", "The fund or its market has clear weaknesses that offset the strengths."),
                (3.0, "Weak long-term profile", "Costs, structure or the market's valuation and trend make a long-term case hard."),
                (-1, "Poor long-term profile", "Most areas score poorly, or the fund is not built for holding (leveraged or inverse).")]
TM_TIERS_ETF = [(7.5, "Favourable entry conditions", "The market held is in a confirmed uptrend with momentum, and its valuation adds no unusual downside risk."),
                (6.2, "Mostly favourable entry conditions", "The trend leans positive, but stretch, a weak trend or a rich valuation argues for patience."),
                (4.5, "Neutral entry conditions", "Trend and valuation do not line up."),
                (3.0, "Unfavourable entry conditions", "The market is below its trend, or richly valued with fading momentum."),
                (-1, "Poor entry conditions", "Downtrend with no valuation support.")]

def _d(x):
    try: return date.fromisoformat(str(x)[:10])
    except Exception: return None

def prep(D, REF, hist):
    """Point-in-time preparation. Historical mode drops anything published after REF. In both modes, fields left
    null are derived exactly from dated inputs (price bars, weekly bars, dividend payments); never estimated."""
    notes = []
    meta = D.setdefault("meta", {}); P = D.setdefault("price", {}); MK = D.setdefault("market", {}); T = D.setdefault("tech", {})
    if hist:
        keep, dropped = [], []
        for r in D.get("annual", []):
            filed = _d(r.get("filed")); end = _d(r.get("end")) or _d(f"{r.get('year')}-12-31")
            avail = filed or (end + timedelta(days=90) if end else None)
            (keep if avail and avail <= REF else dropped).append(r)
        if dropped: notes.append("historical mode: fiscal years not yet published on " + str(REF) + " dropped: " + ", ".join(str(r.get("year")) for r in dropped))
        D["annual"] = keep
        for k in ("ohlc", "weekly"):
            if T.get(k): T[k] = [b for b in T[k] if _d(b.get("d")) and _d(b["d"]) <= REF]
        if D.get("dividends"): D["dividends"] = [x for x in D["dividends"] if _d(x.get("d")) and _d(x["d"]) <= REF]
    day = [b for b in T.get("ohlc") or [] if _d(b.get("d")) and num(b.get("c"))]
    wk = [b for b in T.get("weekly") or [] if _d(b.get("d")) and num(b.get("c"))]
    bars = day if len(day) >= 2 else wk
    if bars:
        lastb = bars[-1]
        if num(P.get("last")) is None: P["last"] = lastb["c"]; notes.append(f"price = close on {lastb['d']}")
        def back(days, src):
            tgt = _d(src[-1]["d"]) - timedelta(days=days); pick = None
            for b in src:
                if _d(b["d"]) <= tgt: pick = b
            return pick
        for key, days in (("perf_1w", 7), ("perf_1m", 30), ("perf_6m", 182), ("perf_1y", 365)):
            if num(P.get(key)) is None:
                src = day if day and _d(day[0]["d"]) <= _d(day[-1]["d"]) - timedelta(days=days) else wk
                b = back(days, src) if src else None
                if b: P[key] = (P["last"] / b["c"] - 1) * 100; notes.append(f"{key} derived from {'daily' if src is day else 'weekly'} closes")
        yr = [b for b in (day if day and _d(day[0]["d"]) <= _d(day[-1]["d"]) - timedelta(days=360) else wk) if _d(b["d"]) > _d(bars[-1]["d"]) - timedelta(days=365)]
        if yr:
            if num(P.get("high_52w")) is None: P["high_52w"] = max(num(b.get("h")) or b["c"] for b in yr)
            if num(P.get("low_52w")) is None: P["low_52w"] = min(num(b.get("l")) or b["c"] for b in yr)
    if len(day) < 200 and len(wk) >= 40:
        wc = [b["c"] for b in wk]
        if num(T.get("sma200")) is None and num(T.get("sma200_pct")) is None: T["sma200"] = sum(wc[-40:]) / 40; notes.append("200-day average approximated by the 40-week average")
        if len(day) < 50 and num(T.get("sma50")) is None and num(T.get("sma50_pct")) is None: T["sma50"] = sum(wc[-10:]) / 10; notes.append("50-day average approximated by the 10-week average")
    if len(day) < 21 and len(wk) >= 27 and num(T.get("vol_month")) is None and num(T.get("atr14")) is None:
        w53 = wk[-53:]; r = [math.log(b["c"] / a["c"]) for a, b in zip(w53, w53[1:])]
        T["vol_weekly_ann"] = st.pstdev(r) * math.sqrt(52) * 100; notes.append(f"volatility from {len(r)} weekly returns")
    divs = [x for x in D.get("dividends") or [] if _d(x.get("d")) and num(x.get("a")) is not None]
    if divs:
        if num(MK.get("dps_ttm")) is None:
            MK["dps_ttm"] = sum(x["a"] for x in divs if REF - timedelta(days=365) < _d(x["d"]) <= REF); notes.append("trailing dividend from dated payments")
        if not D.get("dividends_by_year"):
            by = {}
            for x in divs: by[_d(x["d"]).year] = by.get(_d(x["d"]).year, 0) + x["a"]
            D["dividends_by_year"] = {str(y): v for y, v in by.items()}
    if hist:
        for k in ("target_price", "forward_pe", "peg", "eps_revision_3m_pct"):
            if MK.get(k) is not None and not meta.get("as_of_values_checked"):
                notes.append(f"{k} was supplied: make sure it is the value as of {REF}, not today's")
    return notes

def main():
    global REG, GROUPS, WI, LENS, TIMING, LT_TIERS, TM_TIERS
    a = sys.argv[1:]
    lens = "balanced"
    if "--lens" in a:
        i = a.index("--lens"); lens = a[i + 1]; del a[i:i + 2]
    if lens not in LENS: sys.exit(f"unknown lens {lens}")
    as_of = None
    if "--as-of" in a:
        i = a.index("--as-of"); as_of = a[i + 1]; del a[i:i + 2]
    prev_runs = []
    if "--prev" in a:
        i = a.index("--prev"); pf = a[i + 1]; del a[i:i + 2]
        try:
            pr = json.load(open(pf)); prev_runs = pr if isinstance(pr, list) else pr.get("runs", [])
        except Exception as ex: print("warning: --prev file not read:", ex)
    news_items = None
    if "--news" in a:
        i = a.index("--news"); nf = a[i + 1]; del a[i:i + 2]
        try:
            nj = json.load(open(nf)); nj = nj.get("news", nj) if isinstance(nj, dict) else {"items": nj}
            news_items = nj.get("items") if isinstance(nj, dict) else None
        except Exception as ex: print("warning: --news file not read:", ex)
    inp, out = a[0], a[1]
    D = json.load(open(inp))
    if news_items is None: news_items = ((D.get("news") or {}).get("items") if isinstance(D.get("news"), dict) else D.get("news")) or []
    as_of = as_of or (D.get("meta") or {}).get("as_of_date")
    # SV_REF_DATE pins "today" for repeatable tests (selftest.py); live runs leave it unset
    REF = date.fromisoformat(as_of) if as_of else date.fromisoformat(__import__("os").environ["SV_REF_DATE"]) if __import__("os").environ.get("SV_REF_DATE") else date.today()
    is_etf = str((D.get("meta") or {}).get("asset_type") or "").lower() == "etf" or bool(D.get("etf"))
    if is_etf:
        keys = [m[0] for m in ETF_REG] + TECH_KEYS
        REG = [next(m for m in FULL_REG if m[0] == k) for k in keys]
        GROUPS, WI, LENS, TIMING, LT_TIERS, TM_TIERS = GROUPS_ETF, dict(WI_ETF), LENS_ETF, dict(TIMING_ETF), LT_TIERS_ETF, TM_TIERS_ETF
        lens = "etf"
    is_crypto = (not is_etf) and (str((D.get("meta") or {}).get("asset_type") or "").lower() == "crypto" or bool(D.get("crypto")))
    if is_crypto:
        keys = [m[0] for m in CRYPTO_REG] + ["mdd", "sharpe", "cagr3"] + TECH_KEYS
        REG = [next(m for m in FULL_REG if m[0] == k) for k in keys]
        GROUPS, WI, LENS, TIMING, LT_TIERS, TM_TIERS = GROUPS_CRYPTO, dict(WI_CRYPTO), LENS_CRYPTO, dict(TIMING_CRYPTO), LT_TIERS_CRYPTO, TM_TIERS_CRYPTO
        lens = "crypto"
    nofund = is_etf or is_crypto   # no company accounts: no guidance, earnings or stock gates
    hist_notes = prep(D, REF, bool(as_of))
    meta, P, MK, T = D.get("meta", {}), D.get("price", {}), D.get("market", {}), D.get("tech", {})
    P = {k: num(v) for k, v in P.items()}; MK = {k: num(v) for k, v in MK.items()}; T = {k: num(v) for k, v in T.items()}
    A = []
    for r in D.get("annual", []):
        r = {k: (num(v) if k not in ("year", "filed", "end") else v) for k, v in r.items()}
        for k in ("capex", "div_paid", "buyback", "int", "dep"):
            if r.get(k) is not None: r[k] = abs(r[k])
        if r.get("fcf") is None and r.get("ocf") is not None and r.get("capex") is not None: r["fcf"] = r["ocf"] - r["capex"]
        if r.get("ebitda") is None and r.get("op") is not None and r.get("dep") is not None: r["ebitda"] = r["op"] + r["dep"]
        A.append(r)
    A.sort(key=lambda r: int(r["year"]))
    TT = {k: num(v) for k, v in (D.get("ttm") or {}).items()}
    L = A[-1] if A else {}; Pv = A[-2] if len(A) > 1 else {}
    g = lambda f: TT.get(f) if TT.get(f) is not None else L.get(f)
    def same(f, base="rev"):  # (numerator, denominator) from the same period: TTM if both exist there, else latest fiscal year
        if TT.get(f) is not None and TT.get(base) is not None: return TT[f], TT[base]
        return L.get(f), L.get(base)
    px = P.get("last")
    def lat(f):  # latest value of a field within the last two fiscal years (cash-flow pages can lag a year)
        for r in A[::-1][:2]:
            if r.get(f) is not None: return r[f]
        return None
    V = {}
    def put(k, v, sc=None, disp=None, na=False, src=None):
        m = next((x for x in FULL_REG if x[0] == k), None)
        if m is None: return
        v = num(v)
        if na: V[k] = {"v": None, "s": "na", "score": None, "disp": "—"}
        else:
            score = sc if sc is not None else (band(v, m[4]) if v is not None else None)
            V[k] = {"v": v, "s": "ok" if score is not None else "nf", "score": None if score is None else round(score, 2),
                    "disp": disp or (m[3](v) if v is not None else "∅")}
        if src: V[k]["src"] = src

    span = {}
    def cg(f, n):
        s = [r for r in A if r.get(f) is not None]
        if len(s) < 2: return None
        e = s[-1]; base = [r for r in s if int(e["year"]) - int(r["year"]) >= n]
        if not base and n >= 5: base = [r for r in s if int(e["year"]) - int(r["year"]) >= n - 1]  # free data: 5 rows = 4-year span
        if not base: return None
        b = base[-1]; yrs = int(e["year"]) - int(b["year"]); span[f, n] = yrs
        return cagr(b[f], e[f], yrs)

    rev, ni, eps, fcf, op, gross = (g(x) for x in ("rev", "ni", "eps", "fcf", "op", "gross"))
    ebitda = g("ebitda")
    debt, cash, eq, assets, ca, cl, inv = (L.get(x) for x in ("debt", "cash", "equity", "assets", "ca", "cl", "inv"))
    sh = MK.get("shares_out") or L.get("shares")
    mcap = MK.get("market_cap") or (sh * px if sh and px else None)

    for key, f, n in (("revCagr5", "rev", 5), ("revCagr3", "rev", 3), ("epsCagr5", "eps", 5), ("fcfCagr5", "fcf", 5)):
        v_ = cg(f, n); y_ = span.get((f, n))
        put(key, v_, disp=(f"{v_:.1f}% ({y_}y)" if v_ is not None and y_ and y_ < n else None))
    put("revYoY", (L["rev"] / Pv["rev"] - 1) * 100 if L.get("rev") is not None and (Pv.get("rev") or 0) > 0 else None)
    put("epsYoY", (L["eps"] / Pv["eps"] - 1) * 100 if L.get("eps") is not None and (Pv.get("eps") or 0) > 0 else None)
    pos = lambda x: x if x and x > 0 else None
    for key, f in (("gross", "gross"), ("op", "op"), ("net", "ni"), ("fcfM", "fcf")):
        a_, b_ = same(f); put(key, div(a_, pos(b_), 100))
    roes = [r["ni"] / r["equity"] * 100 for r in A if r.get("ni") is not None and (r.get("equity") or 0) > 0]
    put("roe", div(ni, pos(eq), 100) if pos(eq) else (roes[-1] if roes else None))
    put("roe5", sum(roes[-5:]) / len(roes[-5:]) if len(roes) >= 3 else None)
    tr = min(max(L["tax"] / L["pretax"], 0), .4) if (L.get("pretax") or 0) > 0 and L.get("tax") is not None else .25
    ic = (debt or 0) + (eq or 0) - (cash or 0)
    roic = op * (1 - tr) / ic * 100 if op is not None and ic > 0 else None
    put("roic", roic)
    # cost of capital needs the stock's beta: without it, ROIC − WACC and the implied FCF growth are not computed (no silent beta of 1)
    beta_missing = MK.get("beta") is None
    beta = MK.get("beta") if not beta_missing else 1.0
    if beta_missing and not (is_etf or is_crypto): hist_notes.append("beta missing: cost of capital not computed, so ROIC − WACC and the implied FCF growth (expectations check) are left out")
    rf = (MK.get("rf") if MK.get("rf") is not None else DEFAULT_RF) / 100
    erp = (MK.get("erp") if MK.get("erp") is not None else DEFAULT_ERP) / 100
    ke = rf + beta * erp
    kd = min(max(lat("int") / debt, .02), .12) if (debt or 0) > 0 and (lat("int") or 0) > 0 else ke
    wacc = (mcap * ke + debt * kd * (1 - tr)) / (mcap + debt) if mcap and debt is not None else ke
    put("spread", roic - wacc * 100 if roic is not None and not beta_missing else None)
    net = (debt or 0) - (cash or 0)
    if ebitda and ebitda > 0 and debt is not None: put("ndEbitda", net / ebitda)
    elif debt is not None and cash is not None and cash > debt: put("ndEbitda", None, sc=9, disp="net cash")
    else: put("ndEbitda", None)
    if debt == 0: put("intCov", None, sc=10, disp="no debt")
    elif (debt or 0) > 0 and (lat("int") or 0) > 0 and op is not None: put("intCov", op / lat("int"))
    else: put("intCov", None)
    if eq is not None and eq <= 0 and (debt or 0) > 0: put("de", None, sc=0, disp="neg. equity")
    else: put("de", div(debt, pos(eq), 100))
    put("current", div(ca, pos(cl))); put("quick", div((ca - (inv or 0)) if ca is not None else None, pos(cl)))

    pe = MK.get("pe_ttm") or (px / eps if eps and eps > 0 and px else None)
    if eps is not None and eps <= 0: put("pe", None, sc=1, disp="n/m (loss)")
    else: put("pe", pe)
    fpe, fsrc = MK.get("forward_pe"), "consensus"
    if not fpe and eps and eps > 0 and px:
        gr = V["epsCagr5"]["v"]; gr = min(max(gr, -10), 25) if gr is not None else 6
        fpe, fsrc = px / (eps * (1 + gr / 100)), "model (trailing EPS × historical growth)"
    put("peFwd", fpe if fpe and fpe > 0 else None, src=fsrc)
    peg = MK.get("peg"); gr = V["epsCagr5"]["v"]
    if not peg and pe and gr and gr > 0: peg = pe / gr
    put("peg", peg if peg and peg > 0 else None)
    put("ps", div(mcap, pos(rev)))
    gpa_n, _ = same("gross"); gpa_v = div(gpa_n, pos(assets), 100)
    if gpa_v is not None: put("gpa", gpa_v)
    else:   # IFRS "by nature" reporters (many European firms) give no cost of sales: operating profit / assets as fallback
        op_n, _ = same("op"); opa = div(op_n, pos(assets), 100)
        put("gpa", opa, sc=band(opa, [[0, 1], [4, 4], [8, 6.5], [12, 8.5], [18, 10]]) if opa is not None else None,
            disp=(f"{opa:.1f}% (op. profit / assets)" if opa is not None else None), src="operating profit / assets (no gross profit reported)" if opa is not None else None)
    a0 = Pv.get("assets") if Pv else None
    put("assetG", (assets / a0 - 1) * 100 if assets and a0 and a0 > 0 else None)
    # abnormal capital investment (Titman, Wei & Xie 2004), version 2 (references/methodology.md §5m)
    sx = str(meta.get("sector") or "") + " " + str(meta.get("industry") or "")
    reit = bool(re.search(r"\breits?\b|real estate", sx, re.I)); cyc = bool(re.search(r"semicond|oil|gas|energy|petrol|drilling|exploration", sx, re.I))
    t_ = len(A) - 1; nb = 5 if cyc and len(A) >= 7 else 3
    avg = len(A) >= nb + 2 and all((r.get("rev") or 0) > 0 for r in A[t_ - nb - 1:])
    def ce(i):
        if i < 0 or i >= len(A): return None
        x = A[i]
        if x.get("capex") is None or not (x.get("rev") or 0) > 0: return None
        d_ = ((x["rev"] + A[i - 1]["rev"]) / 2 if i >= 1 and (A[i - 1].get("rev") or 0) > 0 else None) if avg else x["rev"]
        return abs(x["capex"]) / d_ if d_ else None
    base = [ce(t_ - k) for k in range(1, nb + 1)]; now_ = ce(t_) if t_ >= nb else None
    mb = sum(base) / nb if all(v is not None for v in base) else None
    ab = (now_ / mb - 1) * 100 if now_ is not None and mb and mb > 0 else None
    if reit: put("capexAb", None, na=True, src="not used for REITs (capex is mostly acquisitions and development)")
    elif ab is None: put("capexAb", None)
    else:
        L1, P1 = A[t_], A[t_ - 1]
        rg = L1["rev"] / P1["rev"] - 1 if (P1.get("rev") or 0) > 0 and L1.get("rev") else None
        cg_ = abs(L1["capex"]) / abs(P1["capex"]) - 1 if P1.get("capex") else None
        funded = rg is not None and cg_ is not None and rg > cg_
        debt_up = L1.get("debt") is not None and P1.get("debt") is not None and L1["debt"] > P1["debt"]
        sc_ = band(ab, [[-40, 6.5], [-15, 7.5], [0, 8], [15, 7.5], [30, 6.5], [50, 5.5], [100, 4], [200, 3]]); nt = []
        if funded and sc_ < 7: sc_ = 7; nt.append("revenue grew faster than capex")
        if not funded and ab > 30 and debt_up: sc_ = max(0, sc_ - 1); nt.append("surge financed by more debt")
        put("capexAb", ab, sc=sc_, src=f"{nb}-year base" + ("" if avg else ", single-year revenue") + ("; " + "; ".join(nt) if nt else ""))
    put("pb", div(mcap, pos(eq)) if mcap else None)
    if fcf is not None and fcf <= 0: put("pfcf", None, sc=.5, disp="n/m (neg. FCF)")
    else: put("pfcf", div(mcap, pos(fcf)))
    ev = MK.get("enterprise_value") or (mcap + (debt or 0) - (cash or 0) if mcap else None)
    if ebitda is not None and ebitda <= 0: put("evEbitda", None, sc=.5, disp="n/m (neg. EBITDA)")
    else: put("evEbitda", div(ev, pos(ebitda)) if ev and ev > 0 else None)
    put("fcfY", div(fcf, mcap, 100) if mcap else None)
    # reverse DCF: the perpetual FCF growth that makes today's price fair at the WACC (Gordon growth solved for g)
    if fcf is not None and mcap:
        if fcf <= 0: put("impG", None, sc=1, disp="n/m (neg. FCF)")
        elif beta_missing: put("impG", None, disp="n/a (beta missing)")
        else:
            fy_ = fcf / mcap; g_ = (wacc - fy_) / (1 + fy_) * 100; put("impG", 0.0 if abs(g_) < 0.05 else g_)
    else: put("impG", None)   # no FCF or market cap: missing (was a KeyError later on, found by the timing backtest, 28 Nov 2026)
    bb, dp_ = lat("buyback"), lat("div_paid")
    iss = lat("issuance")   # optional annual field: cash raised from share issuance (net payout yield subtracts it)
    put("shY", ((bb or 0) + (dp_ or 0) - abs(iss or 0)) / mcap * 100 if mcap and (bb is not None or dp_ is not None or iss is not None) else None,
        src=None if iss is not None else "issuance not given: gross payout yield")

    # Piotroski F (needs >= 7 of 9 tests computable)
    if len(A) >= 2:
        f = n = 0
        def t(c):
            nonlocal f, n
            n += 1; f += bool(c)
        Lr, Pr = L, Pv
        if Lr.get("ni") is not None and (Lr.get("assets") or 0) > 0: t(Lr["ni"] > 0)
        if Lr.get("ocf") is not None: t(Lr["ocf"] > 0)
        if None not in (Lr.get("ni"), Pr.get("ni")) and (Lr.get("assets") or 0) > 0 and (Pr.get("assets") or 0) > 0: t(Lr["ni"] / Lr["assets"] > Pr["ni"] / Pr["assets"])
        if None not in (Lr.get("ocf"), Lr.get("ni")): t(Lr["ocf"] > Lr["ni"])
        if None not in (Lr.get("debt"), Pr.get("debt")) and (Lr.get("assets") or 0) > 0 and (Pr.get("assets") or 0) > 0: t(Lr["debt"] / Lr["assets"] <= Pr["debt"] / Pr["assets"])
        if None not in (Lr.get("ca"), Pr.get("ca")) and (Lr.get("cl") or 0) > 0 and (Pr.get("cl") or 0) > 0: t(Lr["ca"] / Lr["cl"] > Pr["ca"] / Pr["cl"])
        if None not in (Lr.get("shares"), Pr.get("shares")): t(Lr["shares"] <= Pr["shares"] * 1.01)
        if None not in (Lr.get("gross"), Pr.get("gross")) and (Lr.get("rev") or 0) > 0 and (Pr.get("rev") or 0) > 0: t(Lr["gross"] / Lr["rev"] > Pr["gross"] / Pr["rev"])
        if None not in (Lr.get("rev"), Pr.get("rev")) and (Lr.get("assets") or 0) > 0 and (Pr.get("assets") or 0) > 0: t(Lr["rev"] / Lr["assets"] > Pr["rev"] / Pr["assets"])
        put("piotroski", f if n >= 7 else None)
    else: put("piotroski", None)
    need = ["rev", "recv", "gross", "ca", "ppe", "assets", "dep", "sga"]
    if len(A) >= 2 and all(L.get(k) and Pv.get(k) for k in need) and L.get("ni") is not None and L.get("ocf") is not None:
        try:
            aq = lambda x: 1 - (x["ca"] + x["ppe"]) / x["assets"]
            dr = lambda x: x["dep"] / (x["dep"] + x["ppe"])
            lv = lambda x: ((x.get("debt") or 0) + (x.get("cl") or 0)) / x["assets"]
            m = (-4.84 + .92 * (L["recv"] / L["rev"]) / (Pv["recv"] / Pv["rev"])
                 + .528 * ((Pv["rev"] - Pv["gross"]) / Pv["rev"]) / ((L["rev"] - L["gross"]) / L["rev"])
                 + .404 * aq(L) / aq(Pv) + .892 * L["rev"] / Pv["rev"] + .115 * dr(Pv) / dr(L)
                 - .172 * (L["sga"] / L["rev"]) / (Pv["sga"] / Pv["rev"])
                 + 4.679 * (L["ni"] - L["ocf"]) / L["assets"] - .327 * lv(L) / lv(Pv))
            put("beneish", m)
        except ZeroDivisionError: put("beneish", None)
    else: put("beneish", None)
    wc = ca - cl if None not in (ca, cl) else None
    tl = assets - eq if None not in (assets, eq) else None
    if assets and wc is not None and L.get("ret") is not None and op is not None and tl and tl > 0 and mcap and rev is not None:
        put("altman", 1.2 * wc / assets + 1.4 * L["ret"] / assets + 3.3 * op / assets + .6 * mcap / tl + rev / assets)
    else: put("altman", None)
    f_, n_ = same("fcf", "ni")
    if n_ is not None and n_ <= 0: put("conv", None, na=True)
    else: put("conv", div(f_, pos(n_), 100))
    gms = [r["gross"] / r["rev"] * 100 for r in A if r.get("gross") is not None and (r.get("rev") or 0) > 0]
    put("gmStab", st.pstdev(gms[-5:]) if len(gms) >= 4 else None)

    # dividends
    dby = {int(k): num(v) for k, v in (D.get("dividends_by_year") or {}).items() if num(v) is not None}
    dps = MK.get("dps_ttm")
    if not dps and lat("div_paid") and sh: dps = lat("div_paid") / sh
    if not dps and not dby:
        for k in ("divY", "payout", "divCagr", "streak"): put(k, None, na=True)
    else:
        put("divY", div(dps, px, 100) if px else None)
        put("payout", div(dps, pos(eps), 100) if dps else None)
        full = sorted(y for y in dby if y < REF.year)
        if len(full) >= 2:
            e = full[-1]
            put("divCagr", cagr(dby.get(e - 5), dby[e], 5) if dby.get(e - 5) else None)
            s = 0
            for i in range(len(full) - 1, 0, -1):
                if full[i] - full[i - 1] == 1 and dby[full[i]] > dby[full[i - 1]] * 1.001: s += 1
                else: break
            put("streak", s, disp=f"≥{s} y (data limit)" if s == len(full) - 1 else None)
        else: put("divCagr", None); put("streak", None)

    # technicals from a daily OHLC series (oldest -> newest, >= 60 bars): fills MACD, ADX/DI, RSI when not given
    ohlc = [b for b in (D.get("tech") or {}).get("ohlc", []) if all(num(b.get(k)) for k in ("h", "l", "c"))]
    T["computed_from_ohlc"] = []
    if len(ohlc) >= 60:
        c = [b["c"] for b in ohlc]; h = [b["h"] for b in ohlc]; lo = [b["l"] for b in ohlc]
        def ema(a, n):
            out = [None] * len(a); s = sum(a[:n]) / n; out[n - 1] = s; k = 2 / (n + 1)
            for i in range(n, len(a)): s = a[i] * k + s * (1 - k); out[i] = s
            return out
        e12, e26 = ema(c, 12), ema(c, 26)
        line = [x - y for x, y in zip(e12[25:], e26[25:])]
        sig = ema(line, 9)
        if T.get("macd") is None and T.get("macd_hist") is None:
            T["macd"], T["macd_signal"] = line[-1], sig[-1]; T["computed_from_ohlc"] += ["macd", "macd_signal"]
        n = 14; tr, pdm, mdm = [], [], []
        for i in range(1, len(c)):
            up, dn = h[i] - h[i - 1], lo[i - 1] - lo[i]
            pdm.append(up if up > dn and up > 0 else 0); mdm.append(dn if dn > up and dn > 0 else 0)
            tr.append(max(h[i] - lo[i], abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1])))
        str_, sp, sm = sum(tr[:n]), sum(pdm[:n]), sum(mdm[:n]); dx = []; pdi = mdi = 0
        for i in range(n, len(tr) + 1):
            if i > n: str_ += tr[i - 1] - str_ / n; sp += pdm[i - 1] - sp / n; sm += mdm[i - 1] - sm / n
            pdi, mdi = 100 * sp / str_, 100 * sm / str_
            dx.append(100 * abs(pdi - mdi) / (pdi + mdi) if pdi + mdi else 0)
        adx = sum(dx[:n]) / n
        for x in dx[n:]: adx = (adx * (n - 1) + x) / n
        if T.get("adx14") is None: T["adx14"] = adx; T["computed_from_ohlc"].append("adx14")
        if T.get("plus_di") is None: T["plus_di"], T["minus_di"] = pdi, mdi; T["computed_from_ohlc"] += ["plus_di", "minus_di"]
        if T.get("rsi14") is None:
            g = l_ = 0
            for i in range(1, n + 1): d = c[i] - c[i - 1]; g += max(d, 0); l_ += max(-d, 0)
            g /= n; l_ /= n
            for i in range(n + 1, len(c)): d = c[i] - c[i - 1]; g = (g * (n - 1) + max(d, 0)) / n; l_ = (l_ * (n - 1) + max(-d, 0)) / n
            T["rsi14"] = 100 if l_ == 0 else 100 - 100 / (1 + g / l_); T["computed_from_ohlc"].append("rsi14")
        if T.get("atr14") is None: T["atr14"] = sum(tr[-n:]) / n
        vols = [num(b.get("v")) for b in ohlc]
        if all(v_ is not None for v_ in vols[-60:]) and len(vols) >= 60:
            recent, prior = vols[-21:], [v_ for v_ in vols[:-21][-231:] if v_ is not None]
            if prior and sum(prior) > 0: T["rvol"] = (sum(recent) / len(recent)) / (sum(prior) / len(prior))
        for n_ in (50, 200):  # moving averages from the series when the source gives none
            if T.get(f"sma{n_}") is None and T.get(f"sma{n_}_pct") is None and len(c) >= n_:
                T[f"sma{n_}"] = sum(c[-n_:]) / n_; T["computed_from_ohlc"].append(f"sma{n_}")
        if not (D.get("tech") or {}).get("closes_recent"): D.setdefault("tech", {})["closes_recent"] = c[-30:]
    # technicals: recent closes (oldest -> newest) give SMA20, daily volatility and 1W perf
    cl20 = [num(x) for x in (D.get("tech") or {}).get("closes_recent", []) if num(x)]
    if len(cl20) >= 20 and T.get("sma20") is None and T.get("sma20_pct") is None: T["sma20"] = sum(cl20[-20:]) / 20
    if len(cl20) >= 11 and T.get("vol_month") is None:
        T["vol_month"] = st.pstdev([(b / a - 1) * 100 for a, b in zip(cl20, cl20[1:])][-21:])
    if len(cl20) >= 6 and P.get("perf_1w") is None and px: P["perf_1w"] = (px / cl20[-6] - 1) * 100
    if px and P.get("prev_close") is None and len(cl20) >= 2: P["prev_close"] = cl20[-2]
    for n in (20, 50, 200):
        lv, dp = T.get(f"sma{n}"), T.get(f"sma{n}_pct")
        if lv is None and dp is not None and px: T[f"sma{n}"] = px / (1 + dp / 100)
        if dp is None and lv and px: T[f"sma{n}_pct"] = (px / lv - 1) * 100
    if T.get("vol_ann_pct") is not None: T["vol_ann"] = T["vol_ann_pct"]   # annualised volatility given directly by a source
    elif T.get("vol_month") is not None: T["vol_ann"] = T["vol_month"] * math.sqrt(252)
    elif T.get("atr14") and px: T["vol_ann"] = T["atr14"] / px * 100 * math.sqrt(252)
    elif T.get("vol_weekly_ann") is not None: T["vol_ann"] = T["vol_weekly_ann"]
    else: T["vol_ann"] = None
    if T.get("bb_upper") is None and len(cl20) >= 20:
        m20, sd20 = sum(cl20[-20:]) / 20, st.pstdev(cl20[-20:])
        T["bb_upper"], T["bb_lower"] = m20 + 2 * sd20, m20 - 2 * sd20
    T["boll_pctb"] = (px - T["bb_lower"]) / (T["bb_upper"] - T["bb_lower"]) if px and T.get("bb_upper") and T.get("bb_lower") is not None and T["bb_upper"] > T["bb_lower"] else None
    put("rsi", T.get("rsi14"))
    mc, ms = T.get("macd"), T.get("macd_signal")
    if mc is not None and ms is not None:
        h = mc - ms
        put("macd", h, sc=(8.5 if mc > 0 else 6.5) if h > 0 else (2 if mc < 0 else 4.5), disp=("bull " if h > 0 else "bear ") + f"{h:+.2f}")
    elif T.get("macd_hist") is not None:
        h = T["macd_hist"]; put("macd", h, sc=7.5 if h > 0 else 3, disp=("bull " if h > 0 else "bear ") + f"{h:+.2f}")
    elif mc is not None: put("macd", mc, sc=7 if mc > 0 else 3.5, disp=f"line {mc:+.2f}", src="MACD line only: signal line not published, histogram unknown")
    else: put("macd", None)
    adx, pdi, mdi = T.get("adx14"), T.get("plus_di"), T.get("minus_di")
    if adx is not None:
        up = None if pdi is None or mdi is None else pdi >= mdi
        sc = (9 if up else 1.5) if adx >= 25 and up is not None else (7 if up else 4) if up is not None else 5
        put("adx", adx, sc=sc, disp=f"{adx:.0f}" + ("" if up is None else (" ↑" if up else " ↓")))
    else: put("adx", None)
    if T.get("ema200_pct") is None and T.get("ema200") and px: T["ema200_pct"] = (px / T["ema200"] - 1) * 100
    put("boll", T["boll_pctb"])
    put("s200", T.get("sma200_pct") if T.get("sma200_pct") is not None else T.get("ema200_pct"),
        src="SMA 200" if T.get("sma200_pct") is not None else "EMA 200 (SMA not available)")
    s20, s50, s200 = T.get("sma20"), T.get("sma50"), T.get("sma200")
    put("stack", (px > s200) + (s50 > s200) if None not in (px, s50, s200) else None)
    p1y, p1m = P.get("perf_1y"), P.get("perf_1m")
    r12_1 = ((1 + p1y / 100) / (1 + p1m / 100) - 1) * 100 if p1y is not None and p1m is not None else None
    if r12_1 is not None:
        va_ = T["vol_ann"] if T.get("vol_ann") else None
        put("mom", r12_1 / (va_ if va_ else 30), disp=f"{r12_1 / (va_ if va_ else 30):+.2f} (12-1: {r12_1:+.1f}%)",
            src=None if va_ else "volatility not available: 30% assumed")
    else: put("mom", None)
    T["mom_12_1"] = r12_1
    put("vol", T["vol_ann"]); put("rev1m", p1m)
    bench = MK.get("benchmark_perf_1y")
    sma50_, atr_ = T.get("sma50"), T.get("atr14")
    put("ext50", (px - sma50_) / atr_ if px and sma50_ and atr_ else None)
    put("rvol", T.get("rvol") if T.get("rvol") is not None else num((D.get("tech") or {}).get("rvol")))
    put("rs", p1y - bench if p1y is not None and bench is not None else None, src=("vs " + str(D["market"]["benchmark"])) if (D.get("market") or {}).get("benchmark") else None)
    put("surprise", MK.get("eps_surprise_pct")); put("revision", MK.get("eps_revision_3m_pct"))
    tp = MK.get("target_price")
    put("upside", (tp / px - 1) * 100 if tp and px else None)
    put("hi52", (px / P["high_52w"] - 1) * 100 if px and P.get("high_52w") else None)
    put("beta", MK.get("beta")); put("dilut", cg("shares", 3))

    # ETF indicators: the fund as a vehicle (cost, size, structure) and the market it holds (valuation, risk)
    etf_out, etf_notes = None, []
    if is_etf:
        E = D.get("etf") or {}
        en = lambda k: num(E.get(k))
        lev = en("leverage") or 1.0
        repl = str(E.get("replication") or "").lower()
        aclass = str(E.get("asset_class") or meta.get("asset_class") or "equity").lower()
        put("ter", en("ter_pct"))
        tds = [num(x.get("td")) for x in (E.get("tracking_difference") or []) if isinstance(x, dict) and num(x.get("td")) is not None]
        td = en("td_avg_pct"); td_n = None
        if td is None and tds: td_n = len(tds[-5:]); td = sum(tds[-5:]) / td_n
        put("td", td, disp=(f"{td:+.2f}%/yr" + (f" ({td_n}-y avg)" if td_n else "")) if td is not None else None, src=E.get("td_source"))
        put("te", en("tracking_error_pct")); put("bas", en("spread_pct"))
        aum = en("aum"); put("aum", aum / 1e6 if aum else None, src=E.get("aum_currency") or meta.get("currency"))
        inc = _d(E.get("inception")); put("age", (REF - inc).days / 365.25 if inc else None)
        adv = en("avg_daily_value")
        if adv is None and en("avg_volume") and px: adv = en("avg_volume") * px
        put("adv", adv / 1e6 if adv else None)
        pdv = en("premium_discount_pct"); put("prem", abs(pdv) if pdv is not None else None, disp=f"{pdv:+.2f}%" if pdv is not None else None)
        put("nhold", en("holdings_count")); put("top10", en("top10_pct")); put("maxsect", en("max_sector_pct"), src=E.get("max_sector"))
        if abs(lev) != 1 or lev < 0: put("repl", lev, sc=0, disp=f"{'inverse ' if lev < 0 else ''}{abs(lev):g}× daily")
        elif "synth" in repl or "swap" in repl: put("repl", 2, sc=7, disp="synthetic (swap)")
        elif "sampl" in repl or "optimi" in repl: put("repl", 1, sc=9, disp="physical, sampling")
        elif "phys" in repl or "full" in repl: put("repl", 0, sc=10, disp="physical, full")
        else: put("repl", None)
        rf_l = MK.get("rf")   # 10-year government yield of the fund's main market (%), as given
        if aclass == "equity":
            ipe, ifpe = en("index_pe"), en("index_fpe")
            put("ipe", ipe if ipe and ipe > 0 else None, src=E.get("valuation_source")); put("ifpe", ifpe if ifpe and ifpe > 0 else None, src=E.get("valuation_source"))
            dev = en("index_pe_dev_sigma")
            if dev is None and ipe and en("index_pe_avg10") and en("index_pe_sd10"): dev = (ipe - en("index_pe_avg10")) / en("index_pe_sd10")
            put("pedev", dev, src=E.get("pe_history_source"))
            put("idy", en("index_div_yield_pct"))
            ey_base = ifpe if ifpe and ifpe > 0 else ipe if ipe and ipe > 0 else None
            put("eyg", 100 / ey_base - rf_l if ey_base and rf_l is not None else None, src=(f"{'forward' if ey_base == ifpe else 'trailing'} earnings yield minus {rf_l:.2f}% 10-year yield" if ey_base and rf_l is not None else None))
        else:
            for k in ("ipe", "ifpe", "pedev", "idy", "eyg"): V[k] = {"v": None, "s": "na", "score": None, "disp": "n/m", "src": f"not meaningful for a {aclass} ETF"}
            TIMING = {"tech": 100}
        mdd = en("max_drawdown_3y_pct"); mdd = -abs(mdd) if mdd is not None else None
        put("mdd", mdd)
        r3, v3 = en("ret_3y_ann_pct"), en("vol_3y_pct")
        cr = en("cash_rate_pct") if en("cash_rate_pct") is not None else rf_l   # short-term rate (e.g. ECB deposit rate, T-bill); else the 10-year yield
        put("sharpe", (r3 - (cr if cr is not None else 0)) / v3 if r3 is not None and v3 else None,
            src=(f"risk-free rate {cr:.2f}%" if cr is not None else "risk-free rate not given: 0% used"))
        put("cagr3", r3)
        # checks (not scored): leverage, structure, closure risk, concentration, premium, tax wrapper
        hard = []
        if abs(lev) != 1 or lev < 0:
            hard.append(f"Leveraged or inverse fund ({lev:g}× the index, reset daily): over weeks its return drifts away from {lev:g}× the index (volatility decay). Built for short-term trading, not holding; long-term score capped at 2.9.")
        if aum is not None and aum < 50e6: hard.append(f"Very small fund ({aum/1e6:,.0f} M): closure risk is high (closed ETFs had a median size of about $6 M, Boehmer & Finta).")
        if pdv is not None and abs(pdv) > 2: hard.append(f"Trades {pdv:+.1f}% away from its NAV: check the price and NAV dates before buying.")
        if "synth" in repl or "swap" in repl: etf_notes.append("Synthetic replication: the index return comes from a swap with a bank; UCITS caps exposure to that bank at 10% of the fund, collateral covers the rest.")
        if E.get("securities_lending") is True: etf_notes.append("Lends its securities: a little extra income against a small counterparty risk (collateralised).")
        if aum is not None and 50e6 <= aum < 100e6: etf_notes.append(f"Small fund ({aum/1e6:,.0f} M, below the usual 100 M comfort level): some closure risk.")
        if inc and (REF - inc).days < 3 * 365: etf_notes.append("Track record shorter than 3 years.")
        if pdv is not None and 1 < abs(pdv) <= 2: etf_notes.append(f"Price {pdv:+.1f}% away from NAV.")
        t10, lh = en("top10_pct"), en("largest_holding_pct")
        if (t10 is not None and t10 > 50) or (lh is not None and lh > 15): etf_notes.append("Concentrated: " + ", ".join(x for x in ((f"top 10 = {t10:.0f}%" if t10 is not None else ""), (f"largest holding {lh:.0f}%" if lh is not None else "")) if x) + ".")
        if E.get("currency_risk"): etf_notes.append(str(E["currency_risk"]))
        lab_e = "Warning" if hard else "Watch" if any(x.startswith(("Synthetic", "Small", "Track", "Price")) for x in etf_notes) else "OK"
        facts = {k: E.get(k) for k in ("isin", "index", "issuer", "replication", "securities_lending", "distribution", "domicile", "ucits", "pea_eligible", "currency_hedged", "fund_currency", "inception", "asset_class") if E.get(k) is not None}
        facts["leverage"] = lev
        etf_out = {"facts": facts, "check": {"label": lab_e, "warnings": hard, "notes": etf_notes}, "peers": []}
        # peers on the same index: the 'vehicle' part only (cost, size, structure), so funds can be compared like for like
        def vfields(f):
            i_ = _d(f.get("inception")); r_ = str(f.get("replication") or "").lower()
            return {"ter": num(f.get("ter_pct")), "td": num(f.get("td_avg_pct")), "aum": (num(f.get("aum")) or 0) / 1e6 or None,
                    "age": (REF - i_).days / 365.25 if i_ else None,
                    "repl": (7 if ("synth" in r_ or "swap" in r_) else 9 if "sampl" in r_ else 10) if r_ else None}
        me = {"name": meta.get("name"), "ticker": meta.get("ticker"), "isin": E.get("isin"), "ter_pct": E.get("ter_pct"), "td_avg_pct": td, "aum": aum,
              "inception": E.get("inception"), "replication": E.get("replication"), "distribution": E.get("distribution"), "pea_eligible": E.get("pea_eligible"), "selected": True}
        peers = [me] + [dict(x) for x in (E.get("peers") or []) if isinstance(x, dict) and x.get("isin") != E.get("isin")]
        PW = {"ter": 1.5, "td": 1.5, "aum": 1.25, "age": .75, "repl": 1}
        fv = [vfields(x) for x in peers]
        common = [k for k in PW if all(f_[k] is not None for f_ in fv)]   # like for like: only fields every fund has
        for x, f_ in zip(peers, fv):
            sc_ = [((f_[k] if k == "repl" else band(f_[k], next(m for m in ETF_REG if m[0] == k)[4])), PW[k]) for k in common]
            x["vehicle_score"] = round(sum(a_ * b_ for a_, b_ in sc_) / sum(b_ for _, b_ in sc_), 1) if sc_ else None
        etf_out["peer_basis"] = common
        etf_out["peers"] = sorted(peers, key=lambda x: -(x["vehicle_score"] or 0)) if len(peers) > 1 else []

    crypto_out = None
    if is_crypto:
        C = D.get("crypto") or {}; cn = lambda k: num(C.get(k))
        ph = C.get("phase"); own = C.get("mvrv") is not None
        sh = (lambda v: v) if own else (lambda v: 5 + (v - 5) / 2)
        src = "own on-chain data (Coin Metrics)" if own else "Bitcoin's cycle, shrunk halfway to neutral (no on-chain data for this coin)"
        if ph in CRYPTO_PH:
            put("cyc", None, sc=sh(CRYPTO_PH[ph][0]), disp=CRYPTO_PH[ph][2], src=src); put("cycT", None, sc=sh(CRYPTO_PH[ph][1]), disp=CRYPTO_PH[ph][2], src=src)
        else: put("cyc", None); put("cycT", None)
        put("mvrv", cn("mvrv"), src=(f"realised price {cn('realized_price'):,.0f} USD" if cn("realized_price") else None))
        put("mvrvP", cn("mvrv_pct_4y")); put("adg", cn("adr_growth_1y")); put("fund", cn("funding_annual"), src="OKX perpetual swaps" if cn("funding_annual") is not None else None)
        put("cfng", cn("fng"), src=C.get("fng_date"))
        mdd = cn("max_drawdown_3y_pct"); put("mdd", -abs(mdd) if mdd is not None else None)
        r3, v3, cr = cn("ret_3y_ann_pct"), cn("vol_3y_pct"), cn("cash_rate_pct")
        put("sharpe", (r3 - (cr or 0)) / v3 if r3 is not None and v3 else None, src=(f"risk-free rate {cr:.2f}%" if cr is not None else "risk-free rate not given: 0% used"))
        put("cagr3", r3)
        crypto_out = {"phase": ph, "phase_label": CRYPTO_PH[ph][2] if ph in CRYPTO_PH else None, "own_data": own, "phase_source": src if ph else None,
                      "mvrv": cn("mvrv"), "realized_price": cn("realized_price"), "mvrv_pct_4y": cn("mvrv_pct_4y"), "ma200": cn("ma200"), "date": C.get("date"),
                      "btc": C.get("btc"), "note": C.get("note"), "fng": cn("fng"), "funding_annual": cn("funding_annual"), "adr_growth_1y": cn("adr_growth_1y"),
                      "phase_age": C.get("phase_age"), "past_accumulation": {k: v for k, v in (C.get("past_accumulation") or {}).items() if k != "episodes"} or None,
                      "btc_cycle": C.get("btc_cycle"), "btc_cycle_saved": C.get("btc_cycle_saved")}

    # sector fit: ratios that mean nothing for banks and insurers are n/a, not scored
    # sector-relative scoring (Asness-Porter-Stevens: characteristics are priced more precisely within industry)
    IM = {k: num(v) for k, v in (meta.get("industry_medians") or {}).items() if k not in ("name", "source")}
    if IM:
        for k, mk in REL_MAP.items():
            med, v = IM.get(mk), V[k]
            if med is None or v["s"] != "ok" or v["v"] is None: continue
            rel = band(v["v"] - med, REL_DIFF[k]) if k in REL_DIFF else (band(v["v"] / med, REL_RATIO) if med > 0 and v["v"] > 0 else None)
            if rel is None: continue
            v["score"] = round(2 / 3 * rel + 1 / 3 * v["score"], 2)
            v["src"] = f"vs industry {(meta.get('industry_medians') or {}).get('name', '')} median {med:g}".strip()
    is_fin = (not nofund) and bool(FIN_RX.search(str(meta.get("sector") or "") + " " + str(meta.get("industry") or "")))
    W_ = dict(WI)
    if re.search(r"utilit|telecom", str(meta.get("sector") or "") + " " + str(meta.get("industry") or ""), re.I): W_["capexAb"] = (W_["capexAb"][0] / 2, W_["capexAb"][1])
    if is_fin:
        W_.update(FIN_OVERRIDE)
        r5 = V["roe5"]["v"] if V["roe5"]["v"] is not None else (num(ni / eq * 100) if ni is not None and eq and eq > 0 else None)
        if r5 is not None: put("spread", r5 - ke * 100, src="ROE minus cost of equity (bank/insurer)")
    if is_fin:
        for k in FIN_NA: V[k] = {"v": None, "s": "na", "score": None, "disp": "n/m", "src": "not meaningful for banks and insurers"}
    # groups: weighted mean of the indicators found; coverage = share of the group's indicator weight found
    def gscore(k, j):
        sw = ws_ = tw = 0; n = 0
        for m in REG:
            if m[1] != k: continue
            wt = W_[m[0]][j]; v = V[m[0]]
            if not wt or v["s"] == "na": continue
            tw += wt
            if v["s"] == "ok": sw += wt * v["score"]; ws_ += wt; n += 1
        return (sw / ws_ if ws_ else None), (ws_ / tw if tw else 0), n
    w = LENS[lens]; groups = {}; acc = ws = ok = nf = na = 0
    vg = gscore("value", 0)[0]; vgt = gscore("value", 1)[0]
    vm_lt, vm_t = vmult(vg), vmult(vgt)
    for k, name in GROUPS:
        ms = [m for m in REG if m[1] == k]
        ok += sum(V[m[0]]["s"] == "ok" for m in ms); nf += sum(V[m[0]]["s"] == "nf" for m in ms); na += sum(V[m[0]]["s"] == "na" for m in ms)
        gs, cov, n = gscore(k, 0); gt, covt, _ = gscore(k, 1)
        groups[k] = {"name": name, "score": None if gs is None else round(gs, 1), "coverage": round(cov, 2),
                     "timing_score": None if gt is None else round(gt, 1), "timing_coverage": round(covt, 2),
                     "n": n, "total": len(ms)}
        if gs is not None and w[k] and cov >= MIN_COVERAGE: e = w[k] * cov * (vm_lt if k == "value" else 1); acc += gs * e; ws += e   # a half-empty group counts half
    score = round(acc / ws, 1) if ws and ok >= (8 if is_crypto else 10 if is_etf else 12) else None
    if is_etf and etf_out and etf_out["check"]["warnings"] and any(w_.startswith("Leveraged") for w_ in etf_out["check"]["warnings"]) and score is not None:
        score = min(score, 2.9)
    lt = tier(score, LT_TIERS)
    verdict = lt["label"] if lt else None
    tacc = tws = 0
    for k, wt in TIMING.items():
        G = groups[k]
        if G["timing_score"] is not None and G["timing_coverage"] >= MIN_COVERAGE: e = wt * G["timing_coverage"] * (vm_t if k == "value" else 1); tacc += G["timing_score"] * e; tws += e
    t_ok = groups["tech"]["timing_coverage"] >= .5 and (sum(V[m[0]]["s"] == "ok" for m in REG if m[1] == "value") >= (1 if is_etf else 2) or "value" not in TIMING)
    tscore = round(tacc / tws, 1) if tws and t_ok else None
    # market fear (references/methodology.md §5k, version 3): 0.3 x HAR variance-risk-premium rank (3-7) + 0.7 x fear phase.
    # Applied per stock as 5 + (score - 5) x clip(beta, 0.5, 1.5) (Daniel & Moskowitz 2016: high-beta stocks swing most in
    # rebounds), 10% of the timing score. ETFs and indices without a beta use 1.
    MF = {} if is_crypto else (D.get("market_fear") or {}); hist_notes_fear = []   # market fear (VIX) is equity evidence: not applied to crypto
    mf_s, mf_d = num(MF.get("score")), _d(MF.get("date")) if isinstance(MF.get("date"), str) else None
    mf_ok = mf_s is not None and mf_d is not None and 0 <= (REF - mf_d).days <= 8
    t_before = tscore; bta = num(MK.get("beta")); fb = min(1.5, max(.5, bta)) if bta is not None else 1.0
    f_adj = round(5 + (mf_s - 5) * fb, 1) if mf_s is not None else None
    if tscore is not None and mf_ok: tscore = round((1 - FEAR_W) * tscore + FEAR_W * f_adj, 1)
    fear = ({"score": mf_s, "label": MF.get("label"), "date": str(mf_d), "vix": num(MF.get("vix")), "vix_pct": num(MF.get("vix_pct")), "vix_vix3m": num(MF.get("vix_vix3m")),
             "vrp": num(MF.get("vrp")), "vrp_pct": num(MF.get("vrp_pct")), "note": MF.get("note"), "applied": tscore is not None and mf_ok, "weight": FEAR_W, "timing_before": t_before,
             "beta_used": round(fb, 2), "score_for_stock": f_adj}
            if mf_s is not None else None)
    direction = (crypto_direction(tscore, (V.get("s200") or {}).get("v"), (V.get("mom") or {}).get("v"), (crypto_out or {}).get("phase")) if is_crypto else
                 direction_note(tscore, (V.get("s200") or {}).get("v"), (V.get("mom") or {}).get("v"), bta, MF.get("phase") if mf_ok else None, is_etf, MF.get("market") if mf_ok else None))
    if fear: fear.update({"phase": MF.get("phase"), "phase_label": MF.get("phase_label"), "stress_days": MF.get("stress_days"), "premium_score": num(MF.get("premium_score")),
                          "phase_score": num(MF.get("phase_score")), "window_years": num(MF.get("window_years")), "risk_flag": bool(MF.get("risk_flag")),
                          "fading_checks": MF.get("fading_checks"), "market": MF.get("market"), "credit_check": MF.get("credit_check"),
                          # 27 Nov 2026: live reading first, saved readings for comparison, plain zones vs history, Market Regime context (never scored)
                          "live": bool(MF.get("live")), "time": MF.get("time"), "saved": MF.get("saved"), "week": MF.get("week"), "zone": MF.get("zone"),
                          "credit_zone": MF.get("credit_zone"), "credit_live": MF.get("credit_live"), "regime": MF.get("regime")})
    if MF and not mf_ok: hist_notes_fear.append("Market fear (VIX) reading missing or older than 8 days at the data date: not applied to the timing score.")
    tot_w = sum(v for v in w.values() if v)
    conf = sum(w[k] * groups[k]["coverage"] for k in w if w[k] and groups[k]["coverage"] >= MIN_COVERAGE) / tot_w if tot_w else 0
    tconf = sum(TIMING[k] * groups[k]["timing_coverage"] for k in TIMING if groups[k]["timing_coverage"] >= MIN_COVERAGE) / 100
    clab = lambda c: "high" if c >= .8 else "medium" if c >= .6 else "low"
    def vshare(mult, base, total):  # valuation's effective share of the score after the stress weighting
        return round(100 * base * mult / (total - base + base * mult)) if mult and total else None
    lt_tot = sum(v for v in w.values() if v)
    vw_lt = {"multiplier": round(vm_lt, 2), "share_pct": vshare(vm_lt, w.get("value", 0), lt_tot), "base_share_pct": round(100 * w.get("value", 0) / lt_tot)}
    vw_t = {"multiplier": round(vm_t, 2), "share_pct": vshare(vm_t, TIMING.get("value", 0), 100), "base_share_pct": TIMING.get("value", 0)}
    tbasis = ("Technicals 75% (trend and momentum: Liu & Tsyvinski 2021) + crypto cycle phase 25% (3-month view); market fear (VIX) is not applied to crypto" if is_crypto else
              "Technicals 85% (trend composite, reversal/overextension, volatility, relative strength), Valuation 15%; earnings news is scored once, in the third score" if not is_etf else
              ", ".join(f"{dict(GROUPS)[k]} {v_}%" for k, v_ in TIMING.items()) + " (trend and momentum of the market held, plus its valuation)")
    if vm_t > 1: tbasis += f"; valuation is weak ({vgt:.1f}), so its weight rises to about {vw_t['share_pct']}%"
    if fear and fear["applied"]: tbasis += f"; then market fear ({fear['phase_label'] or 'phase n/a'}, {fear['score']:.1f}/10, {fear['score_for_stock']:.1f} for this stock at beta {fear['beta_used']:.2f}) counts for {round(FEAR_W * 100)}%"
    lbasis = ("Cycle & on-chain 40% (cycle phase, MVRV), risk & return 20% (drawdown, Sharpe), technicals 40% (trend), × data coverage" if is_crypto else
              "All 8 groups, weighted by the " + lens + " lens × data coverage (fundamentals dominate)" if not is_etf else
              "All 6 groups × data coverage: the fund as a vehicle (cost & tracking 20%, size & liquidity 12%, diversification & structure 13%) and its market (valuation 25%, risk 10%, technicals 20%)")
    if vm_lt > 1: lbasis += f"; valuation is weak ({vg:.1f}), so its weight rises from {vw_lt['base_share_pct']}% to about {vw_lt['share_pct']}%"
    # scheduled earnings inside the timing window
    event = None
    ned = _d(MK.get("next_earnings_date")) if isinstance(MK.get("next_earnings_date"), str) else None
    if ned is None and isinstance((D.get("market") or {}).get("next_earnings_date"), str): ned = _d(D["market"]["next_earnings_date"])
    if ned:
        days = (ned - REF).days
        confd = bool((D.get("market") or {}).get("next_earnings_confirmed"))
        if 0 <= days <= EVENT_WINDOW:
            note = (f"Earnings due on {ned} ({'confirmed' if confd else 'estimated'}), in {days} days, inside the 2–12-week window: "
                    "the report can move the price sharply and override this score.")
            if vgt is not None and vgt < VAL_STRESS[0]:
                note += " With valuation this stretched, a disappointment usually costs more than a beat gains (Skinner & Sloan 2002)."
            event = {"date": str(ned), "days": days, "confirmed": confd, "in_window": True, "note": note}
        elif days > EVENT_WINDOW:
            event = {"date": str(ned), "days": days, "confirmed": confd, "in_window": False,
                     "note": f"Next earnings on {ned} ({'confirmed' if confd else 'estimated'}), after the 12-week window."}
    scores = {
        "long_term": {"name": "Long-term score", "score": score, "horizon": "1–3 years", "lens": lens,
                      "question": "Is this a well-built fund on a reasonably priced, healthy market?" if is_etf else "Is the crypto cycle and the coin's trend supportive for the next 1–3 years?" if is_crypto else "Is this a good business at a sensible price?",
                      "basis": lbasis, "valuation_weight": vw_lt, "data_confidence": clab(conf), "coverage": round(conf, 2), **(lt or {"tier": None, "label": "Not enough data", "meaning": ""})},
        "timing": {"name": "Entry-timing score", "score": tscore, "horizon": "2–12 weeks",
                   "question": "Are conditions good to start a position now?",
                   "basis": tbasis, "valuation_weight": vw_t, "event": event, "market_fear": fear, "direction": direction, "data_confidence": clab(tconf), "coverage": round(tconf, 2),
                   "parts": {k: groups[k]["timing_score"] for k in TIMING}, **(tier(tscore, TM_TIERS) or {"tier": None, "label": "Not enough data", "meaning": ""})}}
    # third score: entry timing adjusted for guidance evolution and news (catalyst.py, references/guidance.md)
    GB = None if nofund else guidance_block(D.get("guidance") or {}, REF, meta.get("currency"))
    NB = news_block(news_items, REF, is_etf=nofund, has_guidance=bool(GB and GB.get("score") is not None))
    scores["timing_plus"] = third_score(tscore, GB, NB, TM_TIERS, tier, is_etf=nofund, event=event,
                                        sue=None if nofund else V.get("surprise", {}).get("score"), rev=None if nofund else V.get("revision", {}).get("score"))
    if GB: scores["timing_plus"]["guidance_note"] = GB["note"]
    gv = lambda k: V[k]["v"]
    if is_etf and etf_out:
        num_ = sum(VEHICLE[k] * groups[k]["score"] for k in VEHICLE if groups[k]["score"] is not None and groups[k]["coverage"] >= MIN_COVERAGE)
        den_ = sum(VEHICLE[k] for k in VEHICLE if groups[k]["score"] is not None and groups[k]["coverage"] >= MIN_COVERAGE)
        etf_out["vehicle_score"] = round(num_ / den_, 1) if den_ else None
        etf_out["market_score"] = None
        mk_ = {k: w for k, w in LENS_ETF["etf"].items() if k not in VEHICLE}
        n2 = sum(mk_[k] * groups[k]["score"] for k in mk_ if groups[k]["score"] is not None and groups[k]["coverage"] >= MIN_COVERAGE)
        d2 = sum(mk_[k] for k in mk_ if groups[k]["score"] is not None and groups[k]["coverage"] >= MIN_COVERAGE)
        etf_out["market_score"] = round(n2 / d2, 1) if d2 else None
    gates = []
    ETF_GATES = (("TER ≤0.30%", "ter", lambda v: v <= .3), ("AUM ≥100 M", "aum", lambda v: v >= 100), ("Age ≥3 y", "age", lambda v: v >= 3),
                 ("Tracking diff. ≥ −0.5%", "td", lambda v: v >= -.5), ("P/E ≤ 10-y avg +1σ", "pedev", lambda v: v <= 1))
    STOCK_GATES = (("Rev CAGR 5y ≥10%", "revCagr5", lambda v: v >= 10), ("P/E <25", "pe", lambda v: 0 < v < 25),
                   ("FCF yield ≥3%", "fcfY", lambda v: v >= 3), ("ROE 5y >5%", "roe5", lambda v: v > 5), ("Net debt/EBITDA <3", "ndEbitda", lambda v: v < 3))
    CRYPTO_GATES = (("MVRV ≤ 1.5", "mvrv", lambda v: v <= 1.5), ("Above 200-day", "s200", lambda v: v > 0), ("Max DD 3y > −60%", "mdd", lambda v: v > -60),
                    ("12-1 momentum > 0", "mom", lambda v: v > 0))
    for lab, k, fn in (CRYPTO_GATES if is_crypto else ETF_GATES if is_etf else STOCK_GATES):
        v = gv(k)
        if k == "pe" and v is None and V[k]["s"] == "ok": gates.append({"label": lab, "pass": False})
        elif k == "ndEbitda" and v is None and V[k]["s"] == "ok": gates.append({"label": lab, "pass": V[k]["disp"] == "net cash"})
        else: gates.append({"label": lab, "pass": None if v is None else bool(fn(v))})

    # technical analysis rules (playbook T1-T7)
    R = {}
    if None not in (px, s50, s200):
        if px > s50 > s200 and (s20 is None or s20 > s50): R["regime"] = "Strong uptrend"
        elif px > s200: R["regime"] = "Uptrend, consolidating"
        elif px > s50: R["regime"] = "Recovery attempt"
        elif px < s50 < s200: R["regime"] = "Downtrend"
        else: R["regime"] = "Weak / below trend"
        R["structure"] = "SMA50 above SMA200 (bullish structure)" if s50 > s200 else "SMA50 below SMA200 (bearish structure)"
    else: R["regime"] = "insufficient data"
    rsi = T.get("rsi14")
    rs = None if rsi is None else "overbought" if rsi >= 70 else "bullish" if rsi >= 55 else "neutral" if rsi > 45 else "bearish" if rsi > 30 else "oversold"
    sig, mh = T.get("macd_signal"), T.get("macd_hist")
    if mh is not None and sig is None: ms_ = "bullish" if mh > 0 else "bearish"
    else: ms_ = None if mc is None else ("bullish" if (sig is None and mc > 0) or (sig is not None and mc > sig) else "bearish")
    if rs in ("overbought", "oversold"): mom = rs
    elif rs and ms_: mom = rs if rs == ms_ else "neutral"
    else: mom = rs or ms_ or "insufficient data"
    R["momentum"] = mom
    R["rsi_state"] = rs; R["macd_state"] = ms_ and (ms_ + (" (below zero)" if mc is not None and mc < 0 else ""))
    R["trend_strength"] = "ADX not available" if adx is None else ("no trend (range)" if adx < 20 else "emerging" if adx < 25 else "trending" if adx < 40 else "strong trend") + ("" if pdi is None or mdi is None else (", +DI leads" if pdi >= mdi else ", −DI leads"))
    va = T["vol_ann"]
    R["volatility"] = "insufficient data" if va is None else f"{'low' if va < 20 else 'normal' if va < 35 else 'high' if va < 60 else 'extreme'} ({va:.0f}% annualised)"
    lv = [(T.get(f"sma{n}"), f"SMA{n}") for n in (20, 50, 200)] + [(P.get("low_52w"), "52w low"), (P.get("high_52w"), "52w high")]
    lv = [(x, l) for x, l in lv if x]
    if px:
        below = sorted([x for x in lv if x[0] < px], key=lambda x: -x[0]); above = sorted([x for x in lv if x[0] > px], key=lambda x: x[0])
        mk = lambda x: {"level": round(x[0], 2), "pct": round((x[0] / px - 1) * 100, 1), "label": x[1]}
        R["support"] = mk(below[0]) if below else None; R["resistance"] = mk(above[0]) if above else None
    dd = V["hi52"]["v"]
    R["drawdown"] = None if dd is None else ("deep drawdown" if dd < -30 else "near highs" if dd > -5 else "moderate pullback")
    rg = R["regime"]
    bull = rg in ("Strong uptrend", "Uptrend, consolidating"); bear = rg in ("Downtrend", "Weak / below trend")
    if rg == "insufficient data": stance = "Insufficient data"
    elif bull and mom != "bearish":
        stance = "Bullish but stretched" if (rsi is not None and rsi >= 70) or (T.get("sma50_pct") or 0) > 15 or (V["ext50"]["v"] or 0) > 4 else "Bullish"
    elif bear and mom != "bullish": stance = "Bearish, oversold bounce possible" if rsi is not None and rsi <= 30 else "Bearish"
    elif rg == "Recovery attempt" and mom == "bullish": stance = "Early reversal"
    else: stance = "Neutral / range"
    if adx is not None and adx < 20 and stance in ("Bullish", "Bearish"): stance += ", weak trend strength"
    R["stance"] = stance
    fmt = lambda s: "n/a" if not s else f"{s['label']} {s['level']:,} ({s['pct']:+.1f}%)"
    R["stance_line"] = f"{stance}: {rg.lower()}, momentum {mom}, nearest support {fmt(R.get('support'))}, resistance {fmt(R.get('resistance'))}."
    flags = []
    chk = lambda k, c, msg: flags.append(msg) if gv(k) is not None and c(gv(k)) else None
    chk("beneish", lambda v: v > -1.78, "Beneish M above −1.78 (earnings-quality risk)")
    chk("altman", lambda v: v < 1.8, "Altman Z below 1.8 (distress zone)")
    chk("intCov", lambda v: v < 2, "Interest cover below 2×")
    chk("conv", lambda v: v < 50, "FCF covers less than half of net income")
    chk("payout", lambda v: v > 100, "Dividend payout above 100% of EPS")
    chk("ndEbitda", lambda v: v > 4, "Net debt above 4× EBITDA")
    if V["de"]["disp"] == "neg. equity": flags.append("Negative shareholders' equity")
    R["red_flags"] = flags
    MR = D.get("market_regime") or {}
    iv, ix = num(MR.get("index_vs_sma200_pct")), MR.get("sma50_above_sma200")
    nnh, p200 = num(MR.get("net_new_highs")), num(MR.get("pct_above_200d"))
    if iv is not None:
        weak = (nnh is not None and nnh < 0) or (p200 is not None and p200 < 50)
        strong = (nnh is not None and nnh > 0) or (p200 is not None and p200 > 60)
        if iv > 0 and ix is not False: lab = "Mixed" if weak else "Supportive"
        elif iv < 0 and ix is not True: lab = "Mixed" if strong else "Hostile"
        else: lab = "Mixed"
        txt = f"{MR.get('index', 'Index')} {(0.0 if abs(iv) < 0.05 else iv):+.1f}% vs its 200-day average" + ("" if ix is None else (", 50-day above 200-day" if ix else ", 50-day below 200-day"))
        if nnh is not None or p200 is not None:
            txt += "; breadth: " + ", ".join(x for x in ((f"net new highs {nnh:+.0f}" if nnh is not None else ""), (f"{p200:.0f}% of stocks above their 200-day" if p200 is not None else "")) if x)
            txt += " (weak)" if weak else " (healthy)" if strong else ""
        R["market_regime"] = {"label": lab, "text": txt, "index": MR.get("index")}
    else: R["market_regime"] = None
    # Minervini trend template: stocks only, context (references/methodology.md §5o)
    if not (is_etf or is_crypto):
        Tt = D.get("tech") or {}
        dd = [b for b in Tt.get("ohlc") or [] if _d(b.get("d")) and num(b.get("c"))]
        ww = [b for b in Tt.get("weekly") or [] if _d(b.get("d")) and num(b.get("c"))]
        bwk = [b for b in Tt.get("benchmark_weekly") or [] if _d(b.get("d")) and num(b.get("c"))]
        scores["timing"]["trend_template"] = trend_template(dd, ww, px, (V.get("rs") or {}).get("v"), MF.get("phase") if mf_ok else None, (R.get("market_regime") or {}).get("label"),
                                                            bwk, num(MF.get("vix_pct")) if mf_ok else None, MF.get("market") if mf_ok else None, meta.get("currency"), Tt.get("benchmark_weekly_name") or MR.get("index"))

    meta = dict(meta); meta["mode"] = f"historical, as of {REF}" if as_of else "live"
    meta["warnings"] = list(meta.get("warnings", [])) + hist_notes + hist_notes_fear
    # expectations check: what the price assumes vs how growth is trending (context, not scored)
    ig = V.get("impG", {}).get("v"); pe_v = V.get("pe", {}).get("v")
    rg = [(int(b["year"]), (b["rev"] / a["rev"] - 1) * 100) for a, b in zip(A, A[1:]) if a.get("rev") and b.get("rev")]
    decel = len(rg) >= 2 and rg[-1][1] < rg[-2][1]
    decel2 = len(rg) >= 3 and rg[-1][1] < rg[-2][1] < rg[-3][1]
    slow = bool(decel and pe_v is not None and pe_v > 35)
    rich = ig is not None and ig >= 5
    parts = []
    if ig is not None:
        parts.append(f"The price assumes free cash flow grows about {ig:.1f}% a year forever" + (", above long-run economic growth (about 4%)." if ig > 4 else "."))
    negf = (not is_fin) and V.get("impG", {}).get("disp", "").startswith("n/m")   # insurers/banks: n/m means "not meaningful", not negative FCF
    if negf:
        parts.append("Free cash flow is negative, so the price rests entirely on cash flows that are not visible yet."); rich = True
    if slow:
        parts.append(f"Revenue growth slowed from {rg[-2][1]:.1f}% to {rg[-1][1]:.1f}%" + (" for a second year" if decel2 else "") + f" while the P/E is {pe_v:.1f}×.")
    if slow or (rich and decel):
        parts.append("High expectations with slowing growth: a guidance miss is the typical trigger for a sharp drop.")
    expectations = {"implied_growth": None if ig is None else round(ig, 2), "revenue_growth": [{"year": y, "pct": round(g, 1)} for y, g in rg],
                    "decelerating": decel, "decelerating_2y": decel2, "slowdown_flag": slow, "rich_flag": rich,
                    "flag": slow or rich, "note": " ".join(parts) or None}
    if is_crypto:   # for a coin the 'expectations' line is where price stands against holders' average cost
        Cx = crypto_out or {}
        parts = []
        if Cx.get("mvrv") is not None: parts.append(f"Price is {Cx['mvrv']:.2f}× the average cost of all coins (realised price {Cx['realized_price']:,.0f} USD).")
        if Cx.get("phase_label"): parts.append(f"Cycle phase: {Cx['phase_label']}" + ("" if Cx.get("own_data") else " (Bitcoin's cycle)") + ".")
        flag = (Cx.get("mvrv") or 0) >= 3 or Cx.get("phase") == "distribution"
        if flag: parts.append("Holders sit on large profits: one-year returns from such levels have been poor since 2019.")
        expectations = {"implied_growth": None, "flag": flag, "note": " ".join(parts) or None}
    elif is_etf:   # for an ETF the 'expectations' line is the market's valuation against its own history
        dv, ip = V["pedev"]["v"], V["ipe"]["v"]; avg = num((D.get("etf") or {}).get("index_pe_avg10")); eg = V["eyg"]["v"]
        parts = []
        if ip is not None: parts.append(f"The index trades at {ip:.1f}× trailing earnings" + (f" vs a 10-year average of {avg:.1f}×" if avg else "") + (f" ({dv:+.1f}σ)" if dv is not None else "") + ".")
        elif dv is not None: parts.append(f"The index P/E is {dv:+.1f}σ from its 10-year average.")
        flag = dv is not None and dv >= 1.5
        if flag: parts.append("Markets this far above their own valuation history have tended to deliver lower returns over the following decade (CAPE evidence); over 1–3 years the link is weak, so read it as a risk, not a timing signal.")
        if eg is not None and eg < 1: parts.append(f"The earnings yield is barely above the 10-year bond yield ({eg:+.1f} pt): little extra reward for equity risk."); flag = True
        expectations = {"implied_growth": None, "pe_dev_sigma": dv, "earnings_yield_gap": eg, "flag": flag, "note": " ".join(parts) or None}
    # filing check: were the last reports filed on time? (context, not scored)
    filing_check = None
    FL = D.get("filings") or {}
    FL["items"] = [it for it in (FL.get("items") or []) if isinstance(it, dict) and it.get("period_end")]
    if FL["items"]:
        DL = {"10-Q": {"large_accelerated": 40, "accelerated": 40, "non_accelerated": 45},
              "10-K": {"large_accelerated": 60, "accelerated": 75, "non_accelerated": 90},
              "20-F": 120, "40-F": 120, "annual report": 120, "half-year report": 92}
        filer = FL.get("filer") or "large_accelerated"
        def deadline(it):
            if it.get("deadline"): return _d(it["deadline"])
            pe = _d(it.get("period_end")); f = str(it.get("form") or "").strip()
            if not pe: return None
            r = DL.get(f) if f in DL else DL.get(f.lower())
            if isinstance(r, dict): r = r.get(filer, r["large_accelerated"])
            if not r: return None
            d_ = pe + timedelta(days=r)
            return d_ + timedelta(days=(7 - d_.weekday()) % 7) if d_.weekday() >= 5 else d_   # weekend deadline → Monday   # quarterly reports in the EU and 6-Ks have no legal deadline
        rows, lags = [], []
        for it in sorted(FL["items"], key=lambda x: str(x.get("period_end") or "")):
            dl, fd, rd = deadline(it), _d(it.get("filed")), _d(it.get("report_date"))
            lag = (fd - rd).days if fd and rd else None
            if fd: fst = "late" if dl and fd > dl else "on time" if dl else "published"
            else: fst = ("late (not filed)" if dl and REF > dl else "pending")
            rows.append({**it, "deadline": str(dl) if dl else None, "status": fst, "days_after_results": lag,
                         "days_after_period": (fd - _d(it["period_end"])).days if fd and _d(it.get("period_end")) else None})
            if lag is not None: lags.append(lag)
        usual = sorted(lags)[len(lags) // 2] if lags else None
        last = rows[-1]
        if last["status"] == "pending" and usual is not None and _d(last.get("report_date")):
            waited = (REF - _d(last["report_date"])).days
            if waited > usual + 2: last["status"] = "pending (later than usual)"; last["waited_days"] = waited
        fflags = FL.get("flags") or []
        hard = [f for f in fflags if str(f.get("type", "")).lower() in ("nt 10-q", "nt 10-k", "nt 20-f", "restatement", "material weakness", "going concern", "late filing notice")]
        if hard or any(r["status"].startswith("late") for r in rows): lab = "Warning"
        elif fflags or last["status"] == "pending (later than usual)": lab = "Watch"
        else: lab = "OK"
        def short(r):
            core = f'{r.get("form") or "report"} {r.get("period") or r.get("period_end")}: {r["status"]}'
            if r.get("days_after_results") is not None: core += f' ({r["days_after_results"]} d after results)'
            elif r.get("waited_days"): core += f' ({r["waited_days"]} d since results; usually {usual})'
            if r["status"].startswith("pending") and r.get("deadline"): core += f', deadline {r["deadline"]}'
            return core
        note = f"Filing check {lab}: " + "; ".join(short(r) for r in rows[-3:]) + "."
        if fflags: note += " Flags: " + "; ".join(f'{f.get("type")} ({f.get("date", "")})' for f in fflags) + "."
        filing_check = {"label": lab, "basis": FL.get("basis"), "items": rows[-3:], "flags": fflags, "usual_days_after_results": usual, "note": note}
    res = {"meta": meta, "asset_type": "etf" if is_etf else "crypto" if is_crypto else "stock", "etf": etf_out, "crypto": crypto_out, "expectations": expectations, "filing_check": filing_check, "guidance_check": GB, "news_score": NB,
           "composites": {k: name for name, ks in COMPOSITES.items() for k in ks}, "context_why": (CONTEXT_WHY_CRYPTO | CONTEXT_WHY_ETF | {k: v for k, v in CONTEXT_WHY.items() if k in TECH_KEYS}) if is_crypto else (CONTEXT_WHY_ETF | {k: v for k, v in CONTEXT_WHY.items() if k in TECH_KEYS}) if is_etf else CONTEXT_WHY, "ownership": ownership_block(D.get("ownership"), REF),
           "etf_flows": flows_block((D.get("etf") or {}).get("flows"), REF, aum_now=num((D.get("etf") or {}).get("aum")), perf_6m=num(P.get("perf_6m")), perf_1y=num(P.get("perf_1y"))) if is_etf else None,
           "lens": lens, "bank_or_insurer": is_fin, "indicator_weights": {k: {"long_term": a, "timing": b} for k, (a, b) in W_.items()}, "cost_of_capital": {"rf": round(rf * 100, 2), "erp": round(erp * 100, 2), "ke": round(ke * 100, 2), "wacc": round(wacc * 100, 2)}, "score": score, "verdict": verdict, "scores": scores, "coverage": {"scored": ok, "missing": nf, "na": na, "total": len(REG)},
           "groups": groups, "gates": gates, "price": P, "market": {**MK, "market_cap": mcap}, "tech": T,
           "metrics": {m[0]: {**V[m[0]], "label": m[2], "group": m[1], "why": m[5]} for m in REG},
           "missing": [m[2] for m in REG if V[m[0]]["s"] == "nf"],
           "chart": [{"year": int(r["year"]), "rev": r.get("rev"), "ni": r.get("ni")} for r in A[-6:]],
           "analysis_rules": R,
           "ta_inputs": {V_k: {"label": next(m[2] for m in REG if m[0] == V_k), "value": V[V_k]["v"], "display": V[V_k]["disp"], "score": V[V_k]["score"], "note": V[V_k].get("src")}
                         for V_k in ("stack", "hi52", "mom", "rev1m", "rs", "rsi", "vol", "s200", "ext50", "rvol")},
           "ta_context": {V_k: {"label": next(m[2] for m in REG if m[0] == V_k), "value": V[V_k]["v"], "display": V[V_k]["disp"], "note": V[V_k].get("src")}
                          for V_k in ("macd", "adx", "boll")}}
    # run record (stored in the history artifact) and comparison with the previous run of the same stock
    KEYM = ("pe", "peFwd", "evEbitda", "fcfY", "impG", "roic", "op", "revCagr3", "ndEbitda", "rsi", "s200", "mom", "hi52", "rs", "surprise", "upside") if not is_etf else \
           ("ter", "td", "aum", "prem", "ipe", "ifpe", "pedev", "eyg", "idy", "mdd", "rsi", "s200", "mom", "hi52", "rs", "vol")
    if is_crypto: KEYM = ("mvrv", "mvrvP", "adg", "fund", "cfng", "mdd", "sharpe", "rsi", "s200", "mom", "hi52", "vol")
    rnd = lambda x, n=2: None if x is None else round(x, n)
    data_date = str(REF) if as_of else str(meta.get("as_of") or REF)
    record = {"ticker": meta.get("ticker"), "name": meta.get("name"), "asset_type": "etf" if is_etf else "crypto" if is_crypto else "stock", "cycle_phase": (crypto_out or {}).get("phase_label"), "cycle_days": ((crypto_out or {}).get("phase_age") or {}).get("days"), "as_of": data_date, "mode": "historical" if as_of else "live",
              "currency": meta.get("currency"), "price": rnd(P.get("last")), "lens": lens,
              "lt": {"score": scores["long_term"]["score"], "label": scores["long_term"]["label"], "tier": scores["long_term"].get("tier")},
              "tm": {"score": scores["timing"]["score"], "label": scores["timing"]["label"], "tier": scores["timing"].get("tier")},
              "tp": {"score": scores["timing_plus"]["score"], "label": scores["timing_plus"]["label"], "tier": scores["timing_plus"].get("tier"),
                     "catalyst": scores["timing_plus"].get("catalyst_score"), "guidance": scores["timing_plus"].get("guidance_score"), "news": scores["timing_plus"].get("news_score"),
                     "guidance_trend": (GB or {}).get("trend_label")},
              "own": (lambda O: None if not O else {"key": O.get("trend_key"), "trend": O.get("trend"),
                      "last": ((O["points"][-1]["segments"].get(O["trend_key"]) if O.get("points") and O.get("trend_key") else None)),
                      "buyers_pct": (O["breadth"][-1]["buyers_pct"] if O.get("breadth") else None)})(res.get("ownership")),
              "flows": (lambda Fl: None if not Fl else {"label": Fl.get("label"), "total_pct": Fl.get("total_pct"),
                        "aum": (Fl["points"][-1].get("aum") if Fl.get("points") else None), "units": (Fl["points"][-1].get("units") if Fl.get("points") else None)})(res.get("etf_flows")),
              "groups": {k: G["score"] for k, G in groups.items()},
              "metrics": {k: {"v": rnd(V[k]["v"], 3), "disp": V[k]["disp"]} for k in KEYM if k in V},
              "regime": (R.get("market_regime") or {}).get("label"), "stance": R.get("stance"),
              "fear": ((scores["timing"].get("market_fear") or {}).get("score")), "vix": ((scores["timing"].get("market_fear") or {}).get("vix")),
              "fear_phase": ((scores["timing"].get("market_fear") or {}).get("phase_label")), "direction": ((scores["timing"].get("direction") or {}).get("label")),
              "trend_template": (lambda T_: None if not T_ else {"version": 2, "passed": T_["passed"], "total": T_["total"], "met": T_["met"], "icon": T_["verdict_icon"], "verdict": T_["verdict"], "falling_200": T_["falling_200"], "missing": T_["missing"], "rs_proxy": T_["rs_proxy"], "stop_pct": (T_.get("stop") or {}).get("pct"), "stop_over_10": (T_.get("stop") or {}).get("over_10"),
                                   "full_passed": (T_.get("full") or {}).get("passed"), "full_total": (T_.get("full") or {}).get("total"), "entry_missing": (T_.get("full") or {}).get("entry_missing")})(scores["timing"].get("trend_template")),
              "event": (scores["timing"].get("event") or {}).get("date"),
              "implied_growth": expectations.get("implied_growth"), "scored": ok, "total": len(REG)}
    res["record"] = record
    tk = str(meta.get("ticker") or "").upper()
    older = [r for r in prev_runs if str(r.get("ticker", "")).upper() == tk and str(r.get("as_of", "")) < data_date]
    if older:
        pv = max(older, key=lambda r: (str(r.get("as_of")), str(r.get("run_at", ""))))
        def dlt(a_, b_): return None if a_ is None or b_ is None else round(a_ - b_, 2)
        ch = {"prev_as_of": pv.get("as_of"), "prev_mode": pv.get("mode"), "prev_url": pv.get("url"), "n_previous": len(older),
              "lt": {"from": (pv.get("lt") or {}).get("score"), "to": record["lt"]["score"], "delta": dlt(record["lt"]["score"], (pv.get("lt") or {}).get("score")),
                     "from_label": (pv.get("lt") or {}).get("label"), "to_label": record["lt"]["label"]},
              "tm": {"from": (pv.get("tm") or {}).get("score"), "to": record["tm"]["score"], "delta": dlt(record["tm"]["score"], (pv.get("tm") or {}).get("score")),
                     "from_label": (pv.get("tm") or {}).get("label"), "to_label": record["tm"]["label"]},
              "tp": {"from": (pv.get("tp") or {}).get("score"), "to": record["tp"]["score"], "delta": dlt(record["tp"]["score"], (pv.get("tp") or {}).get("score")),
                     "from_label": (pv.get("tp") or {}).get("label"), "to_label": record["tp"]["label"]},
              "price_pct": None if not pv.get("price") or not record["price"] else round((record["price"] / pv["price"] - 1) * 100, 1),
              "groups": sorted([{"group": groups[k]["name"], "from": pv.get("groups", {}).get(k), "to": record["groups"].get(k), "delta": dlt(record["groups"].get(k), pv.get("groups", {}).get(k))}
                                for k in record["groups"] if dlt(record["groups"].get(k), pv.get("groups", {}).get(k)) not in (None, 0)], key=lambda x: -abs(x["delta"])),
              "metrics": [{"key": k, "label": next(m[2] for m in REG if m[0] == k), "from": (pv.get("metrics", {}).get(k) or {}).get("disp"), "to": record["metrics"][k]["disp"]}
                          for k in KEYM if k in record["metrics"] and (pv.get("metrics", {}).get(k) or {}).get("disp") not in (None, "∅", record["metrics"][k]["disp"]) and record["metrics"][k]["disp"] != "∅"],
              "regime": None if pv.get("regime") == record["regime"] else {"from": pv.get("regime"), "to": record["regime"]}}
        try: ch["days"] = (date.fromisoformat(data_date[:10]) - date.fromisoformat(str(pv.get("as_of"))[:10])).days
        except Exception: ch["days"] = None
        res["compare"] = ch
    json.dump(res, open(out, "w"), indent=1, ensure_ascii=False)
    print(f"{meta.get('name')} ({meta.get('ticker')}) · {ok}/{len(REG)} scored")
    if res.get("compare"):
        c_ = res["compare"]; print(f"  since {c_['prev_as_of']} ({c_['prev_mode']}): long-term {c_['lt']['from']} → {c_['lt']['to']}, timing {c_['tm']['from']} → {c_['tm']['to']}, price {c_['price_pct']}%")
    for sk in scores.values():
        vw = sk.get("valuation_weight") or {}
        print(f"  {sk['name']} ({sk['horizon']}): {sk['score']} · {sk['label']}" + (f"  [valuation weight ×{vw['multiplier']} → {vw['share_pct']}%]" if vw.get("multiplier", 1) > 1 else ""))
    ev = scores["timing"].get("event")
    if ev: print("  event:", ev["note"])
    if expectations.get("note"): print("  expectations:", ("⚠ " if expectations["flag"] else "") + expectations["note"])
    if filing_check: print("  filings:", filing_check["note"])
    if GB: print("  guidance:", GB["note"], f"→ guidance score {GB['score']}")
    if NB: print(f"  news score {NB['score']} (net {NB['net_sentiment']}, {NB['n_items']} items, weight {NB['effective_weight']})")
    for n_ in scores["timing_plus"].get("notes", []): print("  note:", n_)
    if res.get("ownership") and res["ownership"].get("note"): print("  ownership:", res["ownership"]["note"])
    if res.get("etf_flows"):
        Fl = res["etf_flows"]; print("  flows:", Fl.get("note"), " ".join(Fl.get("notes", [])), " ".join(Fl.get("warnings", [])))
    if etf_out:
        print(f"  ETF check {etf_out['check']['label']}: " + " ".join(etf_out["check"]["warnings"] + etf_out["check"]["notes"]))
        print(f"  vehicle score {etf_out.get('vehicle_score')} · market score {etf_out.get('market_score')}")
        for x in etf_out["peers"]: print(f"    {'*' if x.get('selected') else ' '} {x.get('name')} TER {x.get('ter_pct')} AUM {x.get('aum')} TD {x.get('td_avg_pct')} → {x['vehicle_score']}")
    for k, gname in GROUPS: print(f"  {gname:<20} {groups[k]['score'] if groups[k]['score'] is not None else '∅':>5}  ({groups[k]['n']}/{groups[k]['total']})")
    print("  gates:", ", ".join(f"{g['label']} {'✓' if g['pass'] else '✗' if g['pass'] is False else '∅'}" for g in gates))
    print("  technical:", R["stance_line"])
    if flags: print("  red flags:", "; ".join(flags))

if __name__ == "__main__":
    main()
