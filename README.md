# Exness MT5 five-second bot

Uses the last two **completed M1 candles**: a higher close means BUY, a lower
close means SELL, equal closes mean wait. It checks the signal before every batch.
This is a simple momentum rule, not a forecast.

Opens **ten separate positions of 0.01 lot each (0.10 lot total)** in the selected
direction, then monitors their combined floating P/L every 0.2 seconds.
Default exit rules (first one reached closes the whole batch):

- Profit target: +1.00 plus a 0.50 cost buffer, so +1.50 floating P/L.
- Loss limit: -5.00 floating P/L.
- Timeout: 60 seconds after all ten orders finish opening, even if losing.

Amounts are in account currency (USD on a USD account), for the whole batch.
Floating P/L includes swap and bid/ask spread but excludes commissions. The buffer
is an allowance, not a measurement of fees or a guarantee of realized profit.
Orders and closes execute sequentially; execution delay and slippage can move the
final P/L beyond any threshold. These are Python-managed exits, not broker-held
stop-loss or take-profit orders: they cannot run while the bot or connection is down.
This change does not establish a profitable strategy or guarantee more winning trades.
An MT5 **hedging account** is required; netting accounts are rejected.

Customize exits with `--profit-target 1 --cost-buffer 0.5 --loss-limit 5 --max-hold 60`.

## Run on Windows

1. Install 64-bit Python and the Exness MetaTrader 5 desktop terminal on the same Windows PC or VPS.
2. Log into your intended Exness account in MT5. Enable algorithmic trading and permit trading through the external Python API in MT5 settings.
3. In Market Watch, find the exact gold symbol. It may be `XAUUSD`, `XAUUSDm`, or another account-specific name.
4. Open a terminal in this folder and install:

```powershell
py -m pip install -r requirements.txt
```

Run one real ten-trade batch, replacing the account number and symbol with yours:

```powershell
py bot.py --account 12345678 --symbol XAUUSDm --cycles 1
```

For continuous ten-trade batches:

```powershell
py bot.py --account 12345678 --symbol XAUUSDm
```

If multiple terminals are installed, select yours with
`--terminal "C:\Program Files\MetaTrader 5\terminal64.exe"`.
Credentials stay in the logged-in terminal; no password belongs in this code.
The account argument verifies the connected account, rather than logging in.

0.01 means broker lots, not 0.01 ounce. The bot displays the broker's contract size.
It requires this symbol to have no existing positions or pending orders before
each cycle. Avoid concurrent trading on that symbol. Rejected, partial, or
ambiguous orders stop further entries and attempt to close all visible bot positions.
A rejected close does not prevent attempts to close the other positions.
Use only one instance of this bot per account and symbol.
Ctrl+C during monitoring attempts to close the position; a crash, lost connection,
or rejected close can leave it open. Inspect MT5 before restarting after errors.

## Validation

Order logic can be tested with `python -m unittest discover -s tests -v` without
MT5 installed. These are simulated API tests; real broker execution must be
verified on the Windows machine. Linux cloud workspaces cannot use the native
Windows MT5 Python connection.

## Research workflow: export first, then backtest

These commands do not place orders. Keep the live bot stopped while evaluating.
On your Windows machine with Exness MT5 logged in, download the latest files and run:

```powershell
python export_data.py --symbol XAUUSDm --days 7
```

This creates `market-data` containing M1 candles, historical bid/ask ticks, and
contract metadata. No account number, password, or order history is exported.
MT5 must provide the requested history; empty periods and available history vary
by broker. Tick exports can be large. An interrupted export is incomplete: delete
it or use a fresh `--output` directory before retrying. The exporter will not
overwrite existing folders. Successful completion prints `Export complete`.

Zip the completed folder with:

```powershell
Compress-Archive -Path market-data -DestinationPath market-data.zip
```

Share that ZIP for analysis, or run the backtester locally (standard Python only):

```powershell
python backtest.py market-data
```

Results are in `research-results/summary.json` and holdout trade CSVs. Use a new
`--output` folder for another run. Commission defaults to zero; if your account
charges commission, pass the actual USD round-trip amount per full lot with
`--commission`. `--slippage 0.02` models 0.02 adverse gold-price units on each fill;
it is an assumption, not measured execution quality. Repeat with higher assumed
slippage to assess sensitivity.

Three fixed candidates are compared: M1 momentum, momentum aligned with EMA9/21,
and a ten-bar closing breakout. Filtered candidates skip spreads over 15% of ATR.
All use ATR14 stop distance, 1.5x ATR target, 60-second maximum hold, and at most
one 0.01-lot position per completed candle. The first 70% of candles is training;
the last 30% is a chronological holdout. Candidates need 30 training trades for
selection; otherwise the baseline is used. Selection uses training net profit
only. Holdout data is never used to tune parameters. Repeatedly tuning after
viewing the holdout invalidates it; collect new data for further validation.

The output distinguishes insufficient data, losing holdout performance, and
positive results that still need independent testing. It never authorizes live
trading. This research model differs from the existing ten-position bot and does
not automatically change its entry or exit rules. It models spread, fixed
slippage, and commission, but not order latency, rejection, margin, floating
drawdown, or variable contract conversion. It supports linear XAUUSD CFDs in USD
only. Synthetic tests validate software behavior, not a trading edge.
