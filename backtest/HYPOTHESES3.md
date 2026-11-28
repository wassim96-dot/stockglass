# Pre-registration 3: our full Minervini check + our short-term technicals, without fear and valuation (2026-11-28, before any result)

Asked by the owner after test 2: test the Minervini score StockGlass actually shows (the "full check": 5 template blocks +
6 entry points, index.html trendTemplate(), version of 24 Nov 2026), together with the short-term technical indicators
the timing score already uses, with market fear and valuation removed (they become context).

Same universe, month-ends, prices and forward excess returns as tests 1–2. Point in time throughout.

## Measures
- **M (full Minervini check, 0–10)** = 10 × points passed / points available, ported line by line from index.html:
  template blocks (price > 50 > 150 > 200-day; 200-day rising over 21 days; ≥ 25% above the 52-week low; within 25% of
  the 52-week high; IBD-weighted return ≥ SPY's) + entry points (RS line at a 52-week high, ±0.1%; price above the 50-day
  and ≤ 4 ATR(20) above it; largest one-day gain in 21 days < 10%; volume support: an up day in the last 5 with volume
  ≥ 1.4× the 50-day average, or 10-day / 50-day volume < 0.75; median 50-day turnover ≥ €1 M; sector ETF's IBD-weighted
  return ≥ SPY's — XLRE from 2016, XLC from 2019, skipped before, as the page skips a missing benchmark).
- **T (our short-term technicals, 0–10)** = the timing score's technical part from test 1 (tech_part: RSI, Bollinger,
  200-day, MA stack, 12-1 momentum, volatility, 52-week high, 1-month reversal, extension, relative strength; skill
  weights), i.e. the timing score with valuation and market fear removed.
- **C (candidate new short-term score)** = 0.5 × M + 0.5 × T, fixed now.
- **Cw** = w × M + (1 − w) × T with w ∈ {0, .25, .5, .75, 1} picked by the best 8-week IC on 2012–2018 only.

## Primary tests (holdout 2019-01 → last month with 60 forward days, 8 weeks, Holm over 3, two-sided)
- P1: C monthly Spearman IC > 0 (Newey–West t, lag 2).
- P2: C IC minus the current timing score's IC (with fear; test 1 `score`), paired by month, > 0.
- P3: M IC > 0.

## Secondary (reported, not confirmation)
- 4 and 12 weeks; design period; Cw; quintile spreads (block bootstrap).
- Bands of C (≥ 7, 5.5–7, 4–5.5, < 4): mean 8-week excess return, hit rate, maximum adverse excursion.
- Each of the 11 points: mean 8-week excess return when passed minus when failed (monthly paired, NW t).
- Overlap of M, T, C with 12-1 momentum and with the current score.

## Decision rule
P1 and P2 pass after Holm → C replaces the timing score with a predictive claim. Otherwise the owner chooses the score
on design grounds, with the page saying it was not shown to predict 2–12 week returns in this test.
