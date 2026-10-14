# Five-second spot bot

Buys at market, waits five seconds after the buy fills, sells the purchased
quantity at market, and repeats. Exchange latency adds to the actual holding time.

Try two paper cycles (prints simulated orders; no credentials or dependencies):

```sh
python bot.py --cycles 2
```

For real orders, install `python -m pip install -r requirements.txt`, set
`EXCHANGE_API_KEY` and `EXCHANGE_API_SECRET` in your environment (also
`EXCHANGE_API_PASSWORD` if your exchange requires it), then run:

```sh
python bot.py --live --exchange binance --symbol BTC/USDT --amount 0.001 --cycles 2
```

The amount is in the base asset (BTC in this example). Your account needs enough
quote currency and must meet the exchange's minimum order sizes. Omit `--cycles`
to loop indefinitely. CCXT exchange support and market-buy requirements vary;
some exchanges need custom parameters.

Errors stop the bot without retrying orders. If interrupted or an order fails,
check your orders and holdings on the exchange before restarting: the bot does
not automatically recover or close leftover positions.
