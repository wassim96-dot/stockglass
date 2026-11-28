# StockGlass

A free, rule-based stock screen that runs in your browser. Type a ticker and StockGlass scores the stock on public data:

- **Long-term score (1–3 years):** is this a good business at a sensible price? It covers growth, profitability, financial health, valuation, quality, dividend, technicals and market data.
- **Short-term setup score (2–12 weeks):** half Mark Minervini's full check (trend template plus entry points), half technicals. It describes the trend; in our 2012–2026 backtest it did not predict returns.
- **Market backdrop:** fear (VIX phase, variance risk premium), credit spreads, index trend, interest rates and inflation. This is context only and never part of a score.

Every title, row and line can be tapped for a plain explanation of the measure and its levels.

Rule-based screen on public data, not investment advice.

## Pages

| Page | What it shows |
|---|---|
| `index.html` | The full screen for one stock, ETF, index or coin (`index.html?s=MSFT`). |
| `today.html` | The daily Minervini check of the watchlist (`watchlist.txt`): who meets the template and what changed. |
| `history.html` | Past weekly watchlist runs and how the scores moved. |

The site is static (GitHub Pages, no build step). Quotes come from Yahoo Finance through public relays; statements from SEC EDGAR; credit spreads from FRED (ICE BofA); rates from the US Treasury; inflation from BLS and BEA.

## Scheduled jobs (GitHub Actions)

| Job | When (Paris time, GitHub often starts late) | What it saves |
|---|---|---|
| Market fear | weekdays after the US close, with backups | `data/market.json`, `data/market-history.json`, then `data/regime.json` (rates, inflation) |
| Daily Minervini | when Market fear finishes, plus one backup | `data/daily/` |
| Crypto data | daily | `data/crypto.json`, `data/crypto-history.json` |
| Weekly watchlist | Friday after the close, Saturday backup | `data/runs/`, `data/latest.json` |

Alerts reach the phone as GitHub issues (no e-mail): a fear-phase change, a stock that starts or stops meeting the Minervini template, or a job that failed. A new alert closes the previous open one of the same kind. Any job can also be started by hand from the Actions tab ("Run workflow").

## Working on it

```bash
node tests/run.mjs                          # offline tests, about 5 s (also run on every pull request)
node tests/run.mjs --skill ../stock-verdict # also checks the copies shared with the stock-verdict skill
python3 -m http.server 8765                 # then open http://localhost:8765/index.html?s=MSFT
```

Changes go through a branch and a pull request; `main` is merged by the owner. The scoring rules are shared with the `stock-verdict` skill and must stay identical: see [CLAUDE.md](CLAUDE.md) for the architecture, the list of shared copies and the known pitfalls.
