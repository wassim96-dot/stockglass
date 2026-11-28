#!/usr/bin/env python3
"""Universe for the timing backtest: 100 US stocks listed since 2010 or earlier, drawn at random within GICS sectors.

Candidate lists: large and mid-size US companies with a continuous listing under the same ticker since 2010 or earlier
(so Yahoo has their full history). They are today's survivors: companies acquired or bankrupt since 2012 are not in
them (survivorship bias, stated in the report). Seed 20261128; 10 from Information Technology, 9 from each other sector.
Writes backtest/universe.json.
"""
import json, os, random
SEED = 20261128
POOLS = {
 "Information Technology": "AAPL MSFT ORCL CSCO INTC IBM TXN QCOM ADBE ADI AMAT KLAC MU NVDA ACN ADSK CTSH HPQ AKAM INTU".split(),
 "Health Care": "JNJ PFE MRK ABT AMGN GILD BMY LLY UNH MDT SYK BDX BSX CVS CI HUM TMO DHR BIIB REGN".split(),
 "Financials": "JPM BAC WFC C GS MS AXP USB PNC BK SCHW TRV ALL MET PRU AIG CB MMC AON BLK".split(),
 "Consumer Discretionary": "AMZN HD MCD NKE SBUX LOW TJX F BKNG ROST YUM MAR EBAY ORLY AZO DHI LEN HAS".split(),
 "Consumer Staples": "PG KO PEP WMT COST MO PM CL KMB GIS SYY KR HSY CLX MKC CPB ADM TSN CAG HRL".split(),
 "Industrials": "GE HON MMM CAT DE UPS FDX LMT RTX BA UNP CSX NSC EMR ETN ITW GD NOC WM PH".split(),
 "Energy": "XOM CVX COP EOG SLB OXY VLO HAL DVN APA WMB OKE EQT CTRA NOV MUR".split(),
 "Materials": "APD SHW ECL NEM FCX NUE VMC MLM PPG IP BALL AVY ALB CF MOS EMN IFF".split(),
 "Utilities": "NEE DUK SO D AEP EXC SRE XEL ED PEG WEC ES PCG EIX DTE AEE ETR PPL".split(),
 "Real Estate": "PLD AMT SPG PSA EQIX O WELL AVB EQR VTR BXP DLR ESS MAA ARE".split(),
 "Communication Services": "GOOGL VZ T CMCSA DIS NFLX CHTR TMUS EA TTWO OMC IPG LUMN".split(),
}
rng = random.Random(SEED); out = []
for sector, pool in POOLS.items():
    k = 10 if sector == "Information Technology" else 9
    out += [{"ticker": t, "sector": sector} for t in sorted(rng.sample(pool, k))]
json.dump({"seed": SEED, "n": len(out), "stocks": out}, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "universe.json"), "w"), indent=1)
print(f"seed {SEED}: {len(out)} stocks")
for s in POOLS: print(f"  {s}: " + " ".join(x["ticker"] for x in out if x["sector"] == s))
