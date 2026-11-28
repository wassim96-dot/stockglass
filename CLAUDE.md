# StockGlass

Static GitHub Pages site (no build step) plus GitHub Actions jobs that save market data to `data/`. Companion of the
`stock-verdict` skill: the same scoring rules run in the browser here and in Python there.

## Owner rules
- Never commit to `main`: branch, push, open a PR (`gh api repos/wassim96-dot/stockglass/pulls ...`); the owner merges.
  If a PR was already merged, start a new branch from `origin/main` and cherry-pick.
- Phone alerts only (GitHub issues opened by the jobs → mobile app). No e-mail notifications.
- Labels never turn into buy/sell advice; pages end with "rule-based screen, not investment advice".

## Commands
```bash
node tests/run.mjs                     # offline tests, ~5 s: syntax, data files, glossary keys, replays, Minervini block, copies (CI on PRs)
node tests/run.mjs --skill ../stock-verdict   # also the skill's copies (regime.py, glossary, gloss.js, render.py, weights)
node tests/check-copies.mjs [--skill DIR]     # only the copy check, with the first differing input per function
# serve and test the pages offline (outside requests aborted; mock Yahoo answers to test the live path)
python3 -m http.server 8765            # then open http://localhost:8765/index.html (or today.html)
node scripts/market-fear.mjs           # VIX phase/score + credit check → data/market.json, market-history.json
node scripts/market-regime.mjs         # rates + inflation → data/regime.json (context only)
node scripts/crypto-data.mjs           # Coin Metrics / OKX / alternative.me → data/crypto.json, crypto-history.json
node scripts/daily-minervini.mjs       # daily light Minervini check → data/daily/
python3 scripts/weekly_review.py --out /tmp/review   # weekly review page (needs data/runs)
gh workflow run market-fear.yml --ref <branch>       # test a job on a branch (it commits data to that branch)
```
Jobs (cron in UTC; GitHub starts them 6–10 hours late, so each has backups and a once-per-period guard):
`market-fear.yml` (weekdays after the US close, then regime step), `crypto-data.yml` (daily), `daily-minervini.yml`
(starts when market-fear finishes, via `workflow_run`, plus one backup cron), `weekly-watchlist.yml` (Friday/Saturday), `cleanup-branches.yml` (manual or monthly: deletes branches fully merged into main;
Claude Code sessions cannot delete branches or change repo settings).
Phase alerts go through `scripts/send-alerts.sh` (5 retries; never blocks the save; a new alert closes the older open
issue of the same kind, the title up to the first ":"; "Job failed" issues are closed by hand). A failed or timed-out job opens one
issue per job per day (`scripts/job-failed.sh`, last step `if: failure()`; script steps have their own `timeout-minutes`
so that step still runs). A push that fails 3 times fails the step. Optional secret `FRED_API_KEY` (free) → FRED's API.

## Architecture
- `index.html`: the whole app (single file): fetch quotes, compute indicators and the two scores (long-term; short-term setup =
  0.5 × Minervini full check + 0.5 × technicals, `setupScore`; fear, valuation and EPS surprise are context since 28 Nov 2026),
  context windows (Next earnings; Expectations, sales & filings = reverse DCF + `fwdSecs()` analysts/contracted sales/guidance + filing check), one "Market backdrop" card (`renderRegime`: Fear, Credit, Trend, Rates,
  Inflation, every reading once), BTC Cycle, the indicator groups plus the Minervini card (`minerviniCard`, one tappable row per
  check, glossary keys `tt_*`), and "Sources & method" at the end of the left column (all source/method notes live there). `today.html`: daily Minervini page. `history.html`: watchlist history.
- `regime.js`: shared module for both pages: `liveFear` (today's quotes on the saved history, same rules as
  market-fear.mjs), `fearAt`, `fearZone`/`creditZone` (history phrases), `creditLive`, `ratesRead`, `inflationRead`, `btcCycle`, `glossInit`.
- `scripts/lib/net.mjs`: all job network code: `fetchText` (timeout covers the body), `Routes` (direct + relays, a route
  failing 4× is dropped for the run, the working one moves first), `yahooChart`, `fred` (API key or CSV via relays; after
  one series fails on every route the rest are skipped for the run). New fetches in scripts go through it.
- Time tags: every reading shows when it was measured (grey "🕒" after the line title): `tsTag`, `tClose`, `tLive`,
  `tComp`, `fearWhen`, `credWhen` in index.html; `lineHTML` and context-window sections take the tag as an extra item.
  A new reading on a page → give it a tag (saved: the close/date it describes + "computed" time; live: the quote time).
- Cards fold to their title (`foldInit`, 44 px chevron button top right; the title keeps opening the glossary). Open by default (28 Nov 2026;
  `folded:[...]` lists exceptions); the viewer's choices are kept per card title (storage ns `sg2`/`today2`, skill `sv2`). A new
  card with an `h3` title gets the arrow automatically; "Fold all / Expand all" is any element with `data-fold-all`.
- Layout v2 type scale (same in the skill's render.py): 12.5 px tags · 13 notes · 15 body and rows · 17 card titles; nothing under
  12.5 px; one status chip per header, the horizon as `.hzl` under the title; grey text ≥ 5:1 contrast. Every new row or line needs a
  glossary entry (tap-to-explain): `.m[data-k]` rows use the key, `h4`/titles match the `a` aliases.
- `data/glossary.json`: tap-to-explain texts. `data/regime.json`: rates/inflation. `data/market*.json`: fear + credit.

## Rules copied in several places: change all copies together
| Logic | Copies |
|---|---|
| `creditRead` (credit window) | `index.html`, `today.html`, `scripts/weekly_review.py` (`credit_read`), skill `scripts/render.py` |
| fear / zones / rates / inflation / BTC cycle | `regime.js` ↔ `scripts/regime.py` (copy of skill `scripts/regime.py`) |
| glossary | `data/glossary.json` = skill `assets/glossary.json`; popover code `regime.js glossInit` = skill `assets/gloss.js` |
| folding cards | `regime.js foldInit` = skill `assets/fold.js` (cards start open, arrow top right, state in localStorage) |
| weights (`WI_S`, `LW_S`), scoring bands | `index.html` ↔ skill `scripts/score.py` (`WI`, `LENS`) |
| short-term setup score (`setupScore`, `SETUP_W`, labels `TM_T_S`/`TM_T_F`) | `index.html` ↔ skill `scripts/score.py` (`setup_score`, `TM_TIERS`/`TM_TIERS_ETF`; rounding = JS `Math.round`) |
| Minervini v2 | `index.html` between `/* @tt-begin` and `/* @tt-end */`; reused by `daily-minervini.mjs` |

`tests/check-copies.mjs` runs every copy on the same inputs (saved data + values on both sides of each threshold) and must
show no difference; `tests/run.mjs` also replays the nightly job (`build()` on the saved history: every phase and bear
state since 2009) and the live page (`liveFear` on the last 60 days). Two differences are by design and documented in the
checker: `WI_S.surprise` keeps a timing weight the skill moves to its third score (unused since 28 Nov 2026: the mkt group is not in `TIMING_S`); the page
names the 200-day indicator `e200`, the skill `s200`. A new rule copy → add its inputs to `fixtures()`.

## Gotchas
- Backtests (branch `backtest-timing`, draft PR #59, never merge): no score predicted 2–12 week returns in 2012–2026; the setup
  score is shown as trend quality (smaller dips), never as a forecast. Minervini's full check also differs slightly by data: the
  page uses daily bars for the RS line and the sector ETF, the skill weekly bars.
- Yahoo refuses GitHub's servers and browsers' CORS: always go through the relays (`race`/`yCh` in index.html; jina,
  allorigins, codetabs, corsproxy in the scripts).
- FRED (credit spreads, CCC) often times out or refuses from GitHub (jina 401, codetabs 522, allorigins 403/500): one
  pass per run through `lib/net.mjs`, last good value kept up to 5 days (`stale: true`). Rates come from home.treasury.gov CSV; inflation from the BLS API, then
  DBnomics (BEA PCE), FRED last. The FRED ICE series now only keep 3 years.
- Oct 2025 CPI was never collected: year-on-year values can be `null`; code must show "not published", not 0.
- History rows store the dividend-adjusted HYG/IEF ratio; live code uses the raw price ratio (fine for today's row).
- Jobs commit `data/*`: before a PR, merge `origin/main` into the branch to avoid data conflicts. Each job commits only
  its own files (weekly: `data/runs`, `data/latest.json`). A source that fails keeps its previous data (crypto history,
  funding, fear & greed; spreads ≤ 5 days): never write a file that lost data the page needs.
- Scheduled jobs never save an unfinished US session: `lastUsClose()` (lib/net.mjs; 16:15 New York) cuts later bars in
  market-fear and daily-minervini. A manual market-fear run (`MANUAL_RUN=1` from workflow_dispatch) keeps the live session
  on purpose and marks it `intraday` (the pages say "intraday hh:mm (manual run)", never "close").
- Credit spreads (FRED, end of day, 1–2 days late) are estimated live: `creditLive` (regime.js) = `credit_live` (regime.py)
  moves FRED's last value by HYG / LQD vs IEF since that date (needs `credit_check.fund_closes`, saved by market-fear).
- Never clear a fetch timeout before reading the body (`clearTimeout` then `await r.text()` hung the daily job for 30 min).
- The page only uses the CDN/relay hosts it already uses; no new external hosts without checking CSP/CORS.
- JS `toFixed` and Python `format` round an exact half differently (-0.125 → -0.13 vs -0.12); real data almost never
  hits it, test inputs must avoid it.
