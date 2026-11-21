// TEMP probe: which free crypto data sources answer from GitHub Actions
const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/128.0 Safari/537.36";
const T = [
 ["coinmetrics-community", "https://community-api.coinmetrics.io/v4/timeseries/asset-metrics?assets=btc,eth&metrics=PriceUSD,CapMrktCurUSD,CapMVRVCur,AdrActCnt,TxCnt,HashRate,SplyCur&frequency=1d&page_size=5&paging_from=end"],
 ["coinmetrics-catalog-btc", "https://community-api.coinmetrics.io/v4/catalog-v2/asset-metrics?assets=btc&page_size=1"],
 ["alternative-fng", "https://api.alternative.me/fng/?limit=3"],
 ["binance-funding", "https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=3"],
 ["okx-funding", "https://www.okx.com/api/v5/public/funding-rate-history?instId=BTC-USDT-SWAP&limit=3"],
 ["bybit-funding", "https://api.bybit.com/v5/market/funding/history?category=linear&symbol=BTCUSDT&limit=3"],
 ["deribit-funding", "https://www.deribit.com/api/v2/public/get_funding_rate_value?instrument_name=BTC-PERPETUAL&start_timestamp=1763000000000&end_timestamp=1763600000000"],
 ["coingecko-btc", "https://api.coingecko.com/api/v3/coins/bitcoin?localization=false&tickers=false&community_data=false&developer_data=false"],
 ["blockchain-info-mvrv", "https://api.blockchain.info/charts/mvrv?timespan=30days&format=json"],
 ["blockchain-info-addr", "https://api.blockchain.info/charts/n-unique-addresses?timespan=30days&format=json"],
 ["yahoo-btc", "https://query1.finance.yahoo.com/v8/finance/chart/BTC-USD?range=5d&interval=1d"]
];
for (const [n, u] of T) {
  try { const r = await fetch(u, { headers: { "user-agent": UA, accept: "application/json" }, signal: AbortSignal.timeout(20000) });
    const t = await r.text(); console.log(`PROBE ${n}: HTTP ${r.status} ${t.slice(0, 400).replace(/\s+/g, " ")}`);
  } catch (e) { console.log(`PROBE ${n}: FAIL ${e.cause?.code || e.message}`); }
}
