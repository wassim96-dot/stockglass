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
# serve and test the pages offline (outside requests aborted; mock Yahoo answers to test the live path)
python3 -m http.server 8765            # then open http://localhost:8765/index.html (or today.html)
node scripts/market-fear.mjs           # VIX phase/score + credit check → data/market.json, market-history.json
node scripts/market-regime.mjs         # rates + inflation → data/regime.json (context only)
node scripts/crypto-data.mjs           # Coin Metrics / OKX / alternative.me → data/crypto.json, crypto-history.json
node scripts/daily-minervini.mjs       # daily light Minervini check → data/daily/
python3 scripts/weekly_review.py --out /tmp/review   # weekly review page (needs data/runs)
gh workflow run market-fear.yml --ref <branch>       # test a job on a branch (it commits data to that branch)
```
Jobs (cron in UTC, GitHub often starts them hours late, so each has backups and a once-per-period guard):
`market-fear.yml` (weekdays after the US close, then regime step), `crypto-data.yml` (daily), `daily-minervini.yml`,
`weekly-watchlist.yml` (Friday/Saturday). Alerts go through `scripts/send-alerts.sh` (5 retries; never blocks the save).

## Architecture
- `index.html`: the whole app (single file): fetch quotes, compute indicators and the three scores, context windows,
  Market Regime and BTC Cycle cards. `today.html`: daily Minervini page. `history.html`: watchlist history.
- `regime.js`: shared module for both pages: `liveFear` (today's quotes on the saved history, same rules as
  market-fear.mjs), `fearAt`, `fearZone`/`creditZone` (history phrases), `ratesRead`, `inflationRead`, `btcCycle`, `glossInit`.
- `data/glossary.json`: tap-to-explain texts. `data/regime.json`: rates/inflation. `data/market*.json`: fear + credit.

## Rules copied in several places: change all copies together
| Logic | Copies |
|---|---|
| `creditRead` (credit window) | `index.html`, `today.html`, `scripts/weekly_review.py` (`credit_read`), skill `scripts/render.py` |
| fear / zones / rates / inflation / BTC cycle | `regime.js` ↔ `scripts/regime.py` (copy of skill `scripts/regime.py`) |
| glossary | `data/glossary.json` = skill `assets/glossary.json`; popover code `regime.js glossInit` = skill `assets/gloss.js` |
| weights (`WI_S`, `LW_S`), scoring bands | `index.html` ↔ skill `scripts/score.py` (`WI`, `LENS`) |
| Minervini v2 | `index.html` between `/* @tt-begin` and `/* @tt-end */`; reused by `daily-minervini.mjs` |
Verify a port by replay: feed saved history rows through the live code and compare phases (60/60 must match).

## Gotchas
- Yahoo refuses GitHub's servers and browsers' CORS: always go through the relays (`race`/`yCh` in index.html; jina,
  allorigins, codetabs, corsproxy in the scripts).
- FRED (credit spreads, CCC) often times out or refuses from GitHub: fetched one at a time through relays, last good
  value kept up to 5 days (`stale: true`). Rates come from home.treasury.gov CSV; inflation from the BLS API, then
  DBnomics (BEA PCE), FRED last. The FRED ICE series now only keep 3 years.
- Oct 2025 CPI was never collected: year-on-year values can be `null`; code must show "not published", not 0.
- History rows store the dividend-adjusted HYG/IEF ratio; live code uses the raw price ratio (fine for today's row).
- Jobs commit `data/*`: before a PR, merge `origin/main` into the branch to avoid data conflicts.
- The page only uses the CDN/relay hosts it already uses; no new external hosts without checking CSP/CORS.
