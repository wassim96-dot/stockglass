# Pre-registration 2: a Minervini "setup" score to replace the entry-timing score (written 2026-11-28, before any result)

Why: the first test (HYPOTHESES.md) found no edge for the current timing score (mean IC −0.006 at 8 weeks, Holm p = 1.00)
and showed it is 84% the same ranking as 12-1 momentum. This test asks whether Minervini's full price/volume method
(trend template + relative strength + volatility contraction + volume dry-up + no chasing), plus the two academic
trend measures closest to it, ranks stocks better, and whether his market-direction rule and template cut losses.

Same universe, dates, prices and forward returns as test 1 (backtest/results.csv rows; prices from the run-46127374399
cache). Point in time: every feature uses daily bars up to the month-end only. Prices only: Minervini's fundamentals
(Code 33: three quarters of accelerating EPS, sales and margins) need point-in-time quarterly data we do not have; they
are not tested and stay in the third score (earnings news), not in this one.

## Components (each mapped to 0–10 with a fixed scale, so the live skill can score one stock without a universe)
| id | measure | 10 at | 0 at | source |
|---|---|---|---|---|
| tt | trend template blocks met (skill's version 2: MA stack, rising 200-day, ≥25% above 52-week low, within 25% of high, RS ahead of SPY) | 5/5 | 0/5 | Minervini 2013, 2017 |
| rs | IBD-weighted return (40% 3 m, 20% each 6/9/12 m) minus SPY's, points | ≥ +30 | ≤ −30 | Minervini rule 8 (IBD RS) |
| mad | 21-day / 200-day average − 1, % | ≥ +15 | ≤ −15 | Avramov, Kaplanski & Subrahmanyam 2021 |
| hi52 | close / 52-week high (daily highs) | ≥ 0.98 | ≤ 0.70 | George & Hwang 2004 |
| tight | st. dev. of daily returns, last 10 days / last 63 days | ≤ 0.5 | ≥ 1.5 | Minervini VCP (contracting volatility) |
| dry | average volume, last 10 days / last 50 days | ≤ 0.6 | ≥ 1.4 | Minervini VCP volume dry-up; Lee & Swaminathan 2000 |
| ext | close / 50-day average − 1, % (penalty only: 10 up to +8%) | ≤ +8 | ≥ +25 | Minervini "don't chase extended stocks" |
Linear between the two ends.

## Two composites (equal weights of the 0–10 components available)
- **prior**: all seven components (Minervini's method as written, no data mining).
- **selected**: only components whose design-period (2012-01 to 2018-12) 8-week IC of the raw measure, in the
  hypothesised direction, has Newey–West t ≥ 1.0. Chosen once on the design period; the holdout is never used for it.

## Primary tests (holdout 2019-01 to the last month with 60 forward days; Holm over 3; two-sided)
- P1: selected composite, 8-week monthly Spearman IC > 0 (NW t, lag 2).
- P2: selected composite IC minus the current timing score's IC, paired by month, > 0.
- P3: prior composite, 8-week IC > 0.

## Secondary (reported, not confirmation)
- S1 every component and composite: IC at 4/8/12 weeks, design vs holdout, quintile spreads (block bootstrap).
- S2 overlap: Spearman of each composite with 12-1 momentum and with the current timing score.
- S3 market direction (Minervini buys only in a confirmed uptrend): SPY > 50-day > 200-day and 200-day rising
  over 21 days. Mean absolute 8-week return of all stocks and of the top quintile of the selected composite,
  gate on vs off, difference with NW t (monthly series).
- S4 risk (his main claim): template 5/5 vs not, mean 8-week maximum adverse excursion (worst close vs entry
  within 40 days), and share of 8-week losses worse than −10%, difference with NW t.
- S5 VCP setup (all of: tt = 5/5, tight ≤ 0.8, dry ≤ 0.9, within 10% of the 52-week high, ext ≤ 10%): mean 8-week
  excess return and hit rate vs other template-5/5 stocks.

## Decision rule (stated now)
- P1 and P2 pass after Holm → propose replacing the timing score with the selected composite.
- Otherwise no claim of predictive edge: the user chooses between keeping the current score or a Minervini setup
  score shown as a rule-based checklist (labelled "not shown to predict returns in our test"), and S3/S4 decide
  whether the market gate and template are kept as risk filters.

Limitations: 98 large US survivors, 2012–2026 (a period when momentum earned little in large caps); ~98 stocks per
month gives an IC standard error near 0.02; no costs; daily closes (no intraday pivots or breakout-day volume).
