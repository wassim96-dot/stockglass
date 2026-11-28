# Pre-registration: entry-timing score backtest (written 2026-11-28, before any result was computed)

Score tested: the stock-verdict entry-timing score computed from prices and market fear only (skill scripts copied
unchanged in backtest/sv/, commit of 28 Nov 2026). Valuation (15% of the live score) needs point-in-time
fundamentals and is left out: the technical group carries the full pre-fear weight, then market fear 10% with its
beta scaling, exactly as score.py does. No weight or threshold is changed in this test.

Universe: 100 US stocks listed since 2010 or earlier, ~9 per GICS sector (10 in Information Technology), drawn at
random from per-sector candidate lists with seed 20261128 (backtest/universe.py). Survivors only (see limitations).
Dates: last trading day of each month, 2012-01 to the last month with 60 trading days of forward prices.
Point in time: each score uses prices and the market-fear history up to its date only.
Returns: total return (dividend-adjusted closes); excess = stock minus SPY over the same window.
Horizons: 4, 8, 12 weeks = 20, 40, 60 trading days.

H1: a higher timing score → higher excess return over the next 4, 8 and 12 weeks.
    Test: monthly Spearman IC (score vs forward excess return); mean IC, Newey–West t (lags = horizon in months),
    share of months > 0, IC IR; quintile spread (top − bottom) with block-bootstrap 95% CI.
H2: the labels are ordered: Favourable > Mostly favourable > Neutral > Unfavourable > Poor.
    Test: mean excess return and hit rate per label; best-minus-worst label spread, Newey–West t; Spearman between
    label rank and mean return.
H3: the score adds information beyond 12-1 month momentum.
    Test: monthly Fama–MacBeth regressions of forward excess return on standardized score, 12-1 momentum and beta;
    the score coefficient's Newey–West t.
H4: the market-fear part helps.
    Test: IC of the final score minus IC of the score before the fear blend (paired by month), Newey–West t.

Primary tests (Holm-corrected together): H1 at 4/8/12 weeks (3), H2 spread at 8 weeks (1), H3 at 8 weeks (1),
H4 at 8 weeks (1) = 6 tests. Everything else (other horizons for H2–H4, sub-periods 2012–2018 vs 2019–latest, fear
phases, sector-neutral version) is reported as robustness, not as confirmation.
